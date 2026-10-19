import pytest

from app.v2.desktop.backend.schemas import DesktopRunRequest, RunMessage
from sagents.v2.model import ModelToolCall
from sagents.v2.testing.plugins import ScriptedModelProvider
from tests.app.v2.desktop.sdk_fixture import desktop, execute, step
from tests.sagents.v2.test_standard_execution_configuration import response


@pytest.mark.asyncio
@pytest.mark.timeout(60)
@pytest.mark.parametrize("mode", ["normal", "plan"])
async def test_desktop_root_exposes_live_self_configuration_only_outside_plan(tmp_path, mode):
    def configured(request):
        assert "Use concise Chinese." in str(request.messages)
    def loaded(request):
        assert "Check actual deployed routes" in str(request.messages)
    model = ScriptedModelProvider((
        response(ModelToolCall(tool_call_id="configure", name="agent_self_configure", arguments={
            "add_skill_paths": ["downloads/review"], "system_prompt": "Use concise Chinese."})),
        step(ModelToolCall(tool_call_id="load", name="load_skill", arguments={"skill_name": "review"}), assertion=configured),
        step(assertion=loaded),
    )) if mode == "normal" else ScriptedModelProvider((response(ModelToolCall(tool_call_id="plan", name="goal_submit", arguments={"content": "Review the routes"})),))
    host, _, _ = desktop(tmp_path / "sage", model=model)
    try:
        workspace = await host.workspace_root(None, "sage")
        directory = workspace / "downloads" / "review"
        directory.mkdir(parents=True)
        (directory / "SKILL.md").write_text("# Review\nCheck actual deployed routes.")
        run, _, _ = await execute(host, request=DesktopRunRequest(agent_id="sage",
            messages=[RunMessage(role="user", text="review")], invocation_mode=mode, approval_mode="auto_approve" if mode == "normal" else "high_risk"))
        names = {tool.name for tool in model.requests[0].tools}
        assert ("agent_self_configure" in names) == (mode == "normal")
        if mode == "normal":
            assert run.state.value == "completed"
            events = await host.session_store.read_events(run.run_id)
            assert {"agent_self_configure", "load_skill"} <= {event.data.tool_name for event in events if event.type == "tool.call.succeeded"}
        else:
            assert run.state.value == "suspended", (await host.session_store.get_run_result(run.run_id)).error
    finally:
        await host.close()
