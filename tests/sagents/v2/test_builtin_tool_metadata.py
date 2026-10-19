"""Public settings metadata must agree with execution providers, without Run resources."""

import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest
from jsonschema import Draft202012Validator

from sagents.v2.agent.multi_agent.contracts import AgentMode
from sagents.v2.tool import builtin_tool_definitions
from sagents.v2.tool.plugins.delegation import MultiAgentToolPlugin
from sagents.v2.tool.plugins.official import official_tool_definitions
from sagents.v2.tool.plugins.skill import SkillToolPlugin


@pytest.mark.parametrize(
    "mode,extra",
    [
        ("simple", set()),
        ("flow", set()),
        ("team", {"sys_team_delegate_task"}),
        ("fibre", {"sys_spawn_agent", "sys_delegate_task"}),
        ("all", {"sys_team_delegate_task", "sys_spawn_agent", "sys_delegate_task"}),
    ],
)
def test_public_builtin_inventory_by_mode_matches_runtime_providers(mode, extra):
    definitions = builtin_tool_definitions(agent_mode=mode)
    expected = {value.name: value for value in official_tool_definitions()}
    expected.update(
        {value.name: value for value in SkillToolPlugin(SimpleNamespace()).definitions}
    )
    for runtime_mode in (AgentMode.TEAM, AgentMode.FIBRE):
        if mode in {runtime_mode.value, "all"}:
            plugin = MultiAgentToolPlugin(
                coordinator=SimpleNamespace(mode=runtime_mode), runtime=None
            )
            expected.update({value.name: value for value in plugin.definitions})
    assert definitions == tuple(expected[name] for name in sorted(expected))
    base = {value.name for value in official_tool_definitions()} | {"load_skill"}
    assert {value.name for value in definitions} == base | extra
    for value in definitions:
        assert value.description.strip()
        assert value.input_schema["type"] == "object"
        assert isinstance(value.input_schema["properties"], dict)
        Draft202012Validator.check_schema(value.input_schema)
    if mode != "all":
        assert definitions == builtin_tool_definitions(agent_mode=AgentMode(mode))


@pytest.mark.parametrize("mode", [None, "single", "TEAM", "unknown", "", 1, []])
def test_unknown_modes_fail_without_silently_showing_another_catalog(mode):
    with pytest.raises(ValueError, match="agent_mode"):
        builtin_tool_definitions(agent_mode=mode)


def test_metadata_snapshots_cannot_mutate_runtime_or_later_queries():
    originals = {value.name: value for value in builtin_tool_definitions()}
    query = {value.name: value for value in builtin_tool_definitions()}
    query["sys_team_delegate_task"].input_schema["properties"]["tasks"]["items"][
        "required"
    ].append("malicious")
    query["load_skill"].input_schema.clear()
    query["file_write"].input_schema.clear()
    assert {value.name: value for value in builtin_tool_definitions()} == originals
    assert {value.name: value for value in official_tool_definitions()}[
        "file_write"
    ] == originals["file_write"]
    runtime_team = MultiAgentToolPlugin(
        coordinator=SimpleNamespace(mode=AgentMode.TEAM), runtime=None
    )
    assert runtime_team.definitions == (originals["sys_team_delegate_task"],)
    assert SkillToolPlugin(SimpleNamespace()).definitions == (originals["load_skill"],)


def test_localized_settings_metadata_keeps_names_and_schema_contract():
    originals = {value.name: value for value in builtin_tool_definitions()}
    localized = {value.name: value for value in builtin_tool_definitions(language="zh")}
    assert localized.keys() == originals.keys()
    assert localized["file_read"].description != originals["file_read"].description
    for name in localized:
        assert localized[name].input_schema.get("required") == originals[
            name
        ].input_schema.get("required")
        assert (
            localized[name].input_schema["properties"].keys()
            == originals[name].input_schema["properties"].keys()
        )
    localized["load_skill"].input_schema.clear()
    assert {value.name: value for value in builtin_tool_definitions()} == originals


def test_import_and_query_without_app_model_sandbox_network_or_filesystem_writes(
    tmp_path,
):
    script = r"""
import os, sys, json

def audit(event, args):
    if event in {"subprocess.Popen", "os.posix_spawn", "os.fork", "os.mkdir"} or event.startswith("socket."):
        raise AssertionError("metadata allocated a resource: " + event)
    if event == "open" and args[2] & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND):
        raise AssertionError("metadata wrote a file: " + str(args[0]))
sys.addaudithook(audit)
from sagents.v2.tool import builtin_tool_definitions
print(json.dumps({mode: [value.name for value in builtin_tool_definitions(agent_mode=mode)]
                  for mode in ("simple", "team", "fibre", "flow", "all")}))
"""
    root = Path(__file__).resolve().parents[3]
    result = subprocess.run(
        [sys.executable, "-B", "-c", script],
        cwd=tmp_path,
        env={**os.environ, "PYTHONPATH": str(root)},
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    catalogs = json.loads(result.stdout)
    assert "sys_team_delegate_task" in catalogs["team"]
    assert "sys_spawn_agent" not in catalogs["team"]
    assert set(catalogs["all"]) == set(catalogs["simple"]) | set(
        catalogs["team"]
    ) | set(catalogs["fibre"])
    assert not list(tmp_path.iterdir())


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["simple", "team", "fibre"])
async def test_metadata_query_does_not_grant_tools_in_standard_runs(tmp_path, mode):
    from tests.sagents.v2.test_builder_nested_teams import (
        Models,
        open_app,
        package,
        run,
    )

    models = Models({"root": ()})
    app, bindings, _ = await open_app(tmp_path, models)
    manifest = package("root", ("maker",) if mode == "team" else ())
    definition = manifest.agents["assistant"].model_copy(
        update={
            "mode": mode,
            "tools": ("file_read", "load_skill"),
        }
    )
    manifest = manifest.model_copy(update={"agents": {"assistant": definition}})
    try:
        children = (
            {"maker": await app.load_agent(package("maker"))} if mode == "team" else {}
        )
        agent = await app.load_agent(manifest, subagents=children)
        before = app.runtime_configuration
        inventory = {
            value.name: value
            for value in builtin_tool_definitions(agent_mode=mode, language="en")
        }
        result, _ = await run(app, agent)
        assert result.state.value == "completed"
        assert app.runtime_configuration == before
        request = models.seen[-1][1]
        actual = {value.name: value for value in request.tools}
        expected = {"file_read", "load_skill"}
        if mode == "team":
            expected.add("sys_team_delegate_task")
        elif mode == "fibre":
            expected.update({"sys_spawn_agent", "sys_delegate_task"})
        assert actual.keys() == expected
        assert "file_write" in inventory and "file_write" not in actual
        for name, tool in actual.items():
            assert tool.input_schema == inventory[name].input_schema
    finally:
        await app.close()
        await bindings.close()
