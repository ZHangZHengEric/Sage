"""V2-native official Tool plugin conformance and execution tests."""

from __future__ import annotations

from sagents.v2.runtime.execution.sandbox import ResourceLimits

from datetime import datetime, timedelta, timezone
from pathlib import Path
import asyncio
import errno
import hashlib
import json
import os

import pytest

from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo, SageV2Error
from sagents.v2.contracts.jobs import JobState
from sagents.v2.contracts.principals import ActorRef, PrincipalType, RequestContext
from sagents.v2.runtime.extensions import ExtensionScope, ExtensionScopeContext
from sagents.v2.runtime.execution.sandbox import (
    FileOperation,
    FileSystemPolicy,
    InMemorySandboxProvider,
    LifecyclePolicy,
    LocalWorkspaceSandboxProvider,
    NetworkPolicy,
    ProcessPolicy,
    ResolvedSandboxSpec,
    SandboxDurability,
    SandboxGrantIssuer,
)
from sagents.v2.runtime.execution.sandbox.contracts import FileSystemMode
from sagents.v2.tool import (
    CancelSemantics,
    ReconcileState,
    ToolCall,
    ToolCancellationState,
    decorated_tool_definition,
    tool,
)
from sagents.v2.tool.localization import localize_tool_definition
from sagents.v2.tool.decorated import ToolInvocation
from sagents.v2.tool.official import OfficialToolRuntime
from sagents.v2.tool.official.media import MediaTools
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


async def plugin_for(
    root: Path, *, filesystem: FileSystemPolicy | None = None
) -> OfficialToolPlugin:
    issuer = SandboxGrantIssuer()
    provider = LocalWorkspaceSandboxProvider(issuer.verification_key)
    digest = hashlib.sha256(str(root).encode()).hexdigest()
    handle = await provider.provision(
        ResolvedSandboxSpec(
            resources=ResourceLimits(require_hard_limits=False),
            spec_hash=f"sha256:{digest}",
            architecture="native",
            filesystem=filesystem
            or FileSystemPolicy(
                allowed_operations=frozenset(FileOperation),
            ),
            process=ProcessPolicy(
                enabled=filesystem is None,
                allowed_executables=("bash",),
                allow_shell=True,
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


NOW = datetime(2026, 9, 3, tzinfo=timezone.utc)


async def ephemeral_plugin_for(
    filesystem: FileSystemPolicy,
    *,
    issuer_clock=None,
    provider_clock=None,
) -> OfficialToolPlugin:
    """Same official plugin on the in-memory provider, which raises typed errors."""

    issuer = SandboxGrantIssuer(
        b"official-tool-test-key-32-bytes!!", clock=issuer_clock or (lambda: NOW)
    )
    provider = InMemorySandboxProvider(
        issuer.verification_key, clock=provider_clock or (lambda: NOW)
    )
    handle = await provider.provision(
        ResolvedSandboxSpec(
            resources=ResourceLimits(require_hard_limits=False),
            spec_hash="sha256:spec",
            architecture="portable",
            filesystem_mode=FileSystemMode.WORKSPACE,
            filesystem=filesystem,
            process=ProcessPolicy(),
            network=NetworkPolicy(),
            lifecycle=LifecyclePolicy(
                durability=SandboxDurability.SNAPSHOTABLE,
                pause_behavior="snapshot",
            ),
            policy_hash="sha256:policy",
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
async def test_questionnaire_async_returns_validated_terminal_payload(tmp_path: Path):
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

    assert result.content[0].value["status"] == "awaiting_user_input"
    assert result.content[0].value["validation_passed"] is True
    assert result.content[0].value["should_end"] is True
    assert result.content[0].value["questions"][0]["id"] == "target"
    assert signal.explicit_status is None
    assert signal.interaction is None


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


class _ImageRuntime:
    image_context_publisher = None

    def __init__(self):
        from sagents.v2.runtime.artifact import InMemoryArtifactStore
        self.artifact_store = InMemoryArtifactStore()

    async def read_bytes(self, path: str, invocation: ToolInvocation) -> bytes:
        return Path(path).read_bytes()


async def _analyze_image(image_path: str, prompt: str | None = None, *, runtime=None):
    return await MediaTools(runtime or _ImageRuntime()).analyze_image(
        image_path=image_path,
        session_id="session_1",
        prompt=prompt,
        invocation=ToolInvocation(call("analyze_image", {}), CONTEXT),
    )


@pytest.mark.asyncio
async def test_analyze_image_queues_a_user_followup_and_keeps_tool_result_small(
    tmp_path: Path,
):
    image = tmp_path / "frame.png"
    from PIL import Image

    Image.new("RGB", (2048, 1024), "red").save(image)
    runtime = _ImageRuntime()
    result = await _analyze_image(str(image), "Check the frame.", runtime=runtime)

    payload = result.content[0].value
    followup = result.metadata["followup_user_message"]
    assert payload["status"] == "success"
    assert payload["data"]["mode"] == "native_multimodal_context"
    assert payload["data"]["image_path"] == str(image)
    assert "base64" not in json.dumps(payload)
    assert followup["content"][0] == {
        "kind": "text",
        "text": "Check the frame.",
    }
    uri = followup["content"][1]["uri"]
    assert uri.startswith("sage-image:")
    assert followup["content"][1] == {
        "kind": "image",
        "uri": uri,
        "mime_type": "image/jpeg",
        "alt": str(image),
    }
    assert followup["metadata"]["hidden_from_chat"] is True
    assert "data:image" not in json.dumps(followup)

    from sagents.v2.agent.engine import AgentLoopEngine
    from sagents.v2.runtime.artifact.images import hydrate_image_blocks

    tool_message, user_message = AgentLoopEngine._ledger_messages_for_tool_result(
        result
    )
    assert tool_message.role == "tool"
    assert "followup_user_message" not in tool_message.metadata
    assert "base64" not in json.dumps(tool_message.model_dump(mode="json"))
    assert user_message.role == "user"
    assert user_message.content[1].uri == uri
    assert "data:image" not in json.dumps(user_message.model_dump(mode="json"))

    hydrated = await hydrate_image_blocks((user_message,), runtime.artifact_store)
    assert hydrated[0].content[1].uri.startswith("data:image/jpeg;base64,")
    import base64
    import io

    encoded = hydrated[0].content[1].uri.split(",", 1)[1]
    with Image.open(io.BytesIO(base64.b64decode(encoded))) as normalized:
        assert normalized.format == "JPEG"
        assert max(normalized.size) <= 1536


@pytest.mark.asyncio
async def test_analyze_image_keeps_remote_url_without_downloading():
    remote = "https://example.invalid/frame.png"
    result = await _analyze_image(remote, "Look at the remote frame.")

    payload = result.content[0].value
    followup = result.metadata["followup_user_message"]
    assert payload["data"]["image_format"] == "remote_url"
    assert payload["data"]["image_path"] == remote
    assert followup["content"][1]["uri"] == remote
    assert "base64" not in json.dumps(payload)


@pytest.mark.asyncio
@pytest.mark.parametrize("image_path", ["frame.png", "/workspace/frame.png"])
@pytest.mark.parametrize("provider", ["local", "memory"])
async def test_image_snapshot_uses_sandbox_paths_and_survives_source_changes(
    tmp_path, image_path, provider,
):
    from PIL import Image
    import io
    from sagents.v2.agent.engine import AgentLoopEngine
    from sagents.v2.context import DefaultContextAssembler
    from sagents.v2.contracts.commands import StartRun
    from sagents.v2.runtime.artifact import FilesystemArtifactStore

    root = tmp_path / "workspace"
    root.mkdir()
    plugin = (await plugin_for(root) if provider == "local" else
              await ephemeral_plugin_for(FileSystemPolicy(allowed_operations=frozenset(FileOperation))))
    plugin.runtime.artifact_store = FilesystemArtifactStore(tmp_path / "artifacts")
    original = io.BytesIO()
    Image.new("RGB", (32, 32), "red").save(original, format="PNG")
    invocation = ToolInvocation(call("analyze_image", {}), CONTEXT)
    await plugin.runtime.write_bytes("frame.png", original.getvalue(), invocation)
    result = await MediaTools(plugin.runtime).analyze_image(
        image_path, "session_1", invocation=invocation,
    )
    assert result.content[0].value["status"] == "success"
    ledger = AgentLoopEngine._ledger_messages_for_tool_result(result)
    assert "data:image" not in json.dumps(result.model_dump(mode="json"))
    assert "data:image" not in json.dumps([m.model_dump(mode="json") for m in ledger])
    command = StartRun(agent_id="agent_1", input=(), resolved_spec_hash="sha256:spec", idempotency_key="image")
    assembler = DefaultContextAssembler(artifact_store=plugin.runtime.artifact_store)
    first = await assembler.prepare_messages(command, ledger)
    assert first[-1].content[-1].uri.startswith("data:image/jpeg;base64,")
    await plugin.runtime.write_bytes("frame.png", b"overwritten", invocation)
    assert await assembler.prepare_messages(command, ledger) == first
    await plugin.runtime.delete_file("frame.png", invocation)
    await plugin.runtime.sandbox.destroy()
    restarted = DefaultContextAssembler(artifact_store=FilesystemArtifactStore(tmp_path / "artifacts"))
    assert await restarted.prepare_messages(command, ledger) == first


@pytest.mark.asyncio
async def test_image_snapshot_cannot_read_outside_sandbox(tmp_path):
    from PIL import Image
    from sagents.v2.runtime.artifact import FilesystemArtifactStore

    root = tmp_path / "workspace"
    root.mkdir()
    outside = tmp_path / "secret.png"
    Image.new("RGB", (32, 32), "red").save(outside)
    plugin = await plugin_for(root)
    plugin.runtime.artifact_store = FilesystemArtifactStore(tmp_path / "artifacts")
    result = await MediaTools(plugin.runtime).analyze_image(
        str(outside), "session_1", invocation=ToolInvocation(call("analyze_image", {}), CONTEXT),
    )
    assert result.content[0].value["data"]["reason"] == "permission_denied"
    assert "followup_user_message" not in result.metadata


@pytest.mark.asyncio
async def test_image_snapshot_requires_configured_store(tmp_path):
    from PIL import Image
    image = tmp_path / "frame.png"
    Image.new("RGB", (32, 32), "red").save(image)
    runtime = _ImageRuntime()
    runtime.artifact_store = None
    result = await _analyze_image(str(image), runtime=runtime)
    assert result.content[0].value["data"]["reason"] == "attachment_store_unavailable"
    assert "followup_user_message" not in result.metadata


@pytest.mark.asyncio
@pytest.mark.parametrize("image_format", ["TIFF", "ICO"])
async def test_image_snapshot_preserves_pillow_supported_formats(tmp_path, image_format):
    from PIL import Image
    image = tmp_path / ("frame." + image_format.lower())
    Image.new("RGB", (32, 32), "red").save(image, format=image_format)
    result = await _analyze_image(str(image))
    assert result.content[0].value["status"] == "success"


@pytest.mark.asyncio
async def test_analyze_image_reports_missing_file_instead_of_raising():
    missing = "/workspace/videos/promo/qa/frames/frame-01.png"
    result = await _analyze_image(missing, "Check the opening frame.")

    payload = result.content[0].value
    assert result.error is None
    assert "followup_user_message" not in result.metadata
    assert payload == {
        "status": "error",
        "message": f"Image file not found: {missing}",
        "data": {
            "image_path": missing,
            "reason": "not_found",
        },
    }


def test_analyze_image_followups_are_grouped_after_all_tool_results():
    from sagents.v2.agent.engine import AgentLoopEngine
    from sagents.v2.contracts.items import JsonBlock
    from sagents.v2.tool import ToolExecutionResult

    def image_result(call_id: str, uri: str) -> ToolExecutionResult:
        return ToolExecutionResult(
            tool_call_id=call_id,
            operation_id=f"operation_{call_id}",
            content=(JsonBlock(value={"status": "success"}),),
            metadata={
                "followup_user_message": {
                    "content": [
                        {"kind": "text", "text": "Inspect the frame."},
                        {"kind": "image", "uri": uri, "mime_type": "image/png"},
                    ]
                }
            },
        )

    messages = AgentLoopEngine._ledger_messages_for_tool_batch(
        (
            image_result("call_1", "/workspace/a.png"),
            image_result("call_2", "https://example.invalid/b.png"),
        )
    )
    assert [message.role for message in messages] == ["tool", "tool", "user", "user"]
    assert "base64" not in json.dumps(messages[0].model_dump(mode="json"))
    assert messages[2].content[1].uri == "/workspace/a.png"
    assert messages[3].content[1].uri == "https://example.invalid/b.png"
    assert "data:image" not in json.dumps([m.model_dump(mode="json") for m in messages])


def test_legacy_inline_followup_is_preserved_without_reopening_source():
    from sagents.v2.agent.engine import AgentLoopEngine
    from sagents.v2.contracts.items import JsonBlock
    from sagents.v2.tool import ToolExecutionResult

    result = ToolExecutionResult(
        tool_call_id="call_1",
        operation_id="operation_call_1",
        content=(JsonBlock(value={"status": "success"}),),
        metadata={
            "followup_user_message": {
                "content": [
                    {"kind": "text", "text": "Inspect the frame."},
                    {
                        "kind": "image",
                        "uri": "data:image/png;base64,aaa",
                        "mime_type": "image/png",
                    },
                ],
                "metadata": {
                    "tool_source": "analyze_image",
                    "image_path": "/workspace/frame.png",
                },
            }
        },
    )
    _tool, user_message = AgentLoopEngine._ledger_messages_for_tool_result(result)
    assert user_message.content[1].uri == "data:image/png;base64,aaa"


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
async def test_file_update_reconciliation_preserves_unknown_when_evidence_is_absent(
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

    assert result.state == ReconcileState.UNKNOWN
    assert result.result is None
    assert result.error is not None
    assert not result.error.safe_to_resume
    assert result.error.metadata["side_effect_state"] == "unknown"


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
@pytest.mark.skipif(
    os.environ.get("GITHUB_ACTIONS") == "true",
    reason="CI does not run Linux sandbox process checks",
)
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


@pytest.mark.asyncio
async def test_todos_are_isolated_by_session_and_restored_after_runtime_restart(tmp_path: Path):
    plugin = await plugin_for(tmp_path)
    legacy = tmp_path / ".sage" / "todos.json"
    legacy.parent.mkdir(parents=True)
    legacy.write_text(json.dumps([{"id": "legacy", "content": "Unowned"}]))

    for index, session in enumerate(("session_a", "session_b"), start=1):
        result = await plugin.executor.execute(
            call("todo_read", {"session_id": session}, index=index), CONTEXT
        )
        assert result.error is None
        assert result.content[0].value["tasks"] == []
        result = await plugin.executor.execute(
            call(
                "todo_write",
                {"session_id": session, "tasks": [{"id": "t1", "content": session}]},
                index=index + 10,
            ),
            CONTEXT,
        )
        assert result.error is None

    restored = await plugin_for(tmp_path)
    result = await restored.executor.execute(
        call(
            "todo_write",
            {"session_id": "session_a", "tasks": [{"id": "t1", "status": "completed"}]},
            index=30,
        ),
        CONTEXT,
    )
    assert result.error is None
    for index, session in enumerate(("session_a", "session_b"), start=40):
        result = await restored.executor.execute(
            call("todo_read", {"session_id": session}, index=index), CONTEXT
        )
        assert result.error is None
        assert result.content[0].value["tasks"] == [{
            "id": "t1",
            "content": session,
            "status": "completed" if session == "session_a" else "pending",
        }]
        assert (tmp_path / ".sage" / "todos" / f"{session}.json").is_file()
    assert json.loads(legacy.read_text()) == [{"id": "legacy", "content": "Unowned"}]


@pytest.mark.asyncio
async def test_todo_session_paths_are_encoded_and_owner_is_enforced(tmp_path: Path):
    plugin = await plugin_for(tmp_path)
    for index, session in enumerate(("../other", "..%2Fother"), start=1):
        result = await plugin.executor.execute(
            call(
                "todo_write",
                {"session_id": session, "tasks": [{"id": "t1", "content": session}]},
                index=index,
            ),
            CONTEXT,
        )
        assert result.error is None
    assert (tmp_path / ".sage" / "todos" / "..%2Fother.json").is_file()
    assert (tmp_path / ".sage" / "todos" / "..%252Fother.json").is_file()

    for index, name in enumerate(("todo_read", "todo_write"), start=10):
        for offset, session in enumerate(("", " ", "other_session")):
            arguments = {"session_id": session}
            if name == "todo_write":
                arguments["tasks"] = [{"id": "t1", "content": "Wrong session"}]
            request = call(name, arguments, index=index * 10 + offset).model_copy(
                update={"owner_session_id": "current_session"}
            )
            with pytest.raises(SageV2Error, match="session_id") as caught:
                await plugin.executor.execute(request, CONTEXT)
            assert caught.value.info.metadata["side_effect_state"] == "not_applied"
    assert len(list((tmp_path / ".sage" / "todos").iterdir())) == 2

    request = call("todo_read", {"session_id": "../other"}, index=200).model_copy(
        update={"owner_session_id": "../other"}
    )
    result = await plugin.executor.execute(request, CONTEXT)
    assert result.error is None
    assert result.content[0].value["tasks"][0]["content"] == "../other"


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


OUTSIDE_ROOTS = FileSystemPolicy(
    allowed_operations=frozenset(FileOperation),
    allowed_roots=("/workspace/src",),
)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "tool_name, arguments",
    [
        ("file_write", {"file_path": "notes/outside.txt", "content": "x\n"}),
        (
            "file_update",
            {
                "file_path": "notes/outside.txt",
                "operations": [
                    {
                        "update_mode": "search_replace",
                        "search_pattern": "a",
                        "replacement": "b",
                    }
                ],
            },
        ),
        (
            "apply_patch",
            {
                "patch": "*** Begin Patch\n*** Add File: notes/outside.txt\n+x\n"
                "*** End Patch"
            },
        ),
    ],
)
async def test_local_sandbox_denial_is_a_typed_not_applied_failure(
    tmp_path: Path, tool_name: str, arguments: dict
):
    plugin = await plugin_for(tmp_path, filesystem=OUTSIDE_ROOTS)

    with pytest.raises(SageV2Error) as caught:
        await plugin.executor.execute(call(tool_name, arguments), CONTEXT)

    info = caught.value.info
    assert info.code == "sandbox.permission_denied"
    assert info.category == ErrorCategory.POLICY_DENIED
    assert info.safe_to_resume is True
    assert info.metadata["side_effect_state"] == "not_applied"
    assert info.message == "path is outside the allowed filesystem roots"
    assert not (tmp_path / "notes").exists()


@pytest.mark.asyncio
async def test_apply_patch_denied_midway_rolls_back_before_reporting_not_applied(
    tmp_path: Path,
):
    plugin = await plugin_for(tmp_path, filesystem=OUTSIDE_ROOTS)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "old.txt").write_text("one\n")

    with pytest.raises(SageV2Error) as caught:
        await plugin.executor.execute(
            call(
                "apply_patch",
                {
                    "patch": """*** Begin Patch
*** Update File: src/old.txt
@@
-one
+two
*** Add File: docs/new.txt
+created
*** End Patch"""
                },
            ),
            CONTEXT,
        )

    assert caught.value.info.code == "sandbox.permission_denied"
    assert caught.value.info.metadata["side_effect_state"] == "not_applied"
    assert (tmp_path / "src" / "old.txt").read_text() == "one\n"
    assert not (tmp_path / "docs").exists()


@pytest.mark.asyncio
async def test_in_memory_sandbox_policy_denial_keeps_its_code_and_category():
    plugin = await ephemeral_plugin_for(
        FileSystemPolicy(
            allowed_operations=frozenset({FileOperation.READ, FileOperation.LIST})
        )
    )

    with pytest.raises(SageV2Error) as caught:
        await plugin.executor.execute(
            call("file_write", {"file_path": "notes.txt", "content": "x\n"}), CONTEXT
        )

    info = caught.value.info
    provider_error = caught.value.__cause__
    assert info.code == "sandbox.permission_denied"
    assert info.category == ErrorCategory.POLICY_DENIED
    assert info.safe_to_resume is True
    assert info.metadata["side_effect_state"] == "not_applied"
    assert isinstance(provider_error, SageV2Error)
    assert provider_error.info.code == "sandbox.permission_denied"
    assert "side_effect_state" not in provider_error.info.metadata


@pytest.mark.asyncio
async def test_in_memory_sandbox_resource_limit_is_not_applied():
    plugin = await ephemeral_plugin_for(
        FileSystemPolicy(allowed_operations=frozenset(FileOperation), max_file_bytes=4)
    )

    with pytest.raises(SageV2Error) as caught:
        await plugin.executor.execute(
            call("file_write", {"file_path": "notes.txt", "content": "too long\n"}),
            CONTEXT,
        )

    assert caught.value.info.code == "sandbox.resource_exhausted"
    assert caught.value.info.category == ErrorCategory.POLICY_DENIED
    assert caught.value.info.metadata["side_effect_state"] == "not_applied"


@pytest.mark.asyncio
async def test_in_memory_sandbox_grant_expiry_is_not_applied():
    plugin = await ephemeral_plugin_for(
        FileSystemPolicy(allowed_operations=frozenset(FileOperation)),
        provider_clock=lambda: NOW + timedelta(hours=1),
    )

    with pytest.raises(SageV2Error) as caught:
        await plugin.executor.execute(
            call("file_write", {"file_path": "notes.txt", "content": "x\n"}), CONTEXT
        )

    assert caught.value.info.code == "sandbox.grant_expired"
    assert caught.value.info.category == ErrorCategory.AUTHORIZATION
    assert caught.value.info.safe_to_resume is True
    assert caught.value.info.metadata["side_effect_state"] == "not_applied"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure",
    [
        PermissionError(errno.EACCES, "Permission denied"),
        OSError(errno.ENOSPC, "No space left on device"),
        SageV2Error(
            RuntimeErrorInfo(
                code="sandbox.network_timeout",
                category=ErrorCategory.PROVIDER_TRANSIENT,
                message="the sandbox stopped responding",
            )
        ),
    ],
    ids=["os-permission-error", "os-error", "non-denial-sandbox-error"],
)
async def test_failures_inside_the_write_keep_the_unknown_outcome_path(
    tmp_path: Path, monkeypatch, failure: BaseException
):
    """Only the sandbox's own denials are mapped; an error raised from inside
    the I/O may have left a partial write and must stay on the reconciliation path."""

    plugin = await plugin_for(tmp_path)

    async def failing_write(path, content, *, intent, grant, overwrite=True):
        del path, content, intent, grant, overwrite
        raise failure

    monkeypatch.setattr(plugin.runtime.sandbox.filesystem, "write_bytes", failing_write)

    with pytest.raises(type(failure)) as caught:
        await plugin.executor.execute(
            call("file_write", {"file_path": "notes.txt", "content": "x\n"}), CONTEXT
        )

    assert caught.value is failure
    if isinstance(failure, SageV2Error):
        assert "side_effect_state" not in failure.info.metadata


@pytest.mark.asyncio
async def test_shell_wait_is_cancelled_cooperatively_and_jobs_end_with_the_run(
    tmp_path: Path,
):
    """取消只中断对 job 的等待（暂停后还能 await_shell）；Run 终态时 release_run 才终止 job。"""

    plugin = await plugin_for(tmp_path)
    definitions = {definition.name: definition for definition in plugin.definitions}
    assert (
        definitions["execute_shell_command"].cancel_semantics
        == CancelSemantics.COOPERATIVE
    )
    assert definitions["await_shell"].cancel_semantics == CancelSemantics.COOPERATIVE
    assert (
        definitions["file_write"].cancel_semantics == CancelSemantics.NOT_STARTED_ONLY
    )

    shell = call(
        "execute_shell_command", {"command": "sleep 5", "block_until_ms": 1500}
    )
    execution = asyncio.create_task(plugin.executor.execute(shell, CONTEXT))
    job_runtime = plugin.runtime.job_runtime
    for _ in range(100):
        jobs = await job_runtime.list_run_jobs("run_1")
        if jobs and jobs[0].state == JobState.RUNNING:
            break
        await asyncio.sleep(0.01)
    else:
        pytest.fail("shell job did not start")
    job_id = jobs[0].job_id

    cancelled = await plugin.executor.cancel(shell.operation_id, CONTEXT)
    assert cancelled.state == ToolCancellationState.CANCELLED
    with pytest.raises(asyncio.CancelledError):
        await execution
    assert (await job_runtime.inspect(job_id)).state == JobState.RUNNING
    too_late = await plugin.executor.cancel(shell.operation_id, CONTEXT)
    assert too_late.state == ToolCancellationState.TOO_LATE
    unknown = await plugin.executor.cancel("operation_unknown", CONTEXT)
    assert unknown.state == ToolCancellationState.TOO_LATE

    await plugin.executor.release_run("run_1")
    assert (await job_runtime.inspect(job_id)).state == JobState.KILLED


@pytest.mark.asyncio
async def test_non_cooperative_tool_reports_cancel_as_unsupported(tmp_path: Path):
    plugin = await plugin_for(tmp_path)
    gate = asyncio.Event()

    async def blocked_write(*args, **kwargs):
        del args, kwargs
        await gate.wait()
        raise AssertionError("unreachable")

    plugin.runtime.write_text = blocked_write  # type: ignore[method-assign]
    write = call("file_write", {"file_path": "notes.txt", "content": "x"})
    execution = asyncio.create_task(plugin.executor.execute(write, CONTEXT))
    await asyncio.sleep(0.05)

    result = await plugin.executor.cancel(write.operation_id, CONTEXT)

    assert result.state == ToolCancellationState.NOT_SUPPORTED
    assert not execution.done()
    execution.cancel()
    with pytest.raises(asyncio.CancelledError):
        await execution


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "replacement, expected_state",
    [
        ("B1\nB2", ReconcileState.SUCCEEDED),
        ("", ReconcileState.UNKNOWN),
    ],
)
async def test_line_batch_reconciles_after_worker_restart(
    tmp_path, replacement, expected_state
):
    (tmp_path / "notes.txt").write_text("a\nb\nc\nd\ne\nf\n")
    update = call(
        "file_update",
        {
            "file_path": "notes.txt",
            "operations": [
                {
                    "update_mode": "line_range",
                    "start_line": 2,
                    "end_line": 2,
                    "replacement": replacement,
                },
                {
                    "update_mode": "line_range",
                    "start_line": 5,
                    "end_line": 5,
                    "replacement": "E",
                },
            ],
        },
    )
    first = await plugin_for(tmp_path)
    result = await first.executor.execute(update, CONTEXT)
    assert result.error is None
    expected = "a\n" + (replacement + "\n" if replacement else "") + "c\nd\nE\nf\n"
    assert (tmp_path / "notes.txt").read_text() == expected
    recovered = await plugin_for(tmp_path)
    result = await recovered.executor.reconcile_call(update, CONTEXT)
    assert result.state == expected_state
    if expected_state == ReconcileState.UNKNOWN:
        assert not result.error.safe_to_resume
    assert (tmp_path / "notes.txt").read_text() == expected


@pytest.mark.asyncio
async def test_analyze_image_rejects_invalid_image_bytes(tmp_path):
    image = tmp_path / "broken.png"
    image.write_bytes(b"not an image")
    result = await _analyze_image(str(image))
    assert result.content[0].value["data"]["reason"] == "invalid_image"
    assert "followup_user_message" not in result.metadata


@pytest.mark.asyncio
@pytest.mark.parametrize("resolved", [False, True])
async def test_analyze_image_text_only_model_does_not_read_or_attach(resolved):
    runtime = _ImageRuntime()
    runtime.supports_multimodal_input = (lambda agent_id: False) if resolved else False
    result = await MediaTools(runtime).analyze_image(
        image_path="/missing.png", session_id="session_1",
        invocation=ToolInvocation(call("analyze_image", {}), CONTEXT),
    )
    assert result.content[0].value["data"]["reason"] == "multimodal_unsupported"
    assert "followup_user_message" not in result.metadata

@pytest.mark.asyncio
@pytest.mark.parametrize("environment", ["{broken", "[]", '{"KEY": 3}'])
async def test_shell_environment_validation_fails_before_job_submission(
    tmp_path, environment
):
    plugin = await plugin_for(tmp_path)
    with pytest.raises(SageV2Error) as failure:
        await plugin.executor.execute(
            call(
                "execute_shell_command",
                {
                    "command": "printf should-not-run",
                    "env_vars": environment,
                },
            ),
            CONTEXT,
        )
    assert failure.value.info.code == "tool.arguments_invalid"
    assert failure.value.info.metadata["side_effect_state"] == "not_applied"
    assert await plugin.runtime.job_runtime.list_run_jobs("run_1") == ()


@pytest.mark.asyncio
@pytest.mark.parametrize("statuses", [(404,), (503,), (503, None), (503, 200)])
async def test_web_fetch_never_treats_failed_http_response_as_success(
    statuses, monkeypatch
):
    from sagents.v2.runtime.execution.sandbox import NetworkResult
    from sagents.v2.tool.official.web import WebTools

    class NetworkRuntime:
        def __init__(self):
            self.statuses = iter(statuses)

        async def network_request(self, url, invocation, **kwargs):
            status = next(self.statuses)
            if status is None:
                raise TimeoutError("network timeout")
            return NetworkResult(
                request_id="request_1",
                status_code=status,
                final_url=url,
                headers={"content-type": "text/plain"},
                body=b"response body",
            )

        async def write_bytes(self, *args):
            pytest.fail("an HTTP error body must not be downloaded")

    async def no_wait(delay):
        pass

    monkeypatch.setattr("sagents.v2.tool.official.web.asyncio.sleep", no_wait)
    result = await WebTools(NetworkRuntime()).fetch_webpages(
        ["https://example.test/resource"], None, retries=len(statuses) - 1
    )
    expected = "success" if statuses[-1] == 200 else "error"
    assert result["status"] == expected
    assert result["results"][0]["status"] == expected
    if expected == "error":
        assert "content" not in result["results"][0]
        expected_error = (
            "network timeout" if statuses[-1] is None else f"HTTP {statuses[-1]}"
        )
        assert expected_error in result["results"][0]["error"]


@pytest.mark.asyncio
async def test_web_fetch_reports_partial_batch_failure():
    from sagents.v2.runtime.execution.sandbox import NetworkResult
    from sagents.v2.tool.official.web import WebTools

    class NetworkRuntime:
        async def network_request(self, url, invocation, **kwargs):
            return NetworkResult(
                request_id="request_1",
                status_code=404 if url.endswith("missing") else 200,
                final_url=url,
                headers={"content-type": "text/plain"},
                body=b"body",
            )

    result = await WebTools(NetworkRuntime()).fetch_webpages(
        ["https://example.test/missing", "https://example.test/ok"], None, retries=0
    )
    assert result["status"] == "partial"
    assert [row["status"] for row in result["results"]] == ["error", "success"]


@pytest.mark.parametrize("tasks", [
    [{"id": "new"}],
    [{"id": "1", "content": "one", "status": "in_progress"},
     {"id": "2", "content": "two", "status": "in_progress"}],
])
async def test_todo_preflight_validation_is_not_applied(tmp_path: Path, tasks):
    plugin = await plugin_for(tmp_path)
    with pytest.raises(SageV2Error) as caught:
        await plugin.executor.execute(call("todo_write", {"session_id": "session_1", "tasks": tasks}), CONTEXT)
    assert caught.value.info.metadata["side_effect_state"] == "not_applied"
    assert not (tmp_path / ".sage" / "todos" / "session_1.json").exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("tool_name,arguments", [
    ("file_read", {"file_path": "value.txt"}),
    ("file_write", {"file_path": "value.txt", "content": "changed"}),
    ("file_update", {"file_path": "value.txt", "operations": [
        {"update_mode": "search_replace", "search_pattern": "original", "replacement": "changed"}
    ]}),
])
async def test_lost_compute_preserves_file_tools(
    tmp_path, tool_name, arguments
):
    from sagents.v2.runtime.execution.sandbox import SandboxState

    plugin = await plugin_for(tmp_path)
    (tmp_path / "value.txt").write_text("original")
    runtime = plugin.runtime
    row = runtime.sandbox.filesystem.row
    row.boundary._mark_lost("sandbox disk quota exceeded", reason="disk_limit_exceeded")
    assert row.state == SandboxState.LOST
    await plugin.executor.execute(call(tool_name, arguments), CONTEXT)
    expected = "original" if tool_name == "file_read" else "changed"
    assert (tmp_path / "value.txt").read_text() == expected
    assert row.state == SandboxState.LOST


@pytest.mark.asyncio
async def test_missing_workspace_and_lost_compute_is_fatal(tmp_path):
    import shutil

    plugin = await plugin_for(tmp_path)
    row = plugin.runtime.sandbox.filesystem.row
    row.boundary._mark_lost("resource monitor failed", reason="resource_monitor_failed")
    shutil.rmtree(tmp_path)
    with pytest.raises(SageV2Error) as caught:
        await plugin.executor.execute(call("file_read", {"file_path": "value.txt"}), CONTEXT)
    info = caught.value.info
    assert info.category == ErrorCategory.RESOURCE_LOST
    assert not info.safe_to_resume
    assert info.metadata["workspace_available"] is False
    assert "workspace_available=False" in info.message
    assert "resource monitor failed" in info.message


def test_sandbox_denial_mapping_does_not_make_resource_loss_resumable():
    from sagents.v2.tool.official.runtime import sandbox_denial_as_not_applied

    failure = SageV2Error(RuntimeErrorInfo(
        code="sandbox.lost", category=ErrorCategory.RESOURCE_LOST,
        message="sandbox execution environment lost",
    ))
    mapped = sandbox_denial_as_not_applied(failure)
    assert mapped is None
    assert not failure.info.safe_to_resume
    assert "side_effect_state" not in failure.info.metadata


@pytest.mark.asyncio
async def test_shell_job_resource_loss_reaches_tool_executor(tmp_path, monkeypatch):
    plugin = await plugin_for(tmp_path)

    async def lost_after_launch(*args, **kwargs):
        raise SageV2Error(RuntimeErrorInfo(
            code="sandbox.lost", category=ErrorCategory.RESOURCE_LOST,
            message="sandbox monitor failed after launch",
        ))

    monkeypatch.setattr(plugin.runtime.sandbox.process, "run", lost_after_launch)
    try:
        with pytest.raises(SageV2Error) as caught:
            await plugin.executor.execute(call("execute_shell_command", {
                "command": "echo test", "block_until_ms": 1000,
            }), CONTEXT)
        assert caught.value.info.category == ErrorCategory.RESOURCE_LOST
        assert not caught.value.info.safe_to_resume
        assert "side_effect_state" not in caught.value.info.metadata
    finally:
        await plugin.executor.release_run("run_1")
