"""Diagnostics are optional projections and never participate in recovery."""

from __future__ import annotations

import json
from io import StringIO

import pytest

from sagents.v2.contracts.items import TextBlock, UsageSummary
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
    StdoutLogSink,
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
        response_id="response_1",
        text="done",
        finish_reason="stop",
        usage=UsageSummary(
            reported=True,
            input_tokens=10,
            output_tokens=5,
            models=("model_1",),
            provider_usage={
                "input_tokens": 10,
                "output_tokens": 5,
                "cache_write_tokens": 1,
            },
        ),
    )
    provider = ScriptedModelProvider(
        (
            ScriptedModelStep(
                events=(
                    ModelStreamEvent(
                        kind=ModelEventKind.TEXT_DELTA,
                        delta="done",
                    ),
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
    assert record["started_at"] <= record["first_token_at"]
    assert record["first_token_at"] <= record["completed_at"]
    assert record["ttfb_ms"] >= 0
    assert record["duration_ms"] >= record["ttfb_ms"]
    assert "provider" not in record
    assert "wire_request" not in record
    assert "provider_metadata" not in record["response"]
    assert record["response"]["usage"] == {
        "reported": True,
        "input_tokens": 10,
        "output_tokens": 5,
        "cached_input_tokens": 0,
        "reasoning_tokens": 0,
        "cost": None,
        "models": ["model_1"],
        "provider_usage": {
            "input_tokens": 10,
            "output_tokens": 5,
            "cache_write_tokens": 1,
        },
    }
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


def test_structured_stdout_logs_share_schema_redact_and_respect_min_level():
    output = StringIO()
    sink = StdoutLogSink(stream="stdout", min_level=LogLevel.INFO, output=output)
    logger = StructuredLogger(sink, "test.agent").bind(
        session_id="session_1",
        run_id="run_1",
    )

    logger.debug("agent.debug", "should be filtered")
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

    rows = [
        json.loads(line) for line in output.getvalue().splitlines() if line
    ]
    assert [value["event"] for value in rows] == [
        "agent.run.started",
        "tool.call.failed",
    ]
    assert all(value["format_version"] == "sage.log/v1" for value in rows)
    serialized = json.dumps(rows)
    assert "top-secret" not in serialized
    assert "sk-secret-value" not in serialized
    assert rows[0]["run_id"] == "run_1"
    assert rows[1]["error"]["type"] == "ValueError"


def test_stdout_log_sink_rejects_unknown_stream():
    with pytest.raises(ValueError, match="stdout"):
        StdoutLogSink(stream="file")


@pytest.mark.asyncio
async def test_stdout_logging_plugin_is_selectable_from_the_official_registry():
    from sagents.v2.runtime.extensions import (
        CapabilityRequirement,
        ExtensionHost,
        ExtensionScope,
        ExtensionScopeContext,
    )
    from sagents.v2.runtime.extensions.defaults import builtin_extension_registry

    host = ExtensionHost(builtin_extension_registry())
    plan = host.plan(
        (CapabilityRequirement(capability="observability.log-sink", api_version="2"),),
        selections={"observability.log-sink": "sage.logging.stdout"},
        configs={"sage.logging.stdout": {"stream": "stderr", "min_level": "warning"}},
        scope_overrides={"sage.logging.stdout": ExtensionScope.PROCESS},
    )
    handle = host.open_scope_sync(
        ExtensionScopeContext(scope=ExtensionScope.PROCESS, scope_id="test-stdout"),
        plan,
    )
    sink = handle.providers.require_unique("observability.log-sink")
    assert isinstance(sink, StdoutLogSink)
    assert sink.stream == "stderr"
    assert sink.min_level == LogLevel.WARNING
    await handle.close()


class _CapturingTraceSink:
    format_version = "sage.trace/v1"

    def __init__(self) -> None:
        self.started = []
        self.events = []
        self.ended = []

    def start_span(self, span):
        self.started.append(span)

    def add_event(self, span_id, event):
        self.events.append((span_id, event))

    def end_span(self, span):
        self.ended.append(span)

    def close(self) -> None:
        return None


def test_session_trace_id_is_stable_and_128_bit():
    from sagents.v2.runtime.observability import session_trace_id

    first = session_trace_id("session_1")
    assert first == session_trace_id("session_1")
    assert first != session_trace_id("session_2")
    assert len(first) == 32
    int(first, 16)


@pytest.mark.asyncio
async def test_resolve_root_session_id_walks_parent_chain():
    from sagents.v2.runtime.observability import resolve_root_session_id

    sessions = {
        "child": type("Session", (), {"parent_session_id": "mid"})(),
        "mid": type("Session", (), {"parent_session_id": "root"})(),
        "root": type("Session", (), {"parent_session_id": None})(),
    }

    async def get_session(session_id: str):
        return sessions[session_id]

    assert await resolve_root_session_id(get_session, "child") == "root"
    assert await resolve_root_session_id(get_session, "root") == "root"


def test_structured_tracer_nests_child_spans_on_the_active_trace():
    from sagents.v2.runtime.observability import (
        StructuredTracer,
        TraceKind,
        current_trace_context,
        session_trace_id,
    )

    sink = _CapturingTraceSink()
    parent = StructuredTracer(
        sink,
        "agent",
        trace_id=session_trace_id("session_1"),
    ).start_span("agent.run", kind=TraceKind.INTERNAL, session_id="session_1")
    assert current_trace_context() == (parent.span.trace_id, parent.span.span_id)
    child = StructuredTracer(sink, "model").start_span(
        "model.request",
        kind=TraceKind.CLIENT,
        session_id="session_1",
        trace_id=session_trace_id("session_1"),
    )
    child.end()
    parent.end()

    assert sink.started[0].name == "agent.run"
    assert sink.started[1].name == "model.request"
    assert sink.started[1].trace_id == sink.started[0].trace_id
    assert sink.started[1].parent_span_id == sink.started[0].span_id
    assert current_trace_context() is None


def test_nested_span_keeps_active_trace_when_child_session_differs():
    from sagents.v2.runtime.observability import (
        StructuredTracer,
        TraceKind,
        session_trace_id,
    )

    sink = _CapturingTraceSink()
    parent = StructuredTracer(
        sink,
        "agent",
        trace_id=session_trace_id("root"),
    ).start_span("agent.run", kind=TraceKind.INTERNAL, session_id="root")
    child = StructuredTracer(sink, "agent").start_span(
        "agent.run",
        kind=TraceKind.INTERNAL,
        session_id="forked",
        trace_id=session_trace_id("forked"),
    )
    child.end()
    parent.end()

    assert child.span.trace_id == parent.span.trace_id == session_trace_id("root")
    assert child.span.parent_span_id == parent.span.span_id
    assert child.span.session_id == "forked"


def test_structured_tracer_records_redacted_span_timing():
    from sagents.v2.runtime.observability import StructuredTracer, TraceKind, TraceStatus

    sink = _CapturingTraceSink()
    tracer = StructuredTracer(sink, "test.agent").bind(session_id="session_1")
    span = tracer.start_span(
        "model.request",
        kind=TraceKind.CLIENT,
        run_id="run_1",
        request_id="request_1",
        attributes={"api_key": "sk-secret-value"},
    )
    span.add_event("first_token")
    span.end(TraceStatus.OK, attributes={"ttfb_ms": 12.5, "duration_ms": 40.0})

    assert len(sink.started) == 1
    assert sink.started[0].attributes["api_key"] == "[REDACTED]"
    assert sink.events[0][1].name == "first_token"
    ended = sink.ended[0]
    assert ended.status is TraceStatus.OK
    assert ended.attributes["ttfb_ms"] == 12.5
    assert ended.attributes["duration_ms"] == 40.0
    assert ended.attributes["component"] == "test.agent"
    assert ended.run_id == "run_1"


@pytest.mark.asyncio
async def test_recording_provider_emits_model_request_spans(tmp_path):
    from sagents.v2.runtime.observability import (
        FilesystemDiagnosticSink,
        TraceStatus,
    )

    sink = FilesystemDiagnosticSink(tmp_path / "diagnostics")
    traces = _CapturingTraceSink()
    response = ModelResponse(
        response_id="response_1", text="done", finish_reason="stop"
    )
    provider = ScriptedModelProvider(
        (
            ScriptedModelStep(
                events=(
                    ModelStreamEvent(kind=ModelEventKind.TEXT_DELTA, delta="done"),
                    ModelStreamEvent(
                        kind=ModelEventKind.COMPLETED,
                        response=response,
                    ),
                )
            ),
        )
    )

    async def resolve_session(run_id: str) -> str:
        return "session_1"

    recording = RecordingModelProvider(
        provider,
        sink=sink,
        trace_sink=traces,
        session_id_resolver=resolve_session,
        provider_metadata={"purpose": "agent"},
    )
    request = ModelRequest(
        request_id="request_1",
        run_id="run_1",
        model_binding="primary",
        messages=(
            ModelMessage(role="user", content=(TextBlock(text="hello"),)),
        ),
    )
    [event async for event in recording.stream(request)]

    from sagents.v2.runtime.observability import session_trace_id

    assert traces.started[0].name == "model.request"
    assert traces.started[0].trace_id == session_trace_id("session_1")
    assert traces.events[0][1].name == "first_token"
    ended = traces.ended[0]
    assert ended.status is TraceStatus.OK
    assert ended.attributes["ttfb_ms"] >= 0
    assert ended.attributes["duration_ms"] >= ended.attributes["ttfb_ms"]


@pytest.mark.asyncio
async def test_trace_noop_plugin_is_the_default_official_sink():
    from sagents.v2.runtime.extensions import (
        CapabilityRequirement,
        ExtensionHost,
        ExtensionScope,
        ExtensionScopeContext,
    )
    from sagents.v2.runtime.extensions.defaults import builtin_extension_registry
    from sagents.v2.runtime.observability import NoopTraceSink, otel_available

    registry = builtin_extension_registry()
    otlp = registry.get("sage.trace.otlp").descriptor
    host = ExtensionHost(registry)
    plan = host.plan(
        (CapabilityRequirement(capability="observability.trace-sink", api_version="2"),),
        selections={"observability.trace-sink": "sage.trace.noop"},
        scope_overrides={"sage.trace.noop": ExtensionScope.PROCESS},
    )
    handle = host.open_scope_sync(
        ExtensionScopeContext(scope=ExtensionScope.PROCESS, scope_id="test-trace"),
        plan,
    )
    sink = handle.providers.require_unique("observability.trace-sink")
    assert isinstance(sink, NoopTraceSink)
    assert otlp.availability.available is otel_available()
    await handle.close()


@pytest.mark.asyncio
async def test_otlp_trace_sink_maps_spans_when_sdk_is_installed():
    from sagents.v2.runtime.observability import otel_available

    if not otel_available():
        pytest.skip("optional opentelemetry packages are not installed")

    from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
        InMemorySpanExporter,
    )

    from sagents.v2.runtime.observability import (
        OtlpTraceSink,
        StructuredTracer,
        TraceKind,
        TraceStatus,
    )

    exporter = InMemorySpanExporter()
    sink = OtlpTraceSink(
        endpoint="http://127.0.0.1:4317",
        service_name="sage-test",
        exporter=exporter,
    )
    tracer = StructuredTracer(sink, "test.otlp")
    span = tracer.start_span(
        "model.request",
        kind=TraceKind.CLIENT,
        session_id="session_1",
        attributes={"api_key": "sk-secret-value"},
    )
    span.add_event("first_token")
    span.end(TraceStatus.OK, attributes={"duration_ms": 8.0})
    sink.close()

    exported = exporter.get_finished_spans()
    assert len(exported) == 1
    assert exported[0].name == "model.request"
    assert exported[0].attributes["api_key"] == "[REDACTED]"
    assert exported[0].attributes["duration_ms"] == 8.0
    assert exported[0].attributes["session_id"] == "session_1"


@pytest.mark.asyncio
async def test_loop_emits_session_scoped_run_model_and_tool_spans():
    from sagents.v2.runtime.observability import (
        NoopDiagnosticSink,
        session_trace_id,
    )

    from tests.sagents.v2.test_agent_loop_matrix import (
        CONTEXT,
        completed,
        setup_loop,
        tool_call,
    )

    traces = _CapturingTraceSink()
    runtime_holder = {}

    async def resolve_session(run_id: str) -> str:
        return (await runtime_holder["runtime"].get_run(run_id)).session_id

    inner = ScriptedModelProvider(
        (
            ScriptedModelStep(events=(completed("", calls=(tool_call(),)),)),
            ScriptedModelStep(events=(completed("the answer is 42"),)),
        )
    )
    model = RecordingModelProvider(
        inner,
        sink=NoopDiagnosticSink(),
        trace_sink=traces,
        session_id_resolver=resolve_session,
    )
    runtime, handle, loop, executor = await setup_loop(model, trace_sink=traces)
    runtime_holder["runtime"] = runtime
    result = await loop.execute(handle.run_id, CONTEXT)

    assert result.state.value == "completed"
    assert len(executor.calls) == 1
    names = [span.name for span in traces.started]
    assert names.count("agent.run") == 1
    assert names.count("model.request") == 2
    assert names.count("tool.call") == 1
    by_name = {span.name: span for span in traces.started if span.name != "model.request"}
    model_spans = [span for span in traces.started if span.name == "model.request"]
    run_span = by_name["agent.run"]
    tool_span = by_name["tool.call"]
    expected_trace = session_trace_id(handle.session_id)
    assert run_span.trace_id == expected_trace
    assert {span.trace_id for span in traces.started} == {expected_trace}
    assert all(span.parent_span_id == run_span.span_id for span in model_spans)
    assert tool_span.parent_span_id == run_span.span_id
    assert run_span.attributes["user_input"] == "do task"
    assert tool_span.attributes["tool_name"] == "read_value"
    ended_run = next(span for span in traces.ended if span.name == "agent.run")
    assert ended_run.attributes["run_state"] == "completed"


@pytest.mark.asyncio
async def test_forked_child_run_joins_parent_session_trace():
    from sagents.v2.agent import AgentLoopEngine
    from sagents.v2.agent.multi_agent import (
        AgentDescriptor,
        DelegationTask,
        WorkspaceSharingPolicy,
    )
    from sagents.v2.agent.multi_agent.executors import LoopChildRunExecutor
    from sagents.v2.context import DefaultContextAssembler
    from sagents.v2.contracts.commands import InputItem, StartRun
    from sagents.v2.contracts.principals import (
        ActorRef,
        PrincipalType,
        RequestContext,
    )
    from sagents.v2.runtime.observability import NoopDiagnosticSink, session_trace_id
    from sagents.v2.testing.runtime import ephemeral_runtime
    from sagents.v2.tool import (
        InMemoryToolCatalog,
        InMemoryToolExecutor,
        ToolCall,
        ToolExecutionResult,
    )

    traces = _CapturingTraceSink()
    context = RequestContext(
        actor=ActorRef(
            principal_id="leader",
            principal_type=PrincipalType.AGENT,
            scopes=frozenset({"agent.delegate"}),
        )
    )
    runtime = ephemeral_runtime()
    parent = await runtime.start_run(
        StartRun(
            agent_id="leader",
            input=(InputItem(role="user", content=(TextBlock(text="root"),)),),
            resolved_spec_hash="sha256:parent",
            idempotency_key="parent_trace",
        ),
        context,
    )
    await runtime.start_execution(
        run_id=parent.run_id,
        expected_revision=0,
        context=context,
        idempotency_key="parent_trace_execute",
    )

    async def resolve_session(run_id: str) -> str:
        return (await runtime.get_run(run_id)).session_id

    def child_loop(descriptor, run_id):
        del run_id
        inner = ScriptedModelProvider(
            (ScriptedModelStep(events=(
                ModelStreamEvent(
                    kind=ModelEventKind.COMPLETED,
                    response=ModelResponse(
                        response_id="child_done",
                        text="child done",
                        finish_reason="stop",
                    ),
                ),
            )),)
        )
        return AgentLoopEngine(
            runtime=runtime,
            model=RecordingModelProvider(
                inner,
                sink=NoopDiagnosticSink(),
                trace_sink=traces,
                session_id_resolver=resolve_session,
            ),
            tool_catalog=InMemoryToolCatalog(()),
            tool_executor=InMemoryToolExecutor({}, {}),
            context_assembler=DefaultContextAssembler(
                developer_instructions=descriptor.instructions
            ),
            trace_sink=traces,
        )

    executor = LoopChildRunExecutor(
        runtime=runtime,
        loop_factory=child_loop,
        resolved_spec_hash="sha256:children",
    )
    parent_loop = AgentLoopEngine(
        runtime=runtime,
        model=ScriptedModelProvider(()),
        tool_catalog=InMemoryToolCatalog(()),
        tool_executor=InMemoryToolExecutor({}, {}),
        trace_sink=traces,
    )

    async def parent_body(run_id, request_context):
        run = await runtime.get_run(run_id)

        async def tool_body(run, call, request_context, turn_id, step_id=None, state=None):
            del call, turn_id, step_id, state
            result = await executor.run_child(
                AgentDescriptor(
                    agent_id="member",
                    name="Member",
                    description="General expert",
                    instructions="Be exact.",
                ),
                DelegationTask(
                    task_id="task_1",
                    agent_id="member",
                    task_name="Task 1",
                    original_task="root",
                    content="work 1",
                ),
                parent_run_id=run.run_id,
                workspace_policy=WorkspaceSharingPolicy.SHARED_PARENT,
                context=request_context,
            )
            text = result.content[0].text if result.content else str(result.outcome)
            return run, ToolExecutionResult(
                tool_call_id="call_delegate",
                operation_id="op_delegate",
                content=(TextBlock(text=text),),
            )

        run, _ = await parent_loop.trace_tool_call(
            run,
            ToolCall(
                tool_call_id="call_delegate",
                tool_name="sys_delegate_task",
                arguments={"tasks": [{"agent_id": "member", "content": "work 1"}]},
                operation_id="op_delegate",
                idempotency_key="delegate_1",
                owner_run_id=run.run_id,
            ),
            request_context,
            "turn_1",
            body=tool_body,
        )
        return run

    snapshot = await parent_loop.trace_run(
        parent.run_id, context, resumed=False, body=parent_body
    )
    child_runs = [
        span for span in traces.started if span.name == "agent.run"
    ]
    assert snapshot.session_id == parent.session_id
    assert len(child_runs) == 2
    parent_run, child_run = child_runs
    tool_span = next(span for span in traces.started if span.name == "tool.call")
    model_span = next(span for span in traces.started if span.name == "model.request")
    expected_trace = session_trace_id(parent.session_id)
    assert {span.trace_id for span in traces.started} == {expected_trace}
    assert child_run.session_id != parent.session_id
    assert child_run.attributes["root_session_id"] == parent.session_id
    assert child_run.attributes["parent_session_id"] == parent.session_id
    assert child_run.parent_span_id == tool_span.span_id
    assert tool_span.parent_span_id == parent_run.span_id
    assert model_span.parent_span_id == child_run.span_id
    assert model_span.trace_id == expected_trace
