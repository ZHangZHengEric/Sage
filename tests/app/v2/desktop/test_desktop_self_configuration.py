import pytest

from app.v2.desktop.backend.service import DesktopV2Service
from app.v2.desktop.backend.schemas import ModelProviderPatch
from sagents.v2.contracts.commands import StartRun, InputItem
from sagents.v2.contracts.items import TextBlock
from sagents.v2.tool.contracts import ToolCall


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["normal", "plan"])
async def test_desktop_root_exposes_live_self_configuration_only_outside_plan(
    tmp_path, mode
):
    host = DesktopV2Service(tmp_path / "sage")
    sandbox = None
    try:
        await host.list_agents("user_1")
        await host.patch_model_provider(
            "model_main", ModelProviderPatch(api_keys=["test-key"]), "user_1"
        )
        agent = await host._agent("sage", "user_1")
        provider = await host._provider(agent, "user_1")
        workspace = await host.workspace_root(None, "sage")
        _, loop, sandbox = await host._build_loop(
            agent=agent,
            provider=provider,
            workspace=workspace,
            preferred_skills=(),
            approval_mode="high_risk",
            invocation_mode=mode,
        )
        if mode == "plan":
            assert loop.self_configuration is None
            return
        controller = loop.self_configuration
        assert controller is not None
        from sagents.v2.tool.plugins.sandbox_mcp import SandboxMcpSessionFactory

        assert isinstance(controller.mcp_session_factory, SandboxMcpSessionFactory)
        assert controller.mcp_session_factory.sandbox is sandbox.sandbox_handle
        context = host._context("user_1")
        handle = await host.runtime.start_run(
            StartRun(
                agent_id="sage",
                input=(InputItem(role="user", content=(TextBlock(text="review"),)),),
                resolved_spec_hash="sha256:test",
                idempotency_key="self-configure-host",
            ),
            context,
        )
        await controller.prepare(handle.run_id, context)
        directory = workspace / "downloads" / "review"
        directory.mkdir(parents=True)
        (directory / "SKILL.md").write_text("# Review\nCheck actual deployed routes.")
        await loop.tool_executor.execute(
            ToolCall(
                tool_call_id="configure",
                operation_id="configure",
                idempotency_key="configure",
                tool_name="agent_self_configure",
                owner_run_id=handle.run_id,
                arguments={
                    "add_skill_paths": ["downloads/review"],
                    "system_prompt": "Use concise Chinese.",
                },
            ),
            context,
        )
        await controller.prepare(handle.run_id, context)
        assert controller.system_prompt == "Use concise Chinese."
        result = await loop.tool_executor.execute(
            ToolCall(
                tool_call_id="load",
                operation_id="load",
                idempotency_key="load",
                tool_name="load_skill",
                owner_run_id=handle.run_id,
                arguments={"skill_name": "review"},
            ),
            context,
        )
        assert result.metadata["skill_name"] == "review"
        loaded = await controller._loader.loaded(run_id=handle.run_id)
        assert "Check actual deployed routes" in loaded[0].instructions
    finally:
        if sandbox is not None:
            await sandbox.close()
        await host.close()
