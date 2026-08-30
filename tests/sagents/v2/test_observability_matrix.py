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
from sagents.v2.runtime.observability import (
    FilesystemDiagnosticSink,
    FilesystemLogSink,
    LogLevel,
    StructuredLogger,
)
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
        "messages": [
            {
                "role": "user",
                "content": "hello",
                "authorization": "Bearer secret",
            }
        ],
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
    assert record["format_version"] == "sage.model-diagnostics/v2"
    assert record["index"] == 0
    assert record["kind"] == "agent"
    assert record["metadata"]["api_key"] == "[REDACTED]"
    assert record["request"]["messages"][0]["authorization"] == "[REDACTED]"
    assert record["request"]["extra_body"]["api_key"] == "[REDACTED]"
    assert "provider" not in record
    assert "wire_request" not in record
    assert "provider_metadata" not in record["response"]
    assert await sink.list_model_requests(session_id="session_1") == (record,)
    request_paths = list(
        (
            tmp_path
            / "diagnostics/session_1/runs/run_1/llm_requests"
        ).glob("*.json")
    )
    assert len(request_paths) == 1
    assert request_paths[0].name.startswith("00000000_agent_")
    assert request_paths[0].name.endswith("Z.json")
    assert not (tmp_path / "diagnostics/journal.jsonl").exists()


@pytest.mark.asyncio
async def test_request_filenames_sort_by_start_order_and_include_kind(tmp_path):
    sink = FilesystemDiagnosticSink(tmp_path / "diagnostics")
    response = ModelResponse(
        response_id="response_1", text="done", finish_reason="stop"
    )
    requests = (
        ModelRequest(
            request_id="request_agent",
            run_id="run_1",
            model_binding="primary",
            messages=(ModelMessage(role="user", content=(TextBlock(text="one"),)),),
        ),
        ModelRequest(
            request_id="request_judge",
            run_id="run_1",
            model_binding="fast",
            messages=(ModelMessage(role="user", content=(TextBlock(text="two"),)),),
            metadata={"purpose": "continuation_judge"},
        ),
    )

    for request in requests:
        await sink.begin_model_request(
            session_id="session_1",
            request=request,
            provider={},
            wire_request={"model": "model_1", "messages": []},
        )
        await sink.complete_model_request(
            session_id="session_1", request=request, response=response
        )

    directory = tmp_path / "diagnostics/session_1/runs/run_1/llm_requests"
    names = [path.name for path in sorted(directory.glob("*.json"))]
    assert names[0].startswith("00000000_agent_")
    assert names[1].startswith("00000001_completion_judge_")
    assert [
        value["request_id"]
        for value in await sink.list_model_requests(session_id="session_1")
    ] == ["request_agent", "request_judge"]
    assert (
        await sink.get_model_request(
            session_id="session_1", run_id="run_1", request_id="request_judge"
        )
    )["kind"] == "completion_judge"


@pytest.mark.asyncio
async def test_colocated_sink_migrates_legacy_diagnostics_into_the_run(tmp_path):
    legacy_directory = (
        tmp_path
        / "legacy/sessions/session_1/runs/run_1/requests"
    )
    legacy_directory.mkdir(parents=True)
    legacy_record = {
        "format_version": "sage.model-diagnostics/v1",
        "status": "completed",
        "session_id": "session_1",
        "run_id": "run_1",
        "request_id": "legacy_request",
        "started_at": "2026-08-29T00:00:00+00:00",
        "request": {"model": "legacy_model"},
        "response": {"text": "legacy"},
    }
    (legacy_directory / "legacy_request.json").write_text(
        json.dumps(legacy_record), encoding="utf-8"
    )
    sink = FilesystemDiagnosticSink(
        tmp_path / "sessions", legacy_root=tmp_path / "legacy"
    )

    assert (
        await sink.get_model_request(
            session_id="session_1",
            run_id="run_1",
            request_id="legacy_request",
        )
    ) == legacy_record
    assert await sink.list_model_requests(session_id="session_1") == (
        legacy_record,
    )
    migrated = list(
        (
            tmp_path / "sessions/session_1/runs/run_1/llm_requests"
        ).glob("*.json")
    )
    assert len(migrated) == 1
    assert migrated[0].name.startswith("00000000_agent_")
    assert not legacy_directory.exists()
    assert not (tmp_path / "legacy").exists()


def test_diagnostics_root_has_no_session_store_metadata(tmp_path):
    sink = FilesystemDiagnosticSink(tmp_path / "diagnostics")
    assert sink.root.is_dir()
    assert not (sink.root / "store.json").exists()
    assert not (sink.root / "sessions" / "index.json").exists()


def test_structured_file_logs_share_schema_redact_errors_and_rotate(tmp_path):
    sink = FilesystemLogSink(
        tmp_path / "logs",
        max_bytes=1024,
        backup_count=20,
    )
    logger = StructuredLogger(sink, "test.agent").bind(
        session_id="session_1",
        run_id="run_1",
    )

    logger.info(
        "agent.run.started",
        "Agent started with Bearer top-secret",
        attributes={"api_key": "sk-secret-value", "attempt": 1},
    )
    try:
        raise ValueError("tool failed with sk-another-secret")
    except ValueError as exc:
        logger.exception(
            "tool.call.failed",
            "Tool execution failed",
            exc,
            tool_call_id="call_1",
        )
    for index in range(8):
        logger.info(
            "agent.step.completed",
            f"Step {index} completed " + ("x" * 220),
        )

    paths = sorted((tmp_path / "logs").glob("sage.jsonl*"))
    assert len(paths) >= 2
    assert sink.root.stat().st_mode & 0o777 == 0o700
    assert all(path.stat().st_mode & 0o777 == 0o600 for path in paths)
    rows = [
        json.loads(line)
        for path in paths
        for line in path.read_text(encoding="utf-8").splitlines()
    ]
    assert all(value["format_version"] == "sage.log/v1" for value in rows)
    assert all(
        {"timestamp", "level", "event", "message", "component"} <= value.keys()
        for value in rows
    )
    serialized = json.dumps(rows)
    assert "top-secret" not in serialized
    assert "sk-secret-value" not in serialized
    failed = next(value for value in rows if value["event"] == "tool.call.failed")
    assert failed["level"] == LogLevel.ERROR.value
    assert failed["run_id"] == "run_1"
    assert failed["tool_call_id"] == "call_1"
    assert failed["error"]["type"] == "ValueError"
