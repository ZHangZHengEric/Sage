"""Built-in packages expose only established decorator-backed Tool names."""

from __future__ import annotations

from typing import cast

from sagents.v2.contracts.items import TextBlock
import ast
from tests.sagents.v2.model_fixture import TEST_MODELS

from pathlib import Path

import pytest
from pydantic import ValidationError

from sagents.v2.agent.presets.catalog import BUILTIN_AGENT_PRESETS
from sagents.v2.package.presets import BuiltinPackageFactory
from sagents.v2.tool import DecoratedToolProvider, ToolCall, ToolDefinition, tool
from sagents.v2.contracts.errors import SageV2Error
from sagents.v2.contracts.principals import ActorRef, PrincipalType, RequestContext


OFFICIAL_LOCAL_TOOLS = {
    "analyze_image",
    "apply_patch",
    "await_shell",
    "execute_shell_command",
    "fetch_webpages",
    "file_read",
    "file_update",
    "file_write",
    "glob",
    "grep",
    "kill_shell",
    "list_dir",
    "questionnaire_async",
    "read_lints",
    "search_memory",
    "todo_read",
    "todo_write",
    "tool_expand_tools",
    "turn_status",
}


@pytest.mark.parametrize("preset_id", sorted(BUILTIN_AGENT_PRESETS))
def test_every_builtin_preset_creates_a_complete_resolvable_manifest(preset_id):
    manifest = BuiltinPackageFactory.create(
        preset_id,
        package_id=f"sage.official.{preset_id}",




    )
    from sagents.v2.composition.agent_graph import resolve_agent_graph
    def resolve(preset, value):
        assert len(value.agents) == 1
        children = BuiltinPackageFactory.dependencies(preset, value)
        return resolve_agent_graph(value, value.runtime, {key: resolve(key, child) for key, child in children.items()}, models=TEST_MODELS)
    resolved = resolve(preset_id, manifest)
    assert resolved.entrypoint_agent == preset_id
    assert resolved.agents[preset_id].instructions
    assert "credentials" not in manifest.model_dump()
    assert "models" not in manifest.model_dump()


def test_builtin_presets_do_not_invent_tool_names():
    for preset in BUILTIN_AGENT_PRESETS.values():
        assert set(preset.tools) <= OFFICIAL_LOCAL_TOOLS
        assert all("." not in name for name in preset.tools)


def test_tool_name_contract_rejects_dot_names():
    with pytest.raises(ValidationError, match="string_pattern_mismatch"):
        ToolDefinition(
            name="agent_package.save_draft",
            description="invalid",
            input_schema={"type": "object"},
        )


def test_builtin_tool_definitions_are_owned_by_decorators_or_protocol_converters():
    tool_root = Path(__file__).parents[3] / "sagents" / "v2" / "tool"
    # Constructing a ToolDefinition by hand is allowed only where the Tools are
    # not ours to declare: these three translate a schema discovered at runtime
    # — a decorated method, an MCP server's tool list, an A2A peer's Agent Card.
    allowed_converters = {
        tool_root / "decorators.py",
        tool_root / "plugins" / "mcp.py",
        tool_root / "plugins" / "a2a.py",
    }
    offenders = []
    for path in tool_root.rglob("*.py"):
        if path in allowed_converters or path.name == "contracts.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        constructor_names = {"ToolDefinition"}
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                constructor_names.update(
                    alias.asname or alias.name
                    for alias in node.names
                    if alias.name == "ToolDefinition"
                )
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and (
                isinstance(node.func, ast.Name)
                and node.func.id in constructor_names
                or isinstance(node.func, ast.Attribute)
                and node.func.attr == "ToolDefinition"
            ):
                offenders.append(f"{path.relative_to(tool_root)}:{node.lineno}")
    assert offenders == []


def test_official_tools_use_runtime_execution_instead_of_direct_host_io():
    official = (
        Path(__file__).parents[3] / "sagents" / "v2" / "tool" / "plugins" / "official"
    )
    offenders = []
    for path in official.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            imports = (
                [alias.name for alias in node.names]
                if isinstance(node, ast.Import)
                else [node.module or ""]
                if isinstance(node, ast.ImportFrom)
                else []
            )
            forbidden_import = any(
                module.split(".")[0] in {"subprocess", "httpx", "aiohttp", "pathlib"}
                for module in imports
            )
            forbidden_import |= (
                isinstance(node, ast.ImportFrom)
                and node.module == "asyncio"
                and any(
                    alias.name.startswith("create_subprocess") for alias in node.names
                )
            )
            forbidden_call = isinstance(node, ast.Call) and (
                isinstance(node.func, ast.Attribute)
                and (
                    node.func.attr == "open"
                    or node.func.attr.startswith("create_subprocess")
                )
                or isinstance(node.func, ast.Name)
                and (
                    node.func.id == "open"
                    or node.func.id.startswith("create_subprocess")
                )
            )
            if forbidden_import or forbidden_call:
                offenders.append(f"{path.name}:{getattr(node, 'lineno')}: {ast.unparse(node)}")
    assert offenders == []


@pytest.mark.asyncio
async def test_decorated_provider_loads_and_executes_only_decorated_methods():
    class ExampleTools:
        @tool(
            name="example_echo",
            description="Echo text.",
            input_schema={
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
                "additionalProperties": False,
            },
        )
        async def echo(self, text: str):
            return text

        async def helper(self, text: str):
            raise AssertionError("undecorated helper must not be registered")

    provider = DecoratedToolProvider(ExampleTools())
    assert [value.name for value in await provider.list_tools(run_id="run_1")] == [
        "example_echo"
    ]
    result = await provider.execute(
        ToolCall(
            tool_call_id="call_1",
            tool_name="example_echo",
            arguments={"text": "hello"},
            operation_id="operation_1",
            idempotency_key="key_1",
            owner_run_id="run_1",
        ),
        RequestContext(
            actor=ActorRef(principal_id="user_1", principal_type=PrincipalType.USER)
        ),
    )
    assert cast(TextBlock, result.content[0]).text == "hello"

    with pytest.raises(SageV2Error) as conflict:
        await provider.execute(
            ToolCall(
                tool_call_id="call_2",
                tool_name="example_echo",
                arguments={"text": "different"},
                operation_id="operation_2",
                idempotency_key="key_1",
                owner_run_id="run_1",
            ),
            RequestContext(
                actor=ActorRef(principal_id="user_1", principal_type=PrincipalType.USER)
            ),
        )
    assert conflict.value.info.code == "tool.idempotency_conflict"
