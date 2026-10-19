from dataclasses import replace

import pytest
from pydantic import ValidationError

from app.v2.server.config.settings import ServerSettings
from app.v2.server.runtime.official import workspace_sandbox_spec
from sagents.v2.package.manifest.agents import AgentDefinition
from sagents.v2.runtime.execution.sandbox import NetworkMode, NetworkPolicy
from tests.app.v2.server.conftest import make_settings, register_and_login
from tests.app.v2.server.test_packages import settled


def agent(network=None):
    data = {"name": "Worker", "instructions": {"inline": "Help"}}
    if network is not None:
        data["sandbox"] = {"network": network}
    return AgentDefinition.model_validate(data)


@pytest.mark.parametrize("network", [None, "none", "unrestricted"])
def test_package_network_schema_roundtrip(network):
    definition = agent(network)
    assert definition.sandbox.network == (network or "none")
    assert AgentDefinition.model_validate_json(definition.model_dump_json()) == definition
    schema = AgentDefinition.model_json_schema()
    assert schema["$defs"]["AgentSandboxConfig"]["properties"]["network"]["enum"] == [
        "none", "unrestricted",
    ]


@pytest.mark.parametrize("network", ["allowlist", "proxy", "invalid", "", True, None, {}])
def test_package_rejects_invalid_network(network):
    with pytest.raises(ValidationError):
        AgentDefinition.model_validate({
            "name": "Worker", "instructions": {"inline": "Help"},
            "sandbox": {"network": network},
        })


def test_package_rejects_unknown_sandbox_options():
    with pytest.raises(ValidationError):
        AgentDefinition.model_validate({
            "name": "Worker", "instructions": {"inline": "Help"},
            "sandbox": {"network": "unrestricted", "allowed_hosts": ["example.com"]},
        })


@pytest.mark.parametrize("ceiling", ["none", "unrestricted"])
@pytest.mark.parametrize("network", [None, "none", "unrestricted"])
async def test_standard_network_policy_is_frozen_for_accepted_run(tmp_path, ceiling, network):
    from tests.sagents.v2.test_standard_execution_configuration import (
        build, package, runtime, run, response, CONTEXT,
    )
    from sagents.v2.testing.plugins import ScriptedModelProvider
    expected = "unrestricted" if network == ceiling == "unrestricted" else "none"
    config = runtime(tmp_path)
    binding = config.capabilities["execution.binding"]
    parameters = {**binding.config, "policy": {**binding.config["policy"],
        "network": {"mode": expected, "deny_private_networks": expected != "unrestricted"}}}
    config = config.model_copy(update={"capabilities": {**config.capabilities,
        "execution.binding": binding.model_copy(update={"config": parameters})}})
    app = await build(tmp_path, ScriptedModelProvider((response(),)), config=config)
    try:
        loaded = await app.load_agent(package())
        result, _ = await run(app, loaded, "network")
        assert result.state.value == "completed"
        frozen = await app.execution_configuration(result.run_id, CONTEXT)
        assert frozen.policy["network"]["mode"] == expected
        changed = binding.model_copy(update={"config": {**parameters, "policy": {
            **parameters["policy"], "network": {"mode": "none", "deny_private_networks": True}}}})
        await app.update_runtime(config.model_copy(update={"capabilities": {
            **config.capabilities, "execution.binding": changed}}))
        assert await app.execution_configuration(result.run_id, CONTEXT) == frozen
    finally:
        await app.close()


def test_network_policy_changes_sandbox_fingerprint(tmp_path):
    denied = workspace_sandbox_spec(tmp_path)
    allowed = workspace_sandbox_spec(tmp_path, network=NetworkPolicy(
        mode=NetworkMode.UNRESTRICTED, deny_private_networks=False,
    ))
    assert denied.network.mode == NetworkMode.NONE
    assert denied.spec_hash != allowed.spec_hash
    assert denied.policy_hash != allowed.policy_hash


def test_server_network_ceiling_has_no_environment_binding(tmp_path, monkeypatch):
    monkeypatch.setenv("SAGE_SERVER_MYSQL_URL", "mysql://unused/unused")
    monkeypatch.setenv("SAGE_SERVER_SANDBOX_NETWORK_MODE", "invalid")
    assert ServerSettings.from_env(data_root=tmp_path).sandbox_network_mode == "unrestricted"
    with pytest.raises(ValueError, match="sandbox_network_mode"):
        make_settings(tmp_path, sandbox_network_mode="invalid")


@pytest.mark.parametrize("ceiling", ["none", "unrestricted"])
@pytest.mark.parametrize("network", ["none", "unrestricted"])
def test_saved_package_network_applies_when_server_executes(client, service, monkeypatch, network, ceiling):
    factory = service.agent_management.package_builder_factory
    factory.settings = replace(factory.settings, sandbox_network_mode=ceiling)
    specs = []
    from sagents.v2.runtime.execution.sandbox import LocalWorkspaceSandboxProvider
    provision = LocalWorkspaceSandboxProvider.provision

    async def capture(provider, spec, context, *, run_id):
        specs.append(spec)
        return await provision(provider, spec, context, run_id=run_id)

    monkeypatch.setattr(LocalWorkspaceSandboxProvider, "provision", capture)
    headers = {"Authorization": f"Bearer {register_and_login(client)}"}
    bundle = client.get("/api/agent-packages/template", headers=headers).json()["data"]
    bundle["manifest"]["agents"]["assistant"]["sandbox"] = {"network": network}
    response = client.post("/api/agent-packages", headers=headers, json=bundle)
    assert response.status_code == 200, response.text
    ref = response.json()["data"]["ref"]
    loaded = client.get(f"/api/agent-packages/{ref}", headers=headers).json()["data"]
    assert loaded["manifest"]["agents"]["assistant"]["sandbox"] == {"network": network}
    specs.clear()
    response = client.post("/api/agent-packages/runs", headers=headers, json={
        "ref": ref, "agent_id": "assistant", "operation": "network", "content": "hello",
    })
    assert response.status_code == 200, response.text
    assert settled(client, headers, "network")["run"]["state"] == "completed"
    assert specs
    expected = NetworkMode.UNRESTRICTED if network == ceiling == "unrestricted" else NetworkMode.NONE
    assert all(spec.network.mode == expected for spec in specs)


def test_package_api_rejects_invalid_network_before_save(client):
    headers = {"Authorization": f"Bearer {register_and_login(client)}"}
    bundle = client.get("/api/agent-packages/template", headers=headers).json()["data"]
    bundle["manifest"]["agents"]["assistant"]["sandbox"] = {"network": "allowlist"}
    response = client.post("/api/agent-packages", headers=headers, json=bundle)
    assert response.status_code == 422, response.text
    assert client.get("/api/agent-packages", headers=headers).json()["data"] == []


def test_flow_member_uses_own_network_policy(client, service, monkeypatch):
    from copy import deepcopy

    networks = {}
    from sagents.v2.runtime.execution.sandbox import LocalWorkspaceSandboxProvider
    provision = LocalWorkspaceSandboxProvider.provision

    async def capture(provider, spec, context, *, run_id):
        handle = await provision(provider, spec, context, run_id=run_id)
        networks[run_id] = spec.network.mode
        return handle

    monkeypatch.setattr(LocalWorkspaceSandboxProvider, "provision", capture)
    headers = {"Authorization": f"Bearer {register_and_login(client)}"}
    bundle = client.get("/api/agent-packages/template", headers=headers).json()["data"]
    agents = bundle["manifest"]["agents"]
    agents["worker"] = deepcopy(agents["assistant"])
    agents["assistant"]["sandbox"] = {"network": "unrestricted"}
    agents["worker"]["sandbox"] = {"network": "none"}
    agents["assistant"]["entrypoint"] = {"type": "flow", "flow": "main"}
    bundle["manifest"]["flows"] = {"main": {
        "version": "1", "start": "work",
        "nodes": [{"id": "work", "type": "agent", "agent": "worker"}, {"id": "end", "type": "end"}],
        "edges": [{"from": "work", "to": "end"}],
    }}
    from copy import deepcopy
    child = deepcopy(bundle)
    child["manifest"]["metadata"]["id"] += ".worker"
    child["manifest"]["agents"] = {"worker": child["manifest"]["agents"]["worker"]}
    child["manifest"]["entrypoint"] = {"agent": "worker"}
    child["manifest"]["flows"] = {}
    bundle["manifest"]["agents"].pop("worker")
    bundle["dependencies"] = {"worker": child}
    response = client.post("/api/agent-packages", headers=headers, json=bundle)
    assert response.status_code == 200, response.text
    networks.clear()
    response = client.post("/api/agent-packages/runs", headers=headers, json={
        "ref": response.json()["data"]["ref"], "agent_id": "assistant",
        "operation": "flow-network", "content": "hello",
    })
    assert response.status_code == 200, response.text
    state = settled(client, headers, "flow-network")
    assert state["run"]["state"] == "completed", __import__("json").dumps(state, default=str)
    assert networks[state["run"]["run_id"]] == NetworkMode.UNRESTRICTED
    assert NetworkMode.NONE in networks.values()


@pytest.mark.parametrize("disk_mb", [1, 32768])
def test_workspace_filesystem_quota_follows_resource_configuration(tmp_path, disk_mb):
    from sagents.v2.runtime.execution.sandbox import ResourceLimits

    spec = workspace_sandbox_spec(tmp_path, resources=ResourceLimits(
        disk_mb=disk_mb, require_hard_limits=False,
    ))
    assert spec.resources.disk_mb == disk_mb
    assert spec.filesystem.max_total_bytes == disk_mb * 1024**2
