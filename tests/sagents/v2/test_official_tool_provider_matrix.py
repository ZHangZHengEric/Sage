"""V2-native official Tool plugin conformance and execution tests."""

from __future__ import annotations

from pathlib import Path
import hashlib

import pytest

from sagents.v2.contracts.errors import SageV2Error
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
from sagents.v2.tool import (
    ReconcileState,
    ToolCall,
    decorated_tool_definition,
    tool,
)
from sagents.v2.tool.localization import localize_tool_definition
from sagents.v2.tool.official import OfficialToolRuntime
from sagents.v2.tool.plugins.official import (
    OfficialToolPlugin,
    official_tool_categories,
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
    "goal_complete",
    "goal_submit",
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


def test_official_catalog_exposes_display_categories():
    categories = official_tool_categories()

    assert categories["file_read"] == "files"
    assert categories["grep"] == "code_search"
    assert categories["execute_shell_command"] == "shell"
    assert categories["todo_write"] == "planning"
    assert categories["goal_submit"] == "planning"
    assert categories["goal_complete"] == "planning"
    assert categories["search_memory"] == "memory"
    assert categories["fetch_webpages"] == "web"
    assert categories["analyze_image"] == "image"
    assert categories["read_lints"] == "code_quality"
    assert categories["questionnaire_async"] == "interaction"


def test_official_catalog_localizes_tool_and_parameter_descriptions():
    definitions = {value.name: value for value in official_tool_definitions()}

    zh = localize_tool_definition(definitions["execute_shell_command"], "zh-CN")
    en = localize_tool_definition(definitions["execute_shell_command"], "en-US")
    pt = localize_tool_definition(definitions["execute_shell_command"], "pt-BR")

    assert zh.description.startswith("在沙箱中执行")
    assert zh.input_schema["properties"]["command"]["description"] == (
        "要执行的 Shell 命令"
    )
    assert en.description.startswith("Execute a shell command")
    assert en.input_schema["properties"]["command"]["description"] == (
        "Shell command to execute"
    )
    assert pt.description.startswith("Executar um comando shell")
    assert pt.input_schema["properties"]["command"]["description"] == (
        "Comando shell a executar"
    )
    assert (
        "description"
        not in definitions["execute_shell_command"].input_schema["properties"][
            "command"
        ]
    )


@pytest.mark.parametrize(
    "language", ("zh", "en", "pt", "es", "fr", "de", "ja", "ko", "ru")
)
def test_every_official_tool_has_localized_descriptions_for_visible_parameters(
    language,
):
    for definition in official_tool_definitions():
        localized = localize_tool_definition(definition, language)
        assert localized.description
        for name, schema in localized.input_schema.get("properties", {}).items():
            assert schema.get("description"), f"{language}:{definition.name}.{name}"
        if language not in {"en", "pt"}:
            assert localized.description != definition.description


def test_complex_builtin_schemas_describe_nested_contracts():
    definitions = {value.name: value for value in official_tool_definitions()}

    update = localize_tool_definition(definitions["file_update"], "zh")
    update_fields = update.input_schema["properties"]["operations"]["items"][
        "properties"
    ]
    assert set(update_fields) == {
        "update_mode",
        "search_pattern",
        "replacement",
        "replace_all",
        "start_line",
        "end_line",
    }
    assert update_fields["replacement"]["description"] == "替换内容"

    todo = localize_tool_definition(definitions["todo_write"], "en")
    task_fields = todo.input_schema["properties"]["tasks"]["items"]["properties"]
    assert task_fields["status"]["enum"] == [
        "pending",
        "in_progress",
        "completed",
    ]
    assert task_fields["conclusion"]["description"].startswith("Conclusion")

    questionnaire = localize_tool_definition(definitions["questionnaire_async"], "pt")
    question_fields = questionnaire.input_schema["properties"]["questions"]["items"][
        "properties"
    ]
    assert question_fields["type"]["enum"] == [
        "single",
        "multiple",
        "text",
    ]
    assert question_fields["options"]["description"].startswith("Opções")


@pytest.mark.asyncio
async def test_questionnaire_async_requests_user_input_without_blocking(tmp_path: Path):
    plugin = await plugin_for(tmp_path)

    result = await plugin.executor.execute(
        call(
            "questionnaire_async",
            {
                "title": "Deployment target",
                "questions": [
                    {
                        "id": "target",
                        "type": "single",
                        "title": "Where should this deploy?",
                        "options": ["staging", "production"],
                    }
                ],
            },
        ),
        CONTEXT,
    )
    signal = plugin.runtime.consume_continuation_signals("run_1")

    assert result.content[0].value["should_end"] is True
    assert signal.explicit_status == "need_user_input"
    assert signal.interaction is not None
    assert signal.interaction.interaction_type == "questionnaire"
    assert signal.interaction.allowed_decisions == ("submit", "cancel")
    assert signal.interaction.payload["questions"][0]["id"] == "target"


@pytest.mark.asyncio
async def test_turn_status_publishes_one_shot_continuation_signals(tmp_path: Path):
    plugin = await plugin_for(tmp_path)

    result = await plugin.executor.execute(
        call(
            "turn_status",
            {"status": "need_user_input", "note": "Choose a deployment target."},
        ),
        CONTEXT,
    )
    first = plugin.runtime.consume_continuation_signals("run_1")
    second = plugin.runtime.consume_continuation_signals("run_1")

    assert result.content[0].value == {
        "status": "need_user_input",
        "note": "Choose a deployment target.",
    }
    assert first.explicit_status == "need_user_input"
    assert first.explicit_status_note == "Choose a deployment target."
    assert second.explicit_status is None


@pytest.mark.asyncio
async def test_turn_status_exposes_failed_as_a_typed_terminal_state(tmp_path: Path):
    plugin = await plugin_for(tmp_path)

    result = await plugin.executor.execute(
        call("turn_status", {"status": "failed", "note": "Build failed."}),
        CONTEXT,
    )
    signal = plugin.runtime.consume_continuation_signals("run_1")

    assert result.content[0].value["status"] == "failed"
    assert signal.explicit_status == "failed"


@pytest.mark.asyncio
async def test_stopping_run_scoped_plugin_unregisters_shell_runner(tmp_path: Path):
    plugin = await plugin_for(tmp_path)
    jobs = plugin.runtime.job_runtime

    await plugin.executor.execute(
        call(
            "execute_shell_command",
            {"command": "printf done", "block_until_ms": 1000},
        ),
        CONTEXT,
    )

    assert ("run_1", "official.shell") in jobs._owner_runners
    await plugin.stop(None)
    assert ("run_1", "official.shell") not in jobs._owner_runners


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

    absolute = tmp_path / "notes" / "absolute.txt"
    await plugin.executor.execute(
        call(
            "file_write",
            {"file_path": str(absolute), "content": "host path mapped\n"},
            index=20,
        ),
        CONTEXT,
    )
    assert absolute.read_text() == "host path mapped\n"

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
async def test_file_update_validation_failure_is_known_not_applied(tmp_path: Path):
    plugin = await plugin_for(tmp_path)
    (tmp_path / "notes.txt").write_text("alpha\nbeta\n")

    with pytest.raises(SageV2Error) as caught:
        await plugin.executor.execute(
            call(
                "file_update",
                {
                    "file_path": "notes.txt",
                    "operations": [
                        {
                            "update_mode": "search_replace",
                            "search_pattern": "missing",
                            "replacement": "gamma",
                        }
                    ],
                },
            ),
            CONTEXT,
        )

    assert caught.value.info.metadata["side_effect_state"] == "not_applied"
    assert (tmp_path / "notes.txt").read_text() == "alpha\nbeta\n"


@pytest.mark.asyncio
async def test_file_update_reconciles_from_workspace_after_result_loss(
    tmp_path: Path,
):
    first = await plugin_for(tmp_path)
    (tmp_path / "notes.txt").write_text("alpha\nbeta\n")
    update = call(
        "file_update",
        {
            "file_path": "notes.txt",
            "operations": [
                {
                    "update_mode": "search_replace",
                    "search_pattern": "beta",
                    "replacement": "gamma",
                }
            ],
        },
    )
    await first.executor.execute(update, CONTEXT)

    # A fresh provider has no in-memory result cache, matching worker restart.
    recovered = await plugin_for(tmp_path)
    result = await recovered.executor.reconcile_call(update, CONTEXT)

    assert result.state == ReconcileState.SUCCEEDED
    assert result.result is not None
    assert result.result.metadata["reconciled_from_workspace"] is True


@pytest.mark.asyncio
async def test_file_update_reconciliation_reports_known_failure_when_absent(
    tmp_path: Path,
):
    plugin = await plugin_for(tmp_path)
    (tmp_path / "notes.txt").write_text("alpha\nbeta\n")
    update = call(
        "file_update",
        {
            "file_path": "notes.txt",
            "operations": [
                {
                    "update_mode": "search_replace",
                    "search_pattern": "beta",
                    "replacement": "gamma",
                }
            ],
        },
    )

    result = await plugin.executor.reconcile_call(update, CONTEXT)

    assert result.state == ReconcileState.FAILED
    assert result.result is not None
    assert result.result.error is not None
    assert result.result.error.metadata["side_effect_state"] == "not_applied"


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
