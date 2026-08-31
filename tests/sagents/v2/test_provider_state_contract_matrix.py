from __future__ import annotations

import pytest
from pydantic import ValidationError

from sagents.v2.contracts import provider_state as provider_state_contract
from sagents.v2.contracts.provider_state import (
    make_provider_state,
    read_provider_state,
)
from sagents.v2.model import ModelMessage


def test_provider_state_uses_a_versioned_protocol_namespace():
    state = make_provider_state(
        "openai_responses", {"reasoning_items": [{"type": "reasoning"}]}
    )

    message = ModelMessage(role="assistant", provider_state=state)

    assert read_provider_state(
        message.provider_state, "openai_responses"
    ) == {"reasoning_items": [{"type": "reasoning"}]}
    assert read_provider_state(message.provider_state, "anthropic_messages") is None


def test_provider_state_replays_legacy_v0_but_rejects_unknown_envelope_versions():
    legacy = {"openai_compatible": {"reasoning_content": "opaque"}}
    assert read_provider_state(legacy, "openai_compatible") == {
        "reasoning_content": "opaque"
    }

    with pytest.raises(ValueError, match="unsupported provider_state version"):
        read_provider_state(
            {
                "openai_compatible": {
                    "schema_version": 99,
                    "payload": {},
                }
            },
            "openai_compatible",
        )


def test_provider_state_must_be_bounded_finite_json(monkeypatch):
    monkeypatch.setattr(provider_state_contract, "MAX_PROVIDER_STATE_BYTES", 64)

    with pytest.raises(ValidationError, match="exceeds 64 encoded bytes"):
        ModelMessage(
            role="assistant",
            provider_state=make_provider_state(
                "openai_responses", {"opaque": "x" * 100}
            ),
        )

    with pytest.raises(ValidationError, match="finite JSON data"):
        ModelMessage(
            role="assistant",
            provider_state={"openai_responses": {"value": float("nan")}},
        )
