"""V2-native official Tool plugin conformance and execution tests."""

from __future__ import annotations

from pathlib import Path
import hashlib

import pytest

from sagents.v2.contracts.principals import ActorRef, PrincipalType, RequestContext
from sagents.v2.runtime.extensions import ExtensionScope, ExtensionScopeContext
from sagents.v2.runtime.execution.sandbox import (
    FileOperation,
    FileSystemPolicy,
    LocalWorkspaceSandboxProvider,
    NetworkPolicy,
    ProcessPolicy,
    ResolvedSandboxSpec,
    SandboxGrantIssuer,
)
from sagents.v2.tool import ToolCall, decorated_tool_definition, tool
from sagents.v2.tool.plugins.official import (
    OfficialToolPlugin,
    OfficialToolRuntime,
    official_tool_definitions,
)


EXPECTED_LOCAL_TOOLS = {
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
    "questionnaire",
    "questionnaire_async",
    "read_lints",
    "search_memory",
    "todo_read",
    "todo_write",
    "tool_expand_tools",
    "turn_status",
}

CONTEXT = RequestContext(
    actor=ActorRef(principal_id="user_1", principal_type=PrincipalType.USER)
)


async def plugin_for(root: Path) -> OfficialToolPlugin:
    issuer = SandboxGrantIssuer()
    provider = LocalWorkspaceSandboxProvider(issuer.verification_key)
    digest = hashlib.sha256(str(root).encode()).hexdigest()
    handle = await provider.provision(
        ResolvedSandboxSpec(
            spec_hash=f"sha256:{digest}",
            architecture="native",
            filesystem=FileSystemPolicy(
                allowed_operations=frozenset(FileOperation),
            ),
            process=ProcessPolicy(
                enabled=True,
                allowed_executables=("bash",),
                max_wall_time_seconds=10,
            ),
            network=NetworkPolicy(),
            policy_hash=f"sha256:{digest}",
            metadata={"host_workspace": str(root)},
        ),
        CONTEXT,
        run_id="run_1",
    )
    return OfficialToolPlugin(
        ExtensionScopeContext(
            scope=ExtensionScope.AGENT,
            scope_id="test-official-tools",
            config={"runtime": OfficialToolRuntime(handle, issuer)},
        )
    )


def call(name: str, arguments: dict, *, index: int = 1) -> ToolCall:
    return ToolCall(
        tool_call_id=f"call_{index}",
        tool_name=name,
        arguments=arguments,
        operation_id=f"operation_{index}",
        idempotency_key=f"key_{index}",
        owner_run_id="run_1",
    )


def test_official_catalog_contains_exact_v2_native_names(tmp_path: Path):
    definitions = official_tool_definitions()

    assert {value.name for value in definitions} == EXPECTED_LOCAL_TOOLS
    assert all("." not in value.name for value in definitions)
    assert OfficialToolPlugin.descriptor.capabilities["v2_native"] is True


@pytest.mark.asyncio
async def test_file_tools_execute_real_workspace_operations(tmp_path: Path):
    plugin = await plugin_for(tmp_path)

    written = await plugin.executor.execute(
        call(
            "file_write",
            {"file_path": "notes/example.txt", "content": "alpha\nbeta\n"},
        ),
        CONTEXT,
    )
    assert written.content[0].value["status"] == "success"
    assert (tmp_path / "notes" / "example.txt").read_text() == "alpha\nbeta\n"

    await plugin.executor.execute(
        call(
            "file_update",
            {
                "file_path": "notes/example.txt",
                "operations": [
                    {
                        "update_mode": "search_replace",
                        "search_pattern": "beta",
                        "replacement": "gamma",
                    }
                ],
            },
            index=2,
        ),
        CONTEXT,
    )
    read = await plugin.executor.execute(
        call("file_read", {"file_path": "notes/example.txt"}, index=3), CONTEXT
    )
    assert "gamma" in read.content[0].value["content"]

    searched = await plugin.executor.execute(
        call("grep", {"pattern": "gamma", "path": "notes"}, index=4), CONTEXT
    )
    assert searched.content[0].value["matches"][0]["line"] == 2


@pytest.mark.asyncio
async def test_apply_patch_is_atomic_and_workspace_scoped(tmp_path: Path):
    plugin = await plugin_for(tmp_path)
    (tmp_path / "old.txt").write_text("one\ntwo\n")

    result = await plugin.executor.execute(
        call(
            "apply_patch",
            {
                "patch": """*** Begin Patch
*** Update File: old.txt
@@
 one
-two
+three
*** Add File: new.txt
+created
*** End Patch"""
            },
        ),
        CONTEXT,
    )

    assert result.content[0].value["files_changed"] == 2
    assert (tmp_path / "old.txt").read_text() == "one\nthree\n"
    assert (tmp_path / "new.txt").read_text() == "created\n"


@pytest.mark.asyncio
async def test_shell_and_todo_tools_use_v2_runtime_state(tmp_path: Path):
    plugin = await plugin_for(tmp_path)
    shell = await plugin.executor.execute(
        call(
            "execute_shell_command",
            {"command": "printf shell-ok", "block_until_ms": 5000},
        ),
        CONTEXT,
    )
    assert shell.content[0].value["stdout"] == "shell-ok"

    await plugin.executor.execute(
        call(
            "todo_write",
            {
                "session_id": "session_1",
                "tasks": [{"id": "t1", "content": "First"}],
            },
            index=2,
        ),
        CONTEXT,
    )
    await plugin.executor.execute(
        call(
            "todo_write",
            {
                "session_id": "session_1",
                "tasks": [{"id": "t1", "status": "completed"}],
            },
            index=3,
        ),
        CONTEXT,
    )
    todos = await plugin.executor.execute(
        call("todo_read", {"session_id": "session_1"}, index=4), CONTEXT
    )
    assert todos.content[0].value["tasks"] == [
        {"id": "t1", "content": "First", "status": "completed"}
    ]


def test_v2_tool_decorator_infers_arguments_and_hides_runtime_injection():
    class ExampleTools:
        @tool(description="Echo text")
        async def echo(self, text: str, count: int = 1, invocation=None):
            return text * count

    definition = decorated_tool_definition(ExampleTools().echo)

    assert definition is not None
    assert definition.input_schema == {
        "type": "object",
        "properties": {
            "text": {"type": "string"},
            "count": {"type": "integer", "default": 1},
        },
        "required": ["text"],
        "additionalProperties": False,
    }
