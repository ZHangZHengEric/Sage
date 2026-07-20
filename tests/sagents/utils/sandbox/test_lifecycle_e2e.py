import asyncio

import pytest

from sagents.skill.skill_manager import SkillManager
from sagents.utils.sandbox.config import SandboxConfig
from sagents.utils.sandbox.factory import SandboxProviderFactory
from sagents.utils.sandbox.interface import SandboxType


@pytest.mark.parametrize("mode", [SandboxType.PASSTHROUGH, SandboxType.LOCAL])
@pytest.mark.timeout(60)
def test_sandbox_lifecycle_syncs_skill_and_executes_python(tmp_path, mode):
    host_skills = tmp_path / "host-skills"
    skill_dir = host_skills / "e2e-skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\n"
        "name: e2e-skill\n"
        "description: End-to-end sandbox lifecycle test\n"
        "---\n"
        "Use this skill to verify sandbox initialization.\n",
        encoding="utf-8",
    )
    workspace = tmp_path / f"{mode.value}-workspace"
    workspace.mkdir()
    host_skill_manager = SkillManager([str(host_skills)], isolated=True)

    async def run_lifecycle():
        sandbox = await SandboxProviderFactory.create(
            SandboxConfig(
                sandbox_id=f"e2e-{mode.value}",
                mode=mode,
                sandbox_agent_workspace=str(workspace),
                # E2E 关注生命周期；subprocess 避免依赖主机是否安装 bwrap。
                linux_isolation_mode="subprocess",
                macos_isolation_mode="subprocess",
            )
        )
        try:
            await sandbox.prepare_code_environment()
            sandbox_skills = await sandbox.sync_skills(host_skill_manager)
            result = await sandbox.execute_python(
                "from pathlib import Path\n"
                "p = Path('lifecycle-result.txt')\n"
                "p.write_text('ready', encoding='utf-8')\n"
                "print(p.read_text(encoding='utf-8'))\n",
                workdir=sandbox.workspace_path,
            )

            assert sandbox_skills.list_skills() == ["e2e-skill"]
            assert await sandbox.file_exists(
                f"{sandbox.workspace_path}/skills/e2e-skill/SKILL.md"
            )
            assert result.success, result.error
            assert result.output.strip() == "ready"
            assert await sandbox.read_file(
                f"{sandbox.workspace_path}/lifecycle-result.txt"
            ) == "ready"
        finally:
            await sandbox.cleanup()

    asyncio.run(run_lifecycle())
