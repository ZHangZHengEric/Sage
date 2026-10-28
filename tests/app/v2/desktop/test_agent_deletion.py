from pathlib import Path
import hashlib

import pytest

from app.v2.desktop.backend.schemas import AgentCreate, DesktopRunRequest, RunMessage
from sagents.v2.contracts.errors import SageV2Error
from tests.app.v2.desktop.sdk_fixture import desktop, execute


@pytest.mark.asyncio
async def test_delete_agent_cleans_optimization_but_preserves_read_only_session(tmp_path: Path):
    service, _, _ = desktop(tmp_path)
    user = "user_1"
    try:
        agent = await service.create_agent(AgentCreate(name="Removed"), user)
        agent_id = agent["id"]
        run, command, _ = await execute(service, agent_id=agent_id)
        context = service._context(user)
        before = await service.session_access.get_session(run.session_id, context)
        root = service.runtime_root / "rsi" / "removed-experiment"
        root.mkdir(parents=True)
        (root / "result.json").write_text("{}")
        workspace = root / "workspace"
        workspace.mkdir()
        project = await service.add_project("RSI · removed", str(workspace), source="rsi")
        for kind in ("run", "version", "dataset", "scorer", "user_simulator", "evaluation_plan"):
            value = {"id": "removed-experiment" if kind == "run" else f"removed-{kind}", "status": "completed"}
            if kind == "run":
                value["test_observations"] = [{"score": 1}]
                value.update(workspace_id=project.id, workspace_path=str(workspace))
            service.rsi_store.put(value, user, agent_id, kind)
        service.rsi_store.put({"id": "large-version", "config": {"payload": "x" * 2_000_000}}, user, agent_id, "version")
        before_size = service.rsi_store.path.stat().st_size
        scope = hashlib.sha256(f"{user}\0{agent_id}".encode()).hexdigest()
        artifact_directories = [service.runtime_root / category / scope for category in ("rsi-scorers", "rsi-user-simulators")]
        for directory in artifact_directories:
            directory.mkdir(parents=True)
            (directory / "frozen.py").write_text("source")
        service.rsi_store.put({"id": "other-version"}, user, "sage", "version")
        await service.delete_agent(agent_id, user)
        assert await service.catalog.get_agent(agent_id, user) is None
        with service.rsi_store.connect() as db:
            assert db.execute("SELECT COUNT(*) FROM records WHERE user=? AND agent=?", (user, agent_id)).fetchone()[0] == 0
            assert db.execute("SELECT COUNT(*) FROM run_test_observations WHERE user=? AND agent=?", (user, agent_id)).fetchone()[0] == 0
        assert not root.exists()
        assert project.id not in {p.id for p in (await service.get_settings()).projects}
        await service.patch_settings({"theme_mode": "dark"})
        assert all(not directory.exists() for directory in artifact_directories)
        assert service.rsi_store.path.stat().st_size < before_size
        assert service.rsi_store.get("other-version", user, "sage", "version")
        assert await service.session_access.get_session(run.session_id, context) == before
        assert await service.session_access.get_start_command(run.run_id, context) == command
        for requested_agent in (agent_id, "sage"):
            request = DesktopRunRequest(agent_id=requested_agent, session_id=run.session_id,
                messages=[RunMessage(role="user", text="Continue")])
            with pytest.raises(SageV2Error) as rejected:
                _ = [frame async for frame in service.run_events(request, user)]
            assert rejected.value.info.code == "desktop.session_agent_deleted"
        assert await service.session_access.get_session(run.session_id, context) == before
    finally:
        await service.close()
