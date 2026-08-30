"""Built-in packages expose only established decorator-backed Tool names."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from sagents.v2.agent.presets.catalog import BUILTIN_AGENT_PRESETS
from sagents.v2.package.manifest import CompositionResolver
from sagents.v2.package.presets import BuiltinPackageFactory
from sagents.v2.tool import DecoratedToolProvider, ToolCall, ToolDefinition, tool
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
        model="gpt-test",
        base_url="https://gateway.invalid/openai/v1",
        context_window=128_000,
        max_output_tokens=8_192,
    )
    resolved = CompositionResolver().resolve(manifest)
    assert resolved.entrypoint_agent == preset_id
    assert resolved.agents[preset_id].instructions
    assert manifest.credentials["model_api_key"].key == "SAGE_MODEL_API_KEY"


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


def test_no_hand_written_builtin_catalogs_or_placeholder_plugin_folders():
    tool_root = Path(__file__).parents[3] / "sagents" / "v2" / "tool"
    allowed_converters = {
        tool_root / "decorators.py",
        tool_root / "plugins" / "mcp.py",
    }
    offenders = []
    for path in tool_root.rglob("*.py"):
        if path in allowed_converters or path.name == "contracts.py":
            continue
        if "ToolDefinition(" in path.read_text(encoding="utf-8"):
            offenders.append(path.relative_to(tool_root).as_posix())
    assert offenders == []
    for removed in ("framework", "reference", "v1_compat"):
        assert not (tool_root / "plugins" / removed).exists()
    for removed_file in ("provider.py", "schema.py"):
        assert not (tool_root / "plugins" / "official" / removed_file).exists()
    assert not (tool_root / "plugins" / "sage_mcp.py").exists()


def test_official_tools_use_runtime_execution_instead_of_direct_host_io():
    official = (
        Path(__file__).parents[3] / "sagents" / "v2" / "tool" / "plugins" / "official"
    )
    forbidden = (
        "import subprocess",
        "import httpx",
        "import aiohttp",
        "from pathlib import Path",
        "create_subprocess",
        ".open(",
    )
    offenders = {
        path.name: [value for value in forbidden if value in path.read_text()]
        for path in official.glob("*.py")
        if any(value in path.read_text() for value in forbidden)
    }
    assert offenders == {}


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
    assert result.content[0].text == "hello"
