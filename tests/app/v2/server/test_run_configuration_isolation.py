"""Tenant identity is admitted per Run without multiplying Agent revisions."""
from fastapi.testclient import TestClient
from app.v2.server.main import create_app
from tests.app.v2.server.test_external_chat import make_host, setup_agent, send, result


def test_external_tenants_share_revision_and_keep_separate_frozen_workspaces(tmp_path):
    host = make_host(tmp_path, steps=8)
    with TestClient(create_app(host)) as client:
        setup_agent(client)
        agent_id = client.headers["SAGE-AGENT-ID"]
        baseline = host.application.runtime_configuration
        hashes = []
        for tenant in ("tenant-one", "tenant-two", "tenant-three"):
            response = send(client, session=tenant, user=tenant)
            assert response.status_code == 200, response.text
            assert result(client, session=tenant, user=tenant).json()["data"]["state"] == "completed"
            async def snapshot():
                runs = await host.application.runtime.session_store.list_session_runs(tenant)
                command = await host.application.runtime.session_store.get_start_command(runs[0].run_id)
                return runs[0].resolved_spec_hash, command.config.execution_snapshot
            revision, execution = client.portal.call(snapshot)
            hashes.append(revision)
            assert execution.workspace_root == str(tmp_path / "tenants" / tenant / agent_id / "workspace")
            assert tenant not in str(next(iter(host.application.loaded_agents))._resolved.runtime.model_dump())
        assert len(set(hashes)) == 1
        assert host.application.runtime_configuration == baseline
        retained = [item for item in host.application._loaded_agents.revisions.values() if item.id == agent_id]
        assert len(retained) == 1
