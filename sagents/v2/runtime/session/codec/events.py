"""Version, integrity, and upcasting boundary for persisted RuntimeEvents."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from typing import Any, Literal


from sagents.v2.contracts.common import StrictModel
from sagents.v2.contracts.errors import (
    ErrorCategory,
    RuntimeErrorInfo,
    SageV2Error,
)
from sagents.v2.contracts.events import RuntimeEvent


CURRENT_EVENT_SCHEMA_VERSION = "1"
Upcaster = Callable[[dict[str, Any]], dict[str, Any]]


class EventIntegrityEnvelope(StrictModel):
    storage_format_version: Literal["sage.event-envelope/v1"] = "sage.event-envelope/v1"
    payload_hash: str
    event: dict[str, Any]


class EventUpcasterRegistry:
    def __init__(self) -> None:
        self._upcasters: dict[tuple[str, str], tuple[str, Upcaster]] = {}

    def register(
        self,
        event_type: str,
        from_version: str,
        to_version: str,
        upcaster: Upcaster,
    ) -> None:
        key = (event_type, from_version)
        if key in self._upcasters:
            raise ValueError(f"upcaster already registered for {key}")
        if from_version == to_version:
            raise ValueError("upcaster must advance the schema version")
        self._upcasters[key] = (to_version, upcaster)

    def upcast(
        self,
        payload: Mapping[str, Any],
        *,
        target_version: str = CURRENT_EVENT_SCHEMA_VERSION,
    ) -> dict[str, Any]:
        current = dict(payload)
        visited: set[tuple[str, str]] = set()
        while str(current.get("event_schema_version")) != target_version:
            event_type = str(current.get("type") or "")
            version = str(current.get("event_schema_version") or "")
            key = (event_type, version)
            if key in visited:
                raise self._error(
                    "event.upcaster_cycle",
                    ErrorCategory.CORRUPT_STATE,
                    f"upcaster cycle detected for {key}",
                )
            visited.add(key)
            registered = self._upcasters.get(key)
            if registered is None:
                raise self._error(
                    "event.unsupported_event_schema",
                    ErrorCategory.UNSUPPORTED_SCHEMA,
                    f"no upcaster for event {event_type!r} schema {version!r}",
                )
            to_version, function = registered
            try:
                current = function(dict(current))
            except SageV2Error:
                raise
            except Exception as exc:
                raise self._error(
                    "event.upcast_failed",
                    ErrorCategory.CORRUPT_STATE,
                    f"failed to upcast {event_type!r} from {version!r}: {exc}",
                ) from exc
            current["event_schema_version"] = to_version
        return current

    @staticmethod
    def _error(code, category, message):
        return SageV2Error(
            RuntimeErrorInfo(code=code, category=category, message=message)
        )


class EventCodec:
    """Encode immutable event envelopes and reject corruption or unknown schema.

    Upcasting changes the reader's in-memory representation; it never rewrites
    historical audit facts in place.
    """

    def __init__(self, upcasters: EventUpcasterRegistry | None = None) -> None:
        self.upcasters = upcasters or EventUpcasterRegistry()

    def encode(self, event: RuntimeEvent) -> bytes:
        payload = event.model_dump(mode="json")
        encoded_payload = self._canonical(payload)
        envelope = EventIntegrityEnvelope(
            payload_hash=f"sha256:{hashlib.sha256(encoded_payload).hexdigest()}",
            event=payload,
        )
        return self._canonical(envelope.model_dump(mode="json"))

    def decode(self, encoded: bytes | str) -> RuntimeEvent:
        try:
            raw = json.loads(encoded)
            envelope = EventIntegrityEnvelope.model_validate(raw)
        except Exception as exc:
            raise self._error(
                "event.corrupt_envelope",
                ErrorCategory.CORRUPT_STATE,
                f"event envelope is invalid: {exc}",
            ) from exc
        actual = f"sha256:{hashlib.sha256(self._canonical(envelope.event)).hexdigest()}"
        if actual != envelope.payload_hash:
            raise self._error(
                "event.hash_mismatch",
                ErrorCategory.CORRUPT_STATE,
                "event payload hash does not match envelope",
            )
        payload = self.upcasters.upcast(envelope.event)
        try:
            return RuntimeEvent.model_validate(payload)
        except Exception as exc:
            raise self._error(
                "event.corrupt_payload",
                ErrorCategory.CORRUPT_STATE,
                f"event payload is invalid after upcast: {exc}",
            ) from exc

    @staticmethod
    def _canonical(value: Any) -> bytes:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")

    @staticmethod
    def _error(code, category, message):
        return SageV2Error(
            RuntimeErrorInfo(code=code, category=category, message=message)
        )
