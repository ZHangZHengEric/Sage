"""Shared bounded evidence payloads and capture callbacks."""

from datetime import datetime
import json

from sagents.v2.contracts.common import utc_now
from .redaction import redact
from .requests import model_request_payload


class DiagnosticCapture:
    format_version = "sage.session-diagnostics/v1"
    # A model record combines request/response with two independently bounded
    # 8 MiB streams (provider wire and normalized events). The old 8 MiB row
    # limit discarded otherwise complete captures from ordinary long outputs.
    max_record_bytes = 32 * 1024 * 1024
    max_logs_per_run = 10000
    max_pending_writes = 64

    def _encode(self, value, *, redact_content=True):
        encoded = json.dumps(redact(value) if redact_content else value, ensure_ascii=False)
        size = len(encoded.encode())
        if size > self.max_record_bytes:
            return json.dumps(
                {
                    "truncated": True,
                    "reason": "record_size_limit",
                    "original_bytes": size,
                    **{
                        key: value[key]
                        for key in (
                            "session_id", "run_id", "request_id", "status",
                            "started_at", "completed_at", "first_token_at", "capture_mode",
                        )
                        if key in value
                    },
                }
            )
        return encoded

    async def begin_model_request(
        self, *, session_id, request, provider, wire_request=None, observed_at=None
    ):
        self._record_model_change(
            session_id,
            request,
            {
                "format_version": self.format_version,
                "status": "started",
                "started_at": (observed_at or utc_now()).isoformat(),
                "request_format": "provider_wire"
                if wire_request is not None
                else "normalized",
                "request": model_request_payload(request, wire_request),
                "metadata": dict(provider),
                "request_metadata": dict(request.metadata),
                "step_id": request.metadata.get("step_id"),
                "turn_id": request.metadata.get("turn_id"),
                "model_binding": getattr(request, "model_binding", None),
                "purpose": request.metadata.get("purpose", "agent"),
            },
        )

    async def complete_model_request(self, *, session_id, request, response, observed_at=None):
        self._record_model_change(
            session_id,
            request,
            {
                "status": "completed",
                "completed_at": (observed_at or utc_now()).isoformat(),
                "response_format": "normalized",
                "response": response.model_dump(mode="json"),
            },
        )

    async def fail_model_request(self, *, session_id, request, error, observed_at=None):
        self._record_model_change(
            session_id,
            request,
            {
                "status": "failed",
                "completed_at": (observed_at or utc_now()).isoformat(),
                "error": {
                    "type": type(error).__name__,
                    "message": str(error),
                    "info": error.info.model_dump(mode="json")
                    if hasattr(error, "info")
                    else None,
                },
            },
        )

    async def record_model_stream(self, *, session_id, request, evidence):
        self._record_model_change(session_id, request, {"stream": evidence})

    async def record_model_first_token(
        self, *, session_id, request, observed_at: datetime
    ):
        self._record_model_change(
            session_id,
            request,
            {"first_token_at": observed_at.isoformat()},
        )

    def _record_model_change(self, session_id, request, change):
        self._enqueue(self._update, session_id, request, change)

    def write(self, record):
        # Process-wide/HTTP records without a trusted Run association are excluded.
        if not self.available or not record.session_id or not record.run_id:
            return
        self._enqueue(self._write_log, record)
