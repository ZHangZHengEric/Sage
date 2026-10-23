
from typing import cast

import json
import sys
from types import SimpleNamespace

import pytest

from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo
from sagents.v2.contracts.items import ImageBlock, JsonBlock, TextBlock
from sagents.v2.tool.contracts import ToolCall, ToolExecutionResult
from sagents.v2.tool.plugins.result_file import FileToolResultProcessor
from tests.sagents.v2.test_standard_execution_configuration import (
    CONTEXT, build, package, response, run, runtime,
)
from sagents.v2.model.contracts import ModelToolCall
from sagents.v2.package.manifest.runtime import CapabilitySelection
from sagents.v2.testing.plugins import ScriptedModelProvider


CALL = ToolCall(tool_call_id="call_large", tool_name="query_sql", arguments={},
                operation_id="op_large", idempotency_key="key_large", owner_run_id="run_1")


@pytest.mark.asyncio
@pytest.mark.parametrize("limit", [1024, 12_000, 48_000])
@pytest.mark.parametrize("failed", [False, True])
async def test_result_limit_preserves_full_content_media_status_and_identity(limit, failed):
    writes = {}

    async def write(path, text, invocation):
        assert invocation.call == CALL
        writes[path] = text
        return "/workspace/" + path

    image = ImageBlock(uri="https://example.invalid/image.png", mime_type="image/png")
    error = RuntimeErrorInfo(code="sql.failed", category=ErrorCategory.VALIDATION,
                             message="query failed") if failed else None
    original = ToolExecutionResult(tool_call_id=CALL.tool_call_id, operation_id=CALL.operation_id,
        content=(JsonBlock(value={"rows": "中文🙂" * 15_000}), image), error=error,
        metadata={"provider_fact": "preserved"})
    processor = FileToolResultProcessor(max_inline_characters=limit)
    result = await processor.process(original, call=CALL, context=CONTEXT,
                                     runtime=SimpleNamespace(write_text=write))
    if limit == 48_000:
        assert result is original
        assert writes == {}
        return
    original_text = json.dumps(cast(JsonBlock, original.content[0]).value, ensure_ascii=False)
    assert cast(TextBlock, result.content[0]).text.startswith(original_text[:limit] + "\n\n")
    assert len(cast(TextBlock, result.content[0]).text) <= limit + 1024
    assert result.content[1] == image
    assert result.error == original.error
    assert result.operation_id == CALL.operation_id
    assert result.tool_call_id == CALL.tool_call_id
    assert result.metadata["provider_fact"] == "preserved"
    assert ToolExecutionResult.model_validate_json(next(iter(writes.values()))) == original
    assert result.metadata["context_reference"]["path"] in cast(TextBlock, result.content[0]).text
    assert await processor.process(result, call=CALL, context=CONTEXT) is result


@pytest.mark.asyncio
async def test_offload_failure_preserves_successful_tool_result_without_reexecution():
    async def fail(*args):
        raise PermissionError("workspace read-only")

    original = ToolExecutionResult(tool_call_id=CALL.tool_call_id, operation_id=CALL.operation_id,
                                   content=(TextBlock(text="x" * 45_000),))
    result = await FileToolResultProcessor().process(
        original, call=CALL, context=CONTEXT, runtime=SimpleNamespace(write_text=fail),
    )
    assert result is original
    assert result.error is None


@pytest.mark.asyncio
@pytest.mark.parametrize("alias", [None, "/workspace"])
async def test_registered_processor_bounds_next_model_request_and_persists_readable_file(tmp_path, alias):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    text = "row data 中文\n" * 5000
    (workspace / "large.txt").write_text(text)
    model = ScriptedModelProvider((response(ModelToolCall(
        tool_call_id="read", name="file_read", arguments={"file_path": "large.txt", "end_line": 5000},
    )), response()))
    selected = runtime(tmp_path)
    caps = dict(selected.capabilities)
    caps["execution.binding"] = cast(CapabilitySelection, caps["execution.binding"]).model_copy(update={"config": {
        **cast(CapabilitySelection, caps["execution.binding"]).config, "workspace_alias": alias,
    }})
    caps["tool.result-processor"] = CapabilitySelection(
        plugin="sage.tool.result-processor.file", config={"max_inline_characters": 2048},
    )
    app = await build(tmp_path, model, config=selected.model_copy(update={"capabilities": caps}))
    try:
        agent = await app.load_agent(package())
        result, events = await run(app, agent, "offload")
        assert result.state.value == "completed", result
        message = next(m for m in model.requests[1].messages if m.role == "tool")
        assert isinstance(message.content[0], JsonBlock)
        view = message.content[0].value
        assert len(json.dumps(view, ensure_ascii=False)) <= 2048
        assert 0 < view["end_line"] < 5000
        assert view["remaining_start_line"] == view["end_line"] + 1
        assert view["content"].count("\n") + 1 == view["end_line"]
        assert message.metadata["result_offloaded"]
        saved = list((workspace / ".sage/tool-results").glob("*.json"))
        assert len(saved) == 1
        full = json.loads(saved[0].read_text())
        assert "row data 中文" in full["content"][0]["value"]["content"]
        path = message.metadata["context_reference"]["path"]
        assert path.startswith("/workspace/" if alias and sys.platform == "linux" else str(workspace))
        committed = [e.data.item for e in events if e.type == "item.completed"
                     and e.data.item.data.kind == "tool_result"]
        assert committed[-1].data.content == message.content
    finally:
        await app.close()
