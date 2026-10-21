"""Rolling task state and partial provider evidence survive repeated requests."""

from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from sagents.v2.model.contracts import ModelEventKind
    from sagents.v2.runtime.observability.contracts import DiagnosticSink

from sagents.v2.model.provider import ModelProvider
import asyncio
import json

import pytest

from sagents.v2.context.contracts import ContextReductionScope
from sagents.v2.context.plugins._shared.progress_summary import bounded_snapshot
from sagents.v2.context.summary import SummarizationRequest
from sagents.v2.contracts.items import TextBlock
from sagents.v2.model.contracts import ModelMessage, ModelRequest, ModelStreamEvent
from sagents.v2.model.middleware.recording import RecordingModelProvider
from sagents.v2.model.wire_diagnostics import record_wire_event


def summary_request(previous=None):
    return SummarizationRequest(scope=ContextReductionScope(context_key="test", session_id="s", run_id="r"),
        previous_summary=previous, target_tokens=512,
        messages=(ModelMessage(role="user", content=(TextBlock(text="Keep the completed file /project/result.py and finish the remaining tests."),)),))


def test_twenty_one_compactions_replace_one_snapshot_without_nested_history():
    summary = None
    for _ in range(21):
        summary = bounded_snapshot(summary_request(summary))
    assert "Previous summary" not in cast('str', summary)
    assert "New history" not in cast('str', summary)
    assert len(cast(str, summary)) < 1536
    state = json.loads(cast('str | bytes | bytearray', summary))
    assert len(state["user_requirements"]) == 1
    assert "/project/result.py" in state["user_requirements"][0]


def test_model_summary_is_not_overwritten_by_an_old_pending_todo_snapshot():
    previous = json.dumps({"todo_state_at_compaction_boundary": [{"content": "write the file", "status": "pending"}]})
    updated = {"summary": "The file has been written and verified.", "decisions": [],
        "open_tasks": [], "files_touched": ["/project/result.py"], "commands_run": [],
        "important_errors": [], "user_requirements": []}
    result = json.loads(bounded_snapshot(summary_request(previous), updated))
    assert result["open_tasks"] == []
    assert result["summary"] == updated["summary"]
    assert result["files_touched"] == ["/project/result.py"]


@pytest.mark.asyncio
async def test_concurrent_failed_streams_keep_separate_wire_and_partial_evidence():
    class Sink:
        def __init__(self):
            self.streams = {}
            self.failures = []
            self.requests = {}
        async def begin_model_request(self, **kwargs):
            self.requests[kwargs["request"].request_id] = kwargs["wire_request"]
        async def fail_model_request(self, **kwargs):
            self.failures.append(kwargs["request"].request_id)
        async def record_model_stream(self, **kwargs):
            self.streams[kwargs["request"].request_id] = kwargs["evidence"]

    class Provider:
        async def diagnostic_request(self, request):
            return {"model": request.request_id, "messages": []}
        async def stream(self, request):
            record_wire_event({"request": request.request_id, "arguments": '{"incomplete":'})
            await asyncio.sleep(0)
            yield ModelStreamEvent(kind=cast('ModelEventKind', "text_delta"), delta=request.request_id)
            raise ValueError("invalid streamed tool arguments")

    sink = Sink()
    async def session_id(run_id):
        return "session"
    provider = RecordingModelProvider(cast(ModelProvider, Provider()), sink=cast('DiagnosticSink', sink), session_id_resolver=session_id)
    async def consume(identifier):
        request = ModelRequest(request_id=identifier, run_id="run", model_binding="primary", messages=())
        with pytest.raises(ValueError, match="invalid streamed"):
            async for _ in provider.stream(request):
                pass
    await asyncio.gather(consume("first"), consume("second"))
    assert set(sink.failures) == {"first", "second"}
    for identifier, evidence in sink.streams.items():
        assert evidence["wire_events"] == [{"request": identifier, "arguments": '{"incomplete":'}]
        assert evidence["normalized_events"][0]["delta"] == identifier
        assert evidence["wire_capture_available"] is True
        assert sink.requests[identifier]["model"] == identifier
