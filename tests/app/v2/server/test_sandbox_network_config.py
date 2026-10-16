from dataclasses import replace
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.v2.server.config.settings import ServerSettings
from app.v2.server.packages.builder import PackageBindings
from app.v2.server.runtime.official import workspace_sandbox_spec
from sagents.v2.package.manifest.agents import AgentDefinition
from sagents.v2.runtime.execution import ExecutionBindingRequest
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
@pytest.mark.parametrize("parent", [None, "parent-run"])
async def test_package_network_reaches_actual_sandbox_spec(tmp_path, ceiling, network, parent):
    specs = []
    context = SimpleNamespace(actor=SimpleNamespace(principal_id="user", tenant_id="user"))

    class Provider:
        async def provision(self, spec, context, *, run_id):
            specs.append(spec)
            return SimpleNamespace(ref=SimpleNamespace(owner_run_id=run_id, tenant_id="user"))

    bindings = PackageBindings(
        SimpleNamespace(workspace_dir=lambda *args, **kwargs: tmp_path),
        SimpleNamespace(sandbox_provider=Provider(), sandbox_grant_issuer=object()),
        "user", agents={"worker": agent(network), "parent": agent("unrestricted")},
        settings=make_settings(tmp_path, sandbox_network_mode=ceiling),
    )
    request = ExecutionBindingRequest(
        run_id="run", agent_id="worker", context=context, parent_run_id=parent,
        workspace_policy="private_child" if parent else "shared_parent",
    )
    binding = await bindings.acquire(request)
    binding.validate_for(request)
    expected = NetworkMode.UNRESTRICTED if network == ceiling == "unrestricted" else NetworkMode.NONE
    assert specs[-1].network == NetworkPolicy(
        mode=expected, deny_private_networks=expected != NetworkMode.UNRESTRICTED,
    )
    assert specs[-1].filesystem.allowed_roots == ("/workspace",)
    # A resumed Run rechecks the current host ceiling before provisioning.
    bindings.settings = make_settings(tmp_path, sandbox_network_mode="none")
    await bindings.acquire(request)
    assert specs[-1].network.mode == NetworkMode.NONE


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
    provider = service.execution.sandbox_provider
    provision = provider.provision

    async def capture(spec, context, *, run_id):
        specs.append(spec)
        return await provision(spec, context, run_id=run_id)

    monkeypatch.setattr(provider, "provision", capture)
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
    provider = service.execution.sandbox_provider
    provision = provider.provision

    async def capture(spec, context, *, run_id):
        handle = await provision(spec, context, run_id=run_id)
        networks[run_id] = spec.network.mode
        return handle

    monkeypatch.setattr(provider, "provision", capture)
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
    assert state["run"]["state"] == "completed", state
    assert networks[state["run"]["run_id"]] == NetworkMode.UNRESTRICTED
    assert NetworkMode.NONE in networks.values()
