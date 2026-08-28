from __future__ import annotations

import json
import sqlite3
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

import pytest

from app.desktop_v2.backend.catalog import DesktopMcpRecord
from app.desktop_v2.backend.service import (
    ComponentSelectionRequest,
    DesktopV2Settings,
    DesktopV2Service,
    ModelProviderCreate,
    ModelProviderPatch,
    DesktopRunRequest,
    RunMessage,
)
from sagents.v2.contracts.errors import SageV2Error
from sagents.v2.contracts.commands import InputItem, StartRun
from sagents.v2.contracts.items import TextBlock
from sagents.v2.contracts.run_state import SessionConcurrencyMode
from sagents.v2.contracts.session_commit import (
    SessionCommitProposalStatus,
    SessionMergeStrategy,
)
from sagents.v2.agent import AgentLoopEngine
from sagents.v2.model import (
    ModelEventKind,
    ModelResponse,
    ModelStreamEvent,
    ScriptedModelProvider,
)
from sagents.v2.testing.plugins.scripted_model import ScriptedModelStep
from sagents.v2.tool import InMemoryToolCatalog, InMemoryToolExecutor
from sagents.v2.package.manifest.resolver import CompositionResolver
from sagents.v2.context import ModelConversationSummarizer
from sagents.v2.tool import McpServerConfig, McpToolPlugin


@pytest.mark.parametrize(
    "language",
    ["system", "zh", "en", "pt", "es", "fr", "de", "ja", "ko", "ru"],
)
def test_desktop_settings_accept_supported_frontend_languages(language: str):
    assert DesktopV2Settings(language=language).language == language


def test_desktop_settings_reject_unknown_frontend_language():
    with pytest.raises(ValueError):
        DesktopV2Settings(language="unsupported")  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_desktop_catalog_is_native_seeded_and_persistent(tmp_path: Path):
    service = DesktopV2Service(tmp_path / "sage")
    agents = await service.list_agents("user_1")
    providers = await service.list_model_providers("user_1")

    assert agents == [
        {
            "id": "sage",
            "name": "Sage",
            "is_default": True,
            "tool_count": 14,
            "skill_count": 0,
        }
    ]
    assert providers[0]["protocol"] == "openai-responses"
    assert providers[0]["api_key_configured"] is False
    payload = json.loads(
        (tmp_path / "sage/runtime/desktop-catalog.json").read_text(encoding="utf-8")
    )
    assert payload["format_version"] == "sage.desktop-catalog/v2"
    assert "legacy" not in json.dumps(payload).lower()
    await service.session_store.close()


@pytest.mark.asyncio
async def test_model_patch_persists_explicit_protocol_and_secret(tmp_path: Path):
    service = DesktopV2Service(tmp_path)
    await service.list_agents("user_1")

    value = await service.patch_model_provider(
        "model_main",
        ModelProviderPatch(
            protocol="anthropic-messages",
            model="claude-test",
            base_url="https://api.anthropic.test",
            api_keys=["secret"],
        ),
        "user_1",
    )

    assert value["protocol"] == "anthropic-messages"
    assert value["api_key_configured"] is True
    assert await service.reveal_model_provider_api_key("model_main", "user_1") == {
        "api_key": "secret"
    }
    await service.session_store.close()


@pytest.mark.asyncio
async def test_model_provider_can_be_created(tmp_path: Path):
    service = DesktopV2Service(tmp_path)
    created = await service.create_model_provider(
        ModelProviderCreate(
            name="Secondary",
            protocol="anthropic-messages",
            model="claude-test",
            base_url="https://anthropic.test",
            api_keys=["secret"],
            max_tokens=4096,
            max_model_len=100_000,
        ),
        "user_1",
    )

    assert created["name"] == "Secondary"
    assert created["protocol"] == "anthropic-messages"
    assert created["api_key_configured"] is True
    assert len(await service.list_model_providers("user_1")) == 2
    await service.session_store.close()


@pytest.mark.asyncio
async def test_v1_model_and_anytool_settings_are_imported_once(tmp_path: Path):
    legacy = tmp_path / "legacy.db"
    connection = sqlite3.connect(legacy)
    connection.executescript(
        """
        CREATE TABLE llm_providers (
          id TEXT PRIMARY KEY, name TEXT, base_url TEXT, api_keys TEXT, model TEXT,
          max_tokens INTEGER, temperature REAL, top_p REAL, presence_penalty REAL,
          max_model_len INTEGER, supports_multimodal INTEGER,
          supports_structured_output INTEGER, is_default INTEGER, user_id TEXT
        );
        CREATE TABLE mcp_servers (name TEXT, user_id TEXT, config TEXT);
        """
    )
    connection.execute(
        "INSERT INTO llm_providers VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            "legacy_model",
            "Legacy",
            "https://legacy.test/v1",
            '["legacy-secret"]',
            "legacy-gpt",
            4096,
            0.2,
            None,
            0.0,
            64_000,
            1,
            1,
            1,
            "default_user",
        ),
    )
    connection.execute(
        "INSERT INTO mcp_servers VALUES (?,?,?)",
        (
            "AnyTool",
            "default_user",
            json.dumps(
                {
                    "kind": "anytool",
                    "protocol": "streamable_http",
                    "streamable_http_url": "http://127.0.0.1:18080/api/mcp/anytool/AnyTool",
                    "disabled": False,
                    "tools": [],
                }
            ),
        ),
    )
    connection.commit()
    connection.close()

    service = DesktopV2Service(
        tmp_path / "v2",
        legacy_db_path=legacy,
    )
    first = await service.list_model_providers("default_user")
    second = await service.list_model_providers("default_user")
    agent = await service._agent("sage", "default_user")
    mcp = await service.catalog.list_mcp("default_user")

    assert [value["id"] for value in first] == ["legacy_model"]
    assert second == first
    assert first[0]["protocol"] == "openai-chat-completions"
    assert first[0]["api_key_configured"] is True
    assert agent.config["llm_provider_id"] == "legacy_model"
    assert [(value.name, value.kind, value.tools) for value in mcp] == [
        ("AnyTool", "anytool", ()),
    ]
    await service.session_store.close()


@pytest.mark.asyncio
async def test_model_patch_rejects_an_invalid_route_before_persisting(tmp_path: Path):
    service = DesktopV2Service(tmp_path)
    await service.list_agents("user_1")

    with pytest.raises(ValueError, match="absolute http"):
        await service.patch_model_provider(
            "model_main", ModelProviderPatch(base_url="not-a-url"), "user_1"
        )

    provider = (await service.list_model_providers("user_1"))[0]
    assert provider["base_url"] == "https://api.openai.com/v1"
    await service.session_store.close()


@pytest.mark.asyncio
async def test_desktop_catalog_scopes_reused_ids_by_user(tmp_path: Path):
    service = DesktopV2Service(tmp_path)
    await service.list_agents("user_1")
    await service.list_agents("user_2")

    await service.patch_model_provider(
        "model_main",
        ModelProviderPatch(protocol="anthropic-messages", model="claude-user-1"),
        "user_1",
    )
    first = (await service.list_model_providers("user_1"))[0]
    second = (await service.list_model_providers("user_2"))[0]

    assert first["model"] == "claude-user-1"
    assert first["protocol"] == "anthropic-messages"
    assert second["model"] != "claude-user-1"
    assert second["protocol"] == "openai-responses"
    payload = json.loads(
        (tmp_path / "runtime/desktop-catalog.json").read_text(encoding="utf-8")
    )
    assert [value["id"] for value in payload["model_providers"]].count(
        "model_main"
    ) == 2
    await service.session_store.close()


@pytest.mark.asyncio
async def test_component_inventory_explains_plugins_and_locks_model_protocol(
    tmp_path: Path,
):
    service = DesktopV2Service(tmp_path)
    inventory = await service.component_inventory("user_1")
    by_id = {value["plugin_id"]: value for value in inventory}

    assert {
        "sage.session.filesystem",
        "sage.session.ephemeral",
        "sage.memory.noop",
        "sage.model.openai-responses",
    } <= by_id.keys()
    assert by_id["sage.session.filesystem"]["capabilities"] == {
        "durable": True,
        "global_session_index": False,
        "multi_process_writes": False,
    }
    with pytest.raises(SageV2Error) as unavailable:
        await service.select_component(
            "model.provider",
            ComponentSelectionRequest(plugin_id="unregistered.model"),
            "user_1",
        )
    assert unavailable.value.info.code == "extension.not_found"
    await service.session_store.close()


@pytest.mark.asyncio
async def test_extension_inventory_is_not_a_dynamic_desktop_tool_catalog(
    tmp_path: Path,
):
    service = DesktopV2Service(tmp_path)
    await service.list_agents("user_1")
    await service.catalog.save_mcp(
        DesktopMcpRecord(
            user_id="user_1",
            name="files",
            protocol="stdio",
            command="mcp-files",
        )
    )

    inventory = await service.component_inventory("user_1")
    assert not any(value["plugin_id"] == "native-mcp" for value in inventory)
    await service.session_store.close()


@pytest.mark.asyncio
async def test_tool_catalog_does_not_hide_in_process_sage_mcp_tools(tmp_path: Path):
    service = DesktopV2Service(tmp_path)
    tools = await service.list_tools("user_1")
    by_name = {value["name"]: value for value in tools}

    expected = {
        "generate_image",
        "search_web_page",
        "search_image_from_web",
        "analyze_video",
        "list_tasks",
        "add_task",
        "delete_task",
        "complete_task",
        "enable_task",
        "get_task_details",
        "update_task",
        "send_file_through_im",
        "send_image_through_im",
        "send_message_through_im",
    }
    assert expected.isdisjoint(by_name)
    assert "file_read" in by_name
    assert by_name["file_read"]["type"] == "basic"
    await service.session_store.close()


@pytest.mark.asyncio
async def test_user_component_selection_is_persisted_with_apply_semantics(
    tmp_path: Path,
):
    service = DesktopV2Service(tmp_path)
    selection = await service.select_component(
        "session.store",
        ComponentSelectionRequest(plugin_id="sage.session.ephemeral"),
        "user_1",
    )

    assert selection["plugin_id"] == "sage.session.ephemeral"
    assert selection["pending_restart"] is True
    settings = await service.get_settings()
    assert settings.component_selections == {
        "session.store": "sage.session.ephemeral",
    }
    await service.session_store.close()


@pytest.mark.asyncio
async def test_skills_are_discovered_and_imported_by_native_filesystem_provider(
    tmp_path: Path,
):
    source = tmp_path / "source"
    source.mkdir()
    (source / "SKILL.md").write_text(
        "---\nname: review\ndescription: Review code\n---\n# Review\n",
        encoding="utf-8",
    )
    service = DesktopV2Service(tmp_path / "data")

    result = await service.import_skill_folder(str(source), "user_1")
    catalog = await service.list_skill_catalog("user_1")

    assert result["imported_names"] == ["review"]
    review = next(value for value in catalog if value["name"] == "review")
    assert review["description"] == "Review code"
    assert "# Review" in await service.get_skill_content("review", "user_1")
    with pytest.raises(ValueError, match="already exists"):
        await service.import_skill_folder(str(source), "user_1")
    await service.session_store.close()


@pytest.mark.asyncio
async def test_workspace_paths_remain_contained(tmp_path: Path):
    service = DesktopV2Service(tmp_path / "data")
    root = await service.workspace_root(None, "sage")
    (root / "hello.txt").write_text("hello", encoding="utf-8")

    content, media_type = await service.read_file(None, "sage", "hello.txt")

    assert content == b"hello"
    assert media_type == "text/plain; charset=utf-8"
    with pytest.raises(PermissionError):
        await service.read_file(None, "sage", "../outside.txt")
    await service.session_store.close()


@pytest.mark.asyncio
async def test_loop_composition_uses_native_model_skill_tool_and_sandbox_plugins(
    tmp_path: Path,
):
    service = DesktopV2Service(tmp_path)
    await service.list_agents("user_1")
    await service.patch_model_provider(
        "model_main", ModelProviderPatch(api_keys=["test-key"]), "user_1"
    )
    agent = await service._agent("sage", "user_1")
    provider = await service._provider(agent, "user_1")
    workspace = await service.workspace_root(None, "sage")

    resolved, loop, sandbox = await service._build_loop(
        agent=agent,
        provider=provider,
        workspace=workspace,
        preferred_skills=(),
        approval_mode="high_risk",
    )

    names = {value.name for value in await loop.tool_catalog.list_tools(run_id="run_1")}
    assert resolved.model_routes["primary"]["provider"] == "openai-responses"
    assert sandbox.ref.provider_id == "sage.sandbox.local-workspace"
    assert isinstance(
        loop.context_assembler.reducer.summarizer, ModelConversationSummarizer
    )
    assert {"file_read", "execute_shell_command", "todo_write", "load_skill"} <= names
    await sandbox.close()
    await service.session_store.close()


@pytest.mark.asyncio
async def test_loop_composition_includes_enabled_configured_mcp_tools(
    tmp_path: Path,
):
    class Session:
        async def list_tools(self):
            return {
                "tools": [
                    {
                        "name": "lookup",
                        "description": "Lookup",
                        "inputSchema": {"type": "object", "properties": {}},
                    }
                ]
            }

    @asynccontextmanager
    async def session_factory(config):
        yield Session()

    bridge = McpToolPlugin(
        (
            McpServerConfig(
                name="remote", protocol="streamable_http", url="https://mcp.test"
            ),
        ),
        session_factory=session_factory,
    )
    service = DesktopV2Service(tmp_path)

    async def bridge_for_user(user_id):
        return bridge

    service._mcp_plugin = bridge_for_user
    await service.list_agents("user_1")
    await service.patch_model_provider(
        "model_main", ModelProviderPatch(api_keys=["test-key"]), "user_1"
    )
    agent = await service._agent("sage", "user_1")
    config = dict(agent.config)
    config["availableTools"] = [*config["availableTools"], "mcp_remote_lookup"]
    await service.catalog.save_agent(agent.model_copy(update={"config": config}))
    agent = await service._agent("sage", "user_1")
    provider = await service._provider(agent, "user_1")
    workspace = await service.workspace_root(None, "sage")

    _, loop, sandbox = await service._build_loop(
        agent=agent,
        provider=provider,
        workspace=workspace,
        preferred_skills=(),
        approval_mode="high_risk",
    )

    names = {value.name for value in await loop.tool_catalog.list_tools(run_id="run_1")}
    assert "mcp_remote_lookup" in names
    await sandbox.close()
    await service.session_store.close()


@pytest.mark.asyncio
async def test_desktop_command_freezes_language_identity_time_and_workspace_context(
    tmp_path: Path,
):
    service = DesktopV2Service(tmp_path)
    await service.initialize_agent_workspace()
    (service.agent_workspace / "SOUL.md").write_text("Be precise", encoding="utf-8")
    await service.list_agents("user_1")
    agent = await service._agent("sage", "user_1")
    provider = (await service.catalog.list_model_providers("user_1"))[0]
    resolved = service._manifest(agent, provider, ("todo_write",), ())
    resolved = CompositionResolver().resolve(resolved)
    workspace = await service.workspace_root(None, "sage")

    command = service._command(
        DesktopRunRequest(
            agent_id="sage",
            messages=[RunMessage(role="user", text="hello")],
            session_concurrency_mode=SessionConcurrencyMode.SNAPSHOT_ISOLATED,
            base_session_revision=0,
        ),
        resolved,
        agent=agent,
        workspace=workspace,
    )

    metadata = command.config.metadata
    assert command.session_concurrency_mode == SessionConcurrencyMode.SNAPSHOT_ISOLATED
    assert command.base_session_revision == 0
    assert metadata["response_language"] == "zh"
    assert metadata["identity_documents"] == {"SOUL": "Be precise"}
    assert metadata["working_directory"] == str(workspace)
    assert (
        datetime.strptime(metadata["current_time"], "%a, %d %b %Y %H:%M:%S %z").tzinfo
        is not None
    )
    assert metadata["workspace_files"].startswith("Working directory: ")
    await service.session_store.close()


@pytest.mark.asyncio
async def test_desktop_exposes_snapshot_propose_publish_and_session_inventory(
    tmp_path: Path,
):
    service = DesktopV2Service(tmp_path)
    context = service._context("user_1")
    handle = await service.runtime.start_run(
        StartRun(
            agent_id="sage",
            input=(InputItem(role="user", content=(TextBlock(text="candidate"),)),),
            session_concurrency_mode=SessionConcurrencyMode.SNAPSHOT_ISOLATED,
            resolved_spec_hash="sha256:test",
            idempotency_key="snapshot",
        ),
        context,
    )
    completed = ModelStreamEvent(
        kind=ModelEventKind.COMPLETED,
        response=ModelResponse(
            response_id="response_1",
            text="candidate answer",
            finish_reason="stop",
        ),
    )
    await AgentLoopEngine(
        runtime=service.runtime,
        model=ScriptedModelProvider((ScriptedModelStep(events=(completed,)),)),
        tool_catalog=InMemoryToolCatalog(()),
        tool_executor=InMemoryToolExecutor({}, {}),
    ).execute(handle.run_id, context)

    proposal = await service.propose_session_commit(handle.run_id, "user_1")
    published = await service.publish_session_commit(
        proposal.proposal_id,
        SessionMergeStrategy.REQUIRE_UNCHANGED_BASE,
        "user_1",
    )
    snapshot = await service.session_snapshot(handle.session_id)

    assert published.status == SessionCommitProposalStatus.PUBLISHED
    assert snapshot["commit_proposals"] == [published.model_dump(mode="json")]
    assert (
        await service.session_commit_proposals(handle.session_id)
        == snapshot["commit_proposals"]
    )
    await service.session_store.close()


@pytest.mark.asyncio
async def test_desktop_session_index_is_not_authoritative(tmp_path: Path):
    service = DesktopV2Service(tmp_path)
    handle = await service.runtime.start_run(
        StartRun(
            agent_id="sage",
            input=(InputItem(role="user", content=(TextBlock(text="hello"),)),),
            resolved_spec_hash="sha256:test",
            idempotency_key="index-boundary",
        ),
        service._context("user_1"),
    )
    await service._index_session(handle.session_id)
    assert [value["session_id"] for value in await service.list_sessions()] == [
        handle.session_id
    ]

    service.session_index.path.unlink()
    assert await service.list_sessions() == []
    assert (await service.session_store.get_session(handle.session_id)).session_id == (
        handle.session_id
    )
    await service.session_store.close()


@pytest.mark.asyncio
async def test_desktop_index_failure_does_not_rollback_session_commit(tmp_path: Path):
    service = DesktopV2Service(tmp_path)
    handle = await service.runtime.start_run(
        StartRun(
            agent_id="sage",
            input=(InputItem(role="user", content=(TextBlock(text="hello"),)),),
            resolved_spec_hash="sha256:test",
            idempotency_key="index-failure",
        ),
        service._context("user_1"),
    )

    async def fail(_value):
        raise OSError("index unavailable")

    service.session_index.upsert = fail
    await service._index_session(handle.session_id)
    assert (await service.session_store.get_session(handle.session_id)).revision == 1
    await service.session_store.close()
