"""Run the reference host in real fresh processes with native OS isolation."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

pytestmark = pytest.mark.timeout(240)


@pytest.mark.skipif(os.environ.get("SAGE_V2_NATIVE_HOST_ACCEPTANCE") != "1", reason="explicit native sandbox acceptance")
@pytest.mark.parametrize("host_mode", ["development", "frozen"])
def test_reference_media_mcp_skill_nested_team_and_reopen(tmp_path, host_mode):
    ffmpeg = shutil.which("ffmpeg") or ("/opt/homebrew/bin/ffmpeg" if Path("/opt/homebrew/bin/ffmpeg").exists() else None)
    assert ffmpeg, "FFmpeg must be installed for media acceptance"
    repository = Path(__file__).resolve().parents[3]
    command_path = os.pathsep.join((str(Path(ffmpeg).parent), os.defpath))
    entrypoint = [sys.executable, "-m", "examples.sagents_v2_standard_host"]
    if host_mode == "frozen":
        binary = os.environ.get("SAGE_V2_FROZEN_HOST")
        if not binary:
            pytest.skip("SAGE_V2_FROZEN_HOST must identify a built executable")
        entrypoint = [binary, "--isolation-python", sys.executable]
    common = [*entrypoint, "--root", str(tmp_path),
              "--command-path", command_path]
    first = subprocess.run(common, cwd=repository, check=True, capture_output=True, text=True, timeout=180)
    run_id = json.loads(first.stdout.splitlines()[0])["run_id"]
    final = json.loads(first.stdout.splitlines()[-1])
    assert final["configuration_id"] == final["diagnostics"]["configuration_id"]
    media = tmp_path / "workspace/media.mp4"
    digest = hashlib.sha256(media.read_bytes()).hexdigest()
    assert media.stat().st_size > 0
    assert (tmp_path / "workspace/frame.png").stat().st_size > 0
    assert (tmp_path / "workspace/standard-host.txt").read_text() == "standard-sdk"
    assert tuple((tmp_path / "workspace/skills").rglob("SKILL.md"))
    reopened = subprocess.run([*common, "--recover", run_id], cwd=repository,
                              check=True, capture_output=True, text=True, timeout=180)
    restored = json.loads(reopened.stdout.splitlines()[-1])
    assert restored["configuration_id"] == final["configuration_id"]
    assert hashlib.sha256(media.read_bytes()).hexdigest() == digest


@pytest.mark.asyncio
@pytest.mark.skipif(os.environ.get("SAGE_V2_NATIVE_HOST_ACCEPTANCE") != "1", reason="explicit native sandbox acceptance")
async def test_standard_media_policy_exceeds_old_file_limit_and_enforces_new_limit(tmp_path):
    from sagents.v2.model.contracts import ModelToolCall
    from sagents.v2.testing.plugins import ScriptedModelProvider
    from tests.sagents.v2.test_standard_execution_configuration import build, package, response, run, runtime
    config = runtime(tmp_path)
    binding = config.capabilities["execution.binding"]
    config = config.model_copy(update={"capabilities": {
        **config.capabilities, "execution.binding": binding.model_copy(update={"config": {
            **binding.config, "command_path": "/opt/homebrew/bin:/bin:/usr/bin",
        }}),
    }})
    script = "import pathlib; from PIL import Image; Image.new('RGB',(16,16)).save('frame.png'); p=pathlib.Path('large.bin'); p.touch(); p.open('r+b').truncate(66*1024**2); print(p.stat().st_size)"
    denied = "import pathlib; p=pathlib.Path('denied.bin'); p.touch(); p.open('r+b').truncate(129*1024**2)"
    import shlex
    model = ScriptedModelProvider((
        response(ModelToolCall(tool_call_id="media", name="execute_shell_command", arguments={"command": "python3 -c " + shlex.quote(script)})),
        response(),
        response(ModelToolCall(tool_call_id="over-limit", name="execute_shell_command", arguments={"command": "python3 -c " + shlex.quote(denied)})),
        response(),
    ))
    app = await build(tmp_path, model, config=config)
    try:
        agent = await app.load_agent(package())
        result, _ = await run(app, agent, "valid-large")
        assert result.state.value == "completed"
        workspace = tmp_path / "workspace"
        assert (workspace / "large.bin").stat().st_size == 66 * 1024**2
        assert (workspace / "frame.png").stat().st_size > 0
        await run(app, agent, "over-limit")
        assert (workspace / "denied.bin").stat().st_size <= 128 * 1024**2
    finally:
        await app.close()


@pytest.mark.asyncio
@pytest.mark.skipif(os.environ.get("SAGE_V2_NATIVE_HOST_ACCEPTANCE") != "1", reason="explicit native sandbox acceptance")
async def test_standard_parallel_children_share_skill_materialization_and_keep_parent_lease(tmp_path):
    from examples.sagents_v2_standard_host.host import package
    from sagents.v2.model.contracts import ModelToolCall
    from sagents.v2.package.manifest.runtime import CapabilitySelection
    from sagents.v2.testing.plugins import ScriptedModelProvider
    from tests.sagents.v2.test_standard_execution_configuration import CONTEXT, build, response, run, runtime
    skill = tmp_path / "source-skills/media/SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("---\nname: media\ndescription: Test shared materialization.\n---\nUse the shared media skill.\n")
    config = runtime(tmp_path)
    config = config.model_copy(update={"capabilities": {
        **config.capabilities, "skill.catalog": CapabilitySelection(plugin="sage.skill.filesystem", config={"roots": [str(skill.parent.parent)]}),
    }})
    model = ScriptedModelProvider((
        response(ModelToolCall(tool_call_id="parallel", name="sys_team_delegate_task", arguments={"tasks": [
            {"agent_id": "left", "content": "Use the preloaded skill."},
            {"agent_id": "right", "content": "Use the preloaded skill."},
        ]})), response(), response(), response(),
    ))
    app = await build(tmp_path, model, config=config)
    try:
        left = await app.load_agent(package("left"))
        right = await app.load_agent(package("right"))
        team = await app.load_agent(package("parallel", team=True, children=("left", "right")), subagents={"left": left, "right": right})
        result, _ = await run(app, team, "parallel-skills")
        assert result.state.value == "completed"
        access = app.service("session.access")
        sessions = await access.list_descendant_sessions(result.session_id, CONTEXT)
        assert len(sessions) == 2
        root_facts = await app.execution_diagnostics(result.run_id, CONTEXT)
        for session in sessions:
            child, = await access.list_session_runs(session.session_id, CONTEXT)
            assert child.state.value == "completed"
            facts = await app.execution_diagnostics(child.run_id, CONTEXT)
            assert facts["sandbox"]["sandbox_id"] == root_facts["sandbox"]["sandbox_id"]
            assert facts["sandbox"]["owner_run_id"] == child.run_id
        copies = tuple((tmp_path / "workspace/skills").rglob("SKILL.md"))
        assert len(copies) == 1
        assert copies[0].read_bytes() == skill.read_bytes()
    finally:
        await app.close()
