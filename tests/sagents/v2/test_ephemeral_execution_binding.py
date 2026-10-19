"""Memory sandbox execution and explicit recovery limits through the public SDK."""

import asyncio

import pytest

from sagents.v2.model import ModelToolCall
from sagents.v2.testing.plugins import ScriptedModelProvider
from tests.sagents.v2.test_standard_execution_configuration import (
    CONTEXT,
    build,
    command,
    package,
    response,
    run,
    runtime,
)


def memory_runtime(root):
    from sagents.v2.package.manifest.runtime import RuntimeConfig

    config = runtime(root).model_dump(mode="json")
    return RuntimeConfig.model_validate(
        {
            **config,
            "capabilities": {
                **config["capabilities"],
                "execution.binding": {
                    "plugin": "sage.execution.binding.ephemeral",
                    "config": {"workspace_root": "/sandbox"},
                },
            },
        }
    )


@pytest.mark.asyncio
@pytest.mark.timeout(60)
async def test_memory_binding_executes_files_without_exposing_host_paths(tmp_path):
    model = ScriptedModelProvider(
        (
            response(
                ModelToolCall(
                    tool_call_id="write",
                    name="file_write",
                    arguments={"file_path": "result.txt", "content": "memory result"},
                )
            ),
            response(
                ModelToolCall(
                    tool_call_id="read",
                    name="file_read",
                    arguments={"file_path": "result.txt"},
                )
            ),
            response(),
        )
    )
    app = await build(tmp_path, model, config=memory_runtime(tmp_path))
    try:
        agent = await app.load_agent(package())
        result, events = await run(app, agent, "memory-files")
        assert result.state.value == "completed"
        assert {"file_write", "file_read"} <= {
            event.data.tool_name
            for event in events
            if event.type == "tool.call.succeeded"
        }
        assert "memory result" in str(model.requests[-1].messages)
        facts = await app.execution_diagnostics(result.run_id, CONTEXT)
        assert facts["interpreter"] is None
        assert facts["recovery"] == "same_process"
        assert facts["capabilities"]["isolation_level"] == "none"
        assert not (tmp_path / "workspace" / "result.txt").exists()
    finally:
        await app.close()


@pytest.mark.asyncio
@pytest.mark.timeout(60)
async def test_memory_binding_reports_original_process_lost_after_restart(tmp_path):
    app = await build(
        tmp_path, ScriptedModelProvider(()), config=memory_runtime(tmp_path)
    )
    agent = await app.load_agent(package())
    pending = await app.runtime.start_run(command(agent, "memory-pending"), CONTEXT)
    accepted = await app.execution_configuration(pending.run_id, CONTEXT)
    await app.close()
    model = ScriptedModelProvider((response(),))
    reopened = await build(tmp_path, model, config=memory_runtime(tmp_path))
    try:
        await reopened.load_agent(package())
        await reopened.agent_for_run(pending.run_id, CONTEXT)
        async with asyncio.timeout(30):
            while (
                state := await reopened.runtime.get_run(pending.run_id)
            ).state.value not in {"completed", "failed"}:
                await asyncio.sleep(0.02)
        assert state.state.value == "failed"
        result = await reopened.runtime.session_store.get_run_result(pending.run_id)
        assert result.error.code == "execution.configuration_incompatible"
        assert "process-local" in result.error.message
        assert not model.requests
        assert (
            await reopened.execution_configuration(pending.run_id, CONTEXT) == accepted
        )
    finally:
        await reopened.close()
