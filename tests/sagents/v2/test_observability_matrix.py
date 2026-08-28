"""Diagnostics are optional projections and never participate in recovery."""

from __future__ import annotations

import json

import pytest

from sagents.v2.contracts.items import TextBlock
from sagents.v2.model import ModelRequest, RecordingModelProvider
from sagents.v2.model.contracts import (
    ModelEventKind,
    ModelMessage,
    ModelResponse,
    ModelStreamEvent,
)
from sagents.v2.runtime.observability import FilesystemDiagnosticSink
from sagents.v2.testing.plugins.scripted_model import (
    ScriptedModelProvider,
    ScriptedModelStep,
)


@pytest.mark.asyncio
async def test_recording_sink_keeps_requests_and_redacts_secrets(tmp_path):
    sink = FilesystemDiagnosticSink(tmp_path / "diagnostics")
    response = ModelResponse(
        response_id="response_1", text="done", finish_reason="stop"
    )
    provider = ScriptedModelProvider(
        (
            ScriptedModelStep(
                events=(
                    ModelStreamEvent(
                        kind=ModelEventKind.COMPLETED,
                        response=response,
                    ),
                )
            ),
        )
    )
    provider.diagnostic_request = lambda _request: {
        "model": "model_1",
        "extra_body": {"api_key": "sk-wire-secret"},
    }

    async def resolve_session(run_id: str) -> str:
        assert run_id == "run_1"
        return "session_1"

    recording = RecordingModelProvider(
        provider,
        sink=sink,
        session_id_resolver=resolve_session,
        provider_metadata={"api_key": "sk-provider-secret"},
    )
    request = ModelRequest(
        request_id="request_1",
        run_id="run_1",
        model_binding="primary",
        messages=(
            ModelMessage(
                role="user",
                content=(TextBlock(text="hello"),),
                metadata={"authorization": "Bearer secret"},
            ),
        ),
    )

    events = [event async for event in recording.stream(request)]
    record = await sink.get_model_request(
        session_id="session_1", run_id="run_1", request_id="request_1"
    )

    assert events[-1].response == response
    assert record["provider"]["api_key"] == "[REDACTED]"
    assert record["request"]["messages"][0]["metadata"]["authorization"] == (
        "[REDACTED]"
    )
    assert record["wire_request"]["extra_body"]["api_key"] == "[REDACTED]"
    assert await sink.list_model_requests(session_id="session_1") == (record,)
    journal = [
        json.loads(line)
        for line in (tmp_path / "diagnostics/journal.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert [value["status"] for value in journal] == ["started", "completed"]


def test_diagnostics_root_has_no_session_store_metadata(tmp_path):
    sink = FilesystemDiagnosticSink(tmp_path / "diagnostics")
    assert sink.root.is_dir()
    assert not (sink.root / "store.json").exists()
    assert not (sink.root / "sessions" / "index.json").exists()
