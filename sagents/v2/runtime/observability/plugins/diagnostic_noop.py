"""Official diagnostic-sink plugin: discard every model-request projection."""

from __future__ import annotations

from typing import Any


class NoopDiagnosticSink:
    """Safe default used until a host explicitly selects a diagnostic sink."""

    plugin_id = "sage.observability.noop"
    name = "No-op diagnostic sink"
    description = "Discards model diagnostics."

    async def begin_model_request(self, **kwargs: Any) -> None:
        return None

    async def complete_model_request(self, **kwargs: Any) -> None:
        return None

    async def record_model_first_token(self, **kwargs: Any) -> None:
        return None

    async def fail_model_request(self, **kwargs: Any) -> None:
        return None


class UnavailableEvidence(NoopDiagnosticSink):
    available = False
    raw_capture = False
    capture_failures = 0

    def write(self, record):
        pass

    async def list_model_requests(self, **kwargs):
        return ()

    async def get_model_request(self, **kwargs):
        raise KeyError("model evidence is not collected by this provider")

    async def export_evidence(self, session_id, run_ids):
        return {
            "models": [],
            "logs": [],
            "unavailable": True,
            "evidence_source": "not_collected",
        }


class UnqueryableDiagnostics(NoopDiagnosticSink):
    """An exporter without a supported query API must not enable local capture."""

    available = False
    raw_capture = False
    capture_failures = 0
    closed = False

    def __init__(self, backend):
        self.backend = backend

    def write(self, record):
        pass

    async def close(self):
        self.closed = True

    async def export_evidence(self, session_id, run_ids):
        raise NotImplementedError(f"{self.backend} does not support diagnostic queries")
