from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from sagents.v2.contracts.events import (
    EventDurability,
    EventSource,
    EventSourceType,
    RunEventData,
    RuntimeEvent,
)
from sagents.v2.contracts.principals import ActorRef, PrincipalType
from sagents.v2.contracts.errors import SageV2Error
from sagents.v2.runtime.session.codec.events import EventCodec, EventUpcasterRegistry


def runtime_event():
    return RuntimeEvent(
        event_id="event_1",
        type="run.started",
        occurred_at=datetime(2026, 8, 25, tzinfo=timezone.utc),
        durability=EventDurability.DURABLE,
        session_id="session_1",
        run_id="run_1",
        session_sequence=1,
        run_sequence=1,
        actor=ActorRef(principal_id="worker_1", principal_type=PrincipalType.WORKER),
        source=EventSource(source_type=EventSourceType.RUNTIME),
        data=RunEventData(state="running"),
    )


def envelope_for(payload):
    import hashlib

    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()
    return json.dumps(
        {
            "storage_format_version": "sage.event-envelope/v1",
            "payload_hash": f"sha256:{hashlib.sha256(encoded).hexdigest()}",
            "event": payload,
        }
    ).encode()


def test_current_event_round_trip_is_deterministic():
    codec = EventCodec()
    event = runtime_event()
    first = codec.encode(event)
    second = codec.encode(event)
    assert first == second
    assert codec.decode(first) == event


def test_n_minus_one_upcaster_chain_produces_current_contract():
    registry = EventUpcasterRegistry()

    def v0_to_v1(payload):
        payload["data"] = {
            "kind": "run",
            "state": payload.pop("legacy_state"),
        }
        return payload

    registry.register("run.started", "0", "1", v0_to_v1)
    payload = runtime_event().model_dump(mode="json")
    payload["event_schema_version"] = "0"
    payload["legacy_state"] = payload.pop("data")["state"]
    restored = EventCodec(registry).decode(envelope_for(payload))
    assert restored.event_schema_version == "1"
    assert restored.data.state == "running"


def test_n_minus_two_requires_complete_upcaster_chain():
    registry = EventUpcasterRegistry()

    def v_minus_one_to_v0(payload):
        payload["legacy_state"] = payload.pop("old_state")
        return payload

    def v0_to_v1(payload):
        payload["data"] = {
            "kind": "run",
            "state": payload.pop("legacy_state"),
        }
        return payload

    registry.register(
        "run.started",
        "-1",
        "0",
        v_minus_one_to_v0,
    )
    registry.register(
        "run.started",
        "0",
        "1",
        v0_to_v1,
    )
    payload = runtime_event().model_dump(mode="json")
    payload["event_schema_version"] = "-1"
    payload["old_state"] = payload.pop("data")["state"]
    assert EventCodec(registry).decode(envelope_for(payload)).data.state == "running"


@pytest.mark.parametrize(
    ("mutation", "error_code"),
    [
        ("json", "event.corrupt_envelope"),
        ("hash", "event.hash_mismatch"),
        ("payload", "event.corrupt_payload"),
        ("version", "event.unsupported_event_schema"),
    ],
)
def test_corruption_and_unsupported_schema_matrix(mutation, error_code):
    codec = EventCodec()
    if mutation == "json":
        encoded = b"not-json"
    else:
        payload = runtime_event().model_dump(mode="json")
        if mutation == "payload":
            payload["run_id"] = ""
        elif mutation == "version":
            payload["event_schema_version"] = "999"
        encoded = envelope_for(payload)
        if mutation == "hash":
            raw = json.loads(encoded)
            raw["payload_hash"] = "sha256:bad"
            encoded = json.dumps(raw).encode()
    with pytest.raises(SageV2Error) as exc_info:
        codec.decode(encoded)
    assert exc_info.value.info.code == error_code


def test_duplicate_upcaster_and_non_advancing_registration_rejected():
    registry = EventUpcasterRegistry()
    with pytest.raises(ValueError, match="advance"):
        registry.register("run.started", "0", "0", lambda payload: payload)
    registry.register("run.started", "0", "1", lambda payload: payload)
    with pytest.raises(ValueError, match="already registered"):
        registry.register("run.started", "0", "1", lambda payload: payload)


def test_upcaster_exception_is_typed_as_corrupt_state():
    registry = EventUpcasterRegistry()

    def broken(payload):
        raise KeyError("missing")

    registry.register("run.started", "0", "1", broken)
    payload = runtime_event().model_dump(mode="json")
    payload["event_schema_version"] = "0"
    with pytest.raises(SageV2Error) as failed:
        EventCodec(registry).decode(envelope_for(payload))
    assert failed.value.info.code == "event.upcast_failed"
