from __future__ import annotations

import json
import sqlite3
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.desktop_v2.backend.catalog import DesktopMcpRecord
from app.desktop_v2.backend.service import (
    AgentCreate,
    AgentRosterContextProvider,
    AgentSettingsPatch,
    ComponentSelectionRequest,
    DesktopV2Settings,
    DesktopV2Service,
    ModelProviderCreate,
    ModelProviderPatch,
    DesktopRunRequest,
    RunMessage,
)
from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo, SageV2Error
from sagents.v2.contracts.events import (
    EventDurability,
    EventSource,
    EventSourceType,
    RunEventData,
    RuntimeEvent,
)
from sagents.v2.contracts.common import utc_now
from sagents.v2.contracts.commands import (
    CancelRun,
    InputItem,
    ReplyInteraction,
    RunConfig,
    StartRun,
)
from sagents.v2.contracts.items import TextBlock
from sagents.v2.contracts.run_state import SessionConcurrencyMode
from sagents.v2.contracts.session_commit import (
    SessionCommitProposalStatus,
    SessionMergeStrategy,
)
from sagents.v2.agent import AgentLoopEngine
from sagents.v2.agent.multi_agent import AgentMode, AgentRegistry
from sagents.v2.agent.policy import (
    ExplicitStatusContinuationPolicy,
    LLMJudgeContinuationPolicy,
)
from sagents.v2.model import (
    ModelEventKind,
    ModelResponse,
    ModelStreamEvent,
    ModelToolCall,
    ScriptedModelProvider,
)
from sagents.v2.testing.plugins.scripted_model import ScriptedModelStep
from sagents.v2.tool import InMemoryToolCatalog, InMemoryToolExecutor
from sagents.v2.package.manifest.resolver import CompositionResolver
from sagents.v2.context import ModelConversationSummarizer
from sagents.v2.memory import (
    DirectMemoryRecallQueryGenerator,
    LLMMemoryRecallQueryGenerator,
)
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


def test_legacy_plan_mode_request_migrates_to_typed_invocation_mode():
    request = DesktopRunRequest(
        agent_id="sage",
        messages=[RunMessage(role="user", text="plan it")],
        plan_mode=True,
    )

    assert request.invocation_mode == "plan"


@pytest.mark.asyncio
async def test_desktop_catalog_is_native_seeded_and_persistent(tmp_path: Path):
    service = DesktopV2Service(tmp_path / "sage")
    agents = await service.list_agents("user_1")
    providers = await service.list_model_providers("user_1")

    assert service.diagnostics.root == tmp_path / "sage/runtime/sessions"
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
async def test_usage_overview_aggregates_tokens_agents_turns_and_tools(
    tmp_path: Path,
):
    service = DesktopV2Service(tmp_path / "sage")
    await service.list_agents("user_1")
    now = utc_now()
    service.session_index.list = AsyncMock(
        return_value=(SimpleNamespace(session_id="session_1"),)
    )
    service.session_store.list_session_runs = AsyncMock(
        return_value=(SimpleNamespace(run_id="run_1"),)
    )
    service.session_store.get_start_command = AsyncMock(
        return_value=SimpleNamespace(agent_id="sage")
    )
    service.session_store.read_session_events = AsyncMock(
        return_value=(
            SimpleNamespace(
                occurred_at=now,
                type="turn.started",
                run_id="run_1",
                data=SimpleNamespace(),
            ),
            SimpleNamespace(
                occurred_at=now,
                type="tool.call.proposed",
                run_id="run_1",
                data=SimpleNamespace(tool_name="read_file"),
            ),
        )
    )
    service.diagnostics.list_model_requests = AsyncMock(
        return_value=(
            {
                "status": "completed",
                "session_id": "session_1",
                "run_id": "run_1",
                "completed_at": now.isoformat(),
                "metadata": {"agent_id": "sage", "model_binding": "primary"},
                "request": {"model": "gpt-test", "messages": []},
                "response": {
                    "usage": {
                        "input_tokens": 120,
                        "output_tokens": 30,
                        "cached_input_tokens": 40,
                        "reasoning_tokens": 10,
                        "models": ["gpt-test"],
                    }
                },
            },
        )
    )

    value = await service.usage_overview("user_1", days=7, timezone_offset_minutes=480)

    assert value["totals"] == {
        "input_tokens": 120,
        "output_tokens": 30,
        "cached_input_tokens": 40,
        "reasoning_tokens": 10,
        "total_tokens": 150,
        "model_requests": 1,
        "failed_model_requests": 0,
        "turns": 1,
        "tool_calls": 1,
        "sessions": 1,
    }
    assert value["models"][0]["name"] == "gpt-test"
    assert value["agents"][0]["name"] == "Sage"
    assert value["agents"][0]["total_tokens"] == 150
    assert value["tools"] == [{"name": "read_file", "count": 1}]
    assert value["daily"][-1]["total_tokens"] == 150
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
    assert created["is_default"] is False

    await service.patch_model_provider(
        created["id"], ModelProviderPatch(is_default=True), "user_1"
    )
    providers = await service.list_model_providers("user_1")
    assert len(providers) == 2
    assert [value["id"] for value in providers if value["is_default"]] == [
        created["id"]
    ]
    await service.session_store.close()


@pytest.mark.asyncio
async def test_v2_does_not_read_v1_model_or_mcp_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("HOME", str(tmp_path))
    legacy_dir = tmp_path / ".sage"
    legacy_dir.mkdir()
    legacy = legacy_dir / "sage.db"
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

    service = DesktopV2Service()
    first = await service.list_model_providers("default_user")
    second = await service.list_model_providers("default_user")
    agent = await service._agent("sage", "default_user")
    mcp = await service.catalog.list_mcp("default_user")

    assert [value["id"] for value in first] == ["model_main"]
    assert second == first
    assert first[0]["name"] == "OpenAI"
    assert first[0]["api_key_configured"] is False
    assert agent.config["llm_provider_id"] == "model_main"
    assert agent.config["fast_llm_provider_id"] == "model_main"
    assert mcp == ()
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
    by_id = {value["component"]["component_id"]: value for value in inventory}

    assert set(by_id) == {
        "agent.continuation-policy",
        "context.token-estimator",
        "context.reducer",
        "context.summarizer",
        "context.summary-store",
        "memory.provider",
        "memory.recall-query",
        "tool.selection-policy",
        "session-memory.provider",
        "observability.diagnostic-sink",
        "observability.log-sink",
        "execution.sandbox",
        "session.store",
        "workspace.initializer",
    }
    assert by_id["agent.continuation-policy"]["active"]["config"] == {
        "repeat_threshold": 3,
        "mode": "deterministic",
        "completion_reason": "text.final",
        "status_source": "turn_status",
        "explicit_statuses": [
            "task_done",
            "need_user_input",
            "blocked",
            "continue_work",
            "failed",
        ],
        "flow_boundaries": ["complete_node", "continue_node"],
        "uses_llm_judge": False,
        "uses_finish_reason": False,
    }
    assert {
        value["plugin_id"] for value in by_id["agent.continuation-policy"]["plugins"]
    } == {
        "sage.agent.continuation.deterministic",
        "sage.agent.continuation.llm-judge",
        "sage.agent.continuation.explicit-status",
    }
    assert by_id["context.reducer"]["active"]["plugin_id"] == (
        "sage.context.reducer.persistent-summary"
    )
    assert by_id["memory.recall-query"]["active"]["plugin_id"] == (
        "sage.memory.recall-query.direct"
    )
    assert {
        value["plugin_id"] for value in by_id["memory.recall-query"]["plugins"]
    } == {
        "sage.memory.recall-query.direct",
        "sage.memory.recall-query.llm",
    }
    assert {
        value["plugin_id"] for value in by_id["tool.selection-policy"]["plugins"]
    } == {
        "sage.tool-selection.direct",
        "sage.tool-selection.llm",
        "sage.tool-selection.lexical",
        "sage.tool-selection.recent",
    }
    assert by_id["tool.selection-policy"]["active"] == {
        "plugin_id": "sage.tool-selection.llm",
        "selected_plugin_id": "sage.tool-selection.llm",
        "source": "default",
        "config": {"max_visible_tools": 24},
        "pending_restart": False,
    }
    tool_plugins = {
        value["plugin_id"]: value for value in by_id["tool.selection-policy"]["plugins"]
    }
    assert (
        tool_plugins["sage.tool-selection.direct"]["config_schema"]["properties"] == {}
    )
    assert set(
        tool_plugins["sage.tool-selection.llm"]["config_schema"]["properties"]
    ) == {"max_visible_tools"}
    assert {
        value["plugin_id"] for value in by_id["context.token-estimator"]["plugins"]
    } >= {
        "sage.context.token-estimator.json-heuristic",
        "sage.context.token-estimator.unicode-heuristic",
    }
    assert by_id["observability.log-sink"]["active"] == {
        "plugin_id": "sage.logging.filesystem",
        "selected_plugin_id": "sage.logging.filesystem",
        "source": "default",
        "config": {
            "format_version": "sage.log/v1",
            "path": str(tmp_path / "runtime/logs/sage.jsonl"),
            "min_level": "info",
            "max_bytes": 10 * 1024 * 1024,
            "backup_count": 5,
        },
        "pending_restart": False,
    }
    assert {
        value["plugin_id"] for value in by_id["observability.log-sink"]["plugins"]
    } == {"sage.logging.filesystem", "sage.logging.noop"}
    assert by_id["workspace.initializer"]["active"]["plugin_id"] == (
        "sage.workspace.initializer.claw"
    )
    assert by_id["execution.sandbox"]["active"]["config"] == {
        "workspace_root": "/workspace",
        "workspace_mapping": "active_workspace",
        "filesystem_mode": "workspace",
        "workspace_path_mode": "virtual",
    }
    assert {
        value["plugin_id"] for value in by_id["workspace.initializer"]["plugins"]
    } == {
        "sage.workspace.initializer.bare",
        "sage.workspace.initializer.claw",
    }
    assert by_id["memory.provider"]["active"] == {
        "plugin_id": "sage.memory.filesystem-bm25",
        "selected_plugin_id": "sage.memory.filesystem-bm25",
        "source": "default",
        "config": {
            "path": str(tmp_path / "runtime/memory"),
            "recall": True,
            "auto_write": True,
            "scope_mode": "agent",
        },
        "pending_restart": False,
    }
    assert by_id["session-memory.provider"]["active"] == {
        "plugin_id": "sage.session-memory.sqlite-bm25",
        "selected_plugin_id": "sage.session-memory.sqlite-bm25",
        "source": "default",
        "config": {
            "path": str(tmp_path / "runtime/session-memory"),
            "derived_from": "session.events",
        },
        "pending_restart": False,
    }
    assert by_id["session.store"]["active"]["config"] == {
        "path": str(tmp_path / "runtime/sessions"),
        "authoritative": True,
    }
    with pytest.raises(ValueError, match="not user configurable"):
        await service.select_component(
            "model.provider",
            ComponentSelectionRequest(plugin_id="unregistered.model"),
            "user_1",
        )
    with pytest.raises(SageV2Error) as unavailable:
        await service.select_component(
            "context.reducer",
            ComponentSelectionRequest(plugin_id="unregistered.reducer"),
            "user_1",
        )
    assert unavailable.value.info.code == "extension.not_found"
    logging_selection = await service.select_component(
        "observability.log-sink",
        ComponentSelectionRequest(plugin_id="sage.logging.noop"),
        "user_1",
    )
    assert logging_selection["pending_restart"] is True
    inventory = await service.component_inventory("user_1")
    logging_component = next(
        value
        for value in inventory
        if value["component"]["component_id"] == "observability.log-sink"
    )
    assert logging_component["active"]["plugin_id"] == "sage.logging.filesystem"
    assert logging_component["active"]["selected_plugin_id"] == ("sage.logging.noop")
    assert logging_component["active"]["pending_restart"] is True
    session_memory_selection = await service.select_component(
        "session-memory.provider",
        ComponentSelectionRequest(plugin_id="sage.session-memory.noop"),
        "user_1",
    )
    assert session_memory_selection["plugin_id"] == "sage.session-memory.noop"
    assert session_memory_selection["pending_restart"] is True
    await service.session_store.close()


@pytest.mark.asyncio
async def test_agent_runtime_failures_are_projected_to_structured_logs(
    tmp_path: Path,
):
    service = DesktopV2Service(tmp_path)
    event = RuntimeEvent(
        event_id="event_failed",
        type="run.failed",
        occurred_at=utc_now(),
        durability=EventDurability.DURABLE,
        session_id="session_1",
        run_id="run_1",
        session_sequence=1,
        run_sequence=4,
        actor=service._context("user_1").actor,
        source=EventSource(source_type=EventSourceType.AGENT, source_id="sage"),
        data=RunEventData(
            state="failed",
            error=RuntimeErrorInfo(
                code="agent.loop_failed",
                category=ErrorCategory.INTERNAL,
                message="Agent loop crashed",
            ),
        ),
    )

    service._write_runtime_event(event)

    rows = [
        json.loads(line)
        for line in (tmp_path / "runtime/logs/sage.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    failed = rows[-1]
    assert failed["event"] == "run.failed"
    assert failed["level"] == "error"
    assert failed["session_id"] == "session_1"
    assert failed["run_id"] == "run_1"
    assert failed["error"] == {
        "type": "RuntimeErrorInfo",
        "message": "Agent loop crashed",
        "code": "agent.loop_failed",
        "category": "internal",
    }
    await service.close()


@pytest.mark.asyncio
async def test_preflight_failure_is_a_localized_terminal_event_not_an_http_error(
    tmp_path: Path,
):
    service = DesktopV2Service(tmp_path)
    request = DesktopRunRequest(
        agent_id="missing_agent",
        messages=[RunMessage(role="user", text="开始")],
        response_language="zh-CN",
        idempotency_key="preflight-localized-failure",
    )

    frames = [
        json.loads(value) async for value in service.run_events(request, "user_1")
    ]

    assert frames[0]["kind"] == "stream.opened"
    failed = next(value for value in frames if value.get("type") == "run.failed")
    error = failed["data"]["error"]
    assert error["code"] == "desktop.run_start_failed"
    assert error["message"] == "部分信息无效，无法处理该请求。"
    assert error["message_key"] == "error.validation"
    assert error["metadata"]["response_language"] == "zh"
    assert "diagnostic_message" in error["metadata"]
    await service.close()


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
    assert not any(
        plugin["plugin_id"] == "native-mcp"
        for component in inventory
        for plugin in component["plugins"]
    )
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
    assert by_name["file_read"]["category"] == "files"
    assert by_name["file_read"]["source"] == "文件"
    assert by_name["grep"]["category"] == "code_search"
    assert by_name["grep"]["source"] == "代码检索"
    assert by_name["execute_shell_command"]["category"] == "shell"
    assert by_name["execute_shell_command"]["source"] == "终端"
    await service.session_store.close()


@pytest.mark.asyncio
async def test_native_tool_catalog_localizes_descriptions_and_schema(tmp_path: Path):
    service = DesktopV2Service(tmp_path)

    zh_catalog = {
        value["name"]: value
        for value in await service.list_tools("user_1", language="zh-CN")
    }
    en_catalog = {
        value["name"]: value
        for value in await service.list_tools("user_1", language="en-US")
    }

    assert zh_catalog["file_read"]["description"].startswith("读取文本文件")
    assert (
        zh_catalog["file_read"]["input_schema"]["properties"]["file_path"][
            "description"
        ]
        == "文件虚拟路径"
    )
    assert en_catalog["file_read"]["description"].startswith("Read text")
    assert (
        en_catalog["file_read"]["input_schema"]["properties"]["file_path"][
            "description"
        ]
        == "Virtual path to the file"
    )
    await service.session_store.close()


@pytest.mark.asyncio
async def test_user_component_selection_is_persisted_with_apply_semantics(
    tmp_path: Path,
):
    service = DesktopV2Service(tmp_path)
    selection = await service.select_component(
        "context.reducer",
        ComponentSelectionRequest(plugin_id="sage.context.reducer.window"),
        "user_1",
    )

    assert selection["plugin_id"] == "sage.context.reducer.window"
    assert selection["pending_restart"] is False
    settings = await service.get_settings()
    assert settings.component_selections == {
        "context.reducer": "sage.context.reducer.window",
    }
    inventory = await service.component_inventory("user_1")
    reducer = next(
        value
        for value in inventory
        if value["component"]["component_id"] == "context.reducer"
    )
    assert reducer["active"]["plugin_id"] == "sage.context.reducer.window"
    await service.session_store.close()


@pytest.mark.asyncio
async def test_tool_selection_component_keeps_only_the_builtin_count_limit(
    tmp_path: Path,
):
    service = DesktopV2Service(tmp_path)
    config = {
        "direct_tool_count_threshold": 10,
        "max_visible_tools": 20,
        "max_tool_schema_tokens": 4096,
        "candidate_top_k": 12,
        "context_turns": 3,
        "max_tool_index_entries": 64,
        "max_tool_index_tokens": 1000,
        "tool_index_description_chars": 72,
        "expansion_batch_limit": 4,
        "max_expanded_tools_per_run": 16,
    }

    selection = await service.select_component(
        "tool.selection-policy",
        ComponentSelectionRequest(
            plugin_id="sage.tool-selection.lexical", config=config
        ),
        "user_1",
    )

    assert selection["plugin_id"] == "sage.tool-selection.lexical"
    assert selection["pending_restart"] is False
    assert selection["config"] == {"max_visible_tools": 20}
    settings = await service.get_settings()
    assert settings.component_selections["tool.selection-policy"] == (
        "sage.tool-selection.lexical"
    )
    assert settings.component_configs["tool.selection-policy"] == selection["config"]
    inventory = await service.component_inventory("user_1")
    component = next(
        value
        for value in inventory
        if value["component"]["component_id"] == "tool.selection-policy"
    )
    assert component["active"]["plugin_id"] == "sage.tool-selection.lexical"
    assert component["active"]["config"] == selection["config"]

    await service.list_agents("user_1")
    await service.patch_model_provider(
        "model_main", ModelProviderPatch(api_keys=["test-key"]), "user_1"
    )
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
    assert loop.tool_selection_policy.plugin_id == "sage.tool-selection.lexical"
    assert loop.tool_selection_policy.config.max_visible_tools == 20
    await sandbox.close()
    await service.close()


@pytest.mark.asyncio
async def test_hybrid_is_not_selectable_and_explicit_status_builds_real_policy(
    tmp_path: Path,
):
    service = DesktopV2Service(tmp_path)
    with pytest.raises(ValueError, match="not user selectable"):
        await service.select_component(
            "agent.continuation-policy",
            ComponentSelectionRequest(plugin_id="sage.agent.continuation.hybrid"),
            "user_1",
        )
    await service.select_component(
        "agent.continuation-policy",
        ComponentSelectionRequest(plugin_id="sage.agent.continuation.explicit-status"),
        "user_1",
    )
    await service.list_agents("user_1")
    await service.patch_model_provider(
        "model_main", ModelProviderPatch(api_keys=["test-key"]), "user_1"
    )
    agent = await service._agent("sage", "user_1")
    provider = await service._provider(agent, "user_1")
    workspace = await service.workspace_root(None, "sage")

    _, explicit_loop, explicit_sandbox = await service._build_loop(
        agent=agent,
        provider=provider,
        workspace=workspace,
        preferred_skills=(),
        approval_mode="high_risk",
    )
    assert isinstance(
        explicit_loop.continuation_policy, ExplicitStatusContinuationPolicy
    )
    segments = await explicit_loop.context_assembler.providers[0].segments(
        StartRun(
            agent_id="sage",
            input=(InputItem(role="user", content=(TextBlock(text="test"),)),),
            resolved_spec_hash="sha256:test",
            idempotency_key="explicit-context",
        ),
        run_id="run_explicit",
    )
    assert "explicit turn status is required" in segments[0].content
    await explicit_sandbox.close()
    await service.close()


@pytest.mark.asyncio
async def test_llm_judge_selection_uses_v1_contract_and_hides_turn_status(
    tmp_path: Path,
):
    service = DesktopV2Service(tmp_path)
    fast_provider = await service.create_model_provider(
        ModelProviderCreate(
            name="Fast Judge",
            protocol="openai-chat-completions",
            model="judge-fast",
            base_url="https://judge.test/v1",
            api_keys=["judge-key"],
        ),
        "user_1",
    )
    await service.select_component(
        "agent.continuation-policy",
        ComponentSelectionRequest(plugin_id="sage.agent.continuation.llm-judge"),
        "user_1",
    )
    await service.list_agents("user_1")
    await service.patch_model_provider(
        "model_main", ModelProviderPatch(api_keys=["test-key"]), "user_1"
    )
    await service.patch_agent_settings(
        "sage",
        AgentSettingsPatch(
            fast_llm_provider_id=fast_provider["id"],
            deep_thinking=True,
            thinking_level="high",
        ),
        "user_1",
    )
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
    inventory = await service.component_inventory("user_1")
    component = next(
        value
        for value in inventory
        if value["component"]["component_id"] == "agent.continuation-policy"
    )
    tools = await loop.tool_catalog.list_tools(run_id="pending")

    assert isinstance(loop.continuation_policy, LLMJudgeContinuationPolicy)
    assert loop.continuation_policy.judge.model.provider_metadata == {
        "agent_id": "sage",
        "provider_id": fast_provider["id"],
        "protocol": "openai-chat-completions",
        "base_url": "https://judge.test/v1",
        "model": "judge-fast",
        "purpose": "task_complete_judge",
        "model_type": "fast",
    }
    assert loop.model.provider.config.reasoning_effort == "high"
    assert loop.continuation_policy.judge.model.provider.config.reasoning_effort is None
    assert loop.continuation_policy.judge.model.provider.config.extra_body == {
        "chat_template_kwargs": {"enable_thinking": False},
        "enable_thinking": False,
        "thinking": {"type": "disabled"},
    }
    assert component["active"]["config"] == {
        "repeat_threshold": 3,
        "status_source": "none",
        "explicit_statuses": [],
        "flow_boundaries": ["complete_node", "continue_node"],
        "uses_finish_reason": False,
        "mode": "llm_judge",
        "model_binding": "fast",
        "prompt_contract": "v1",
        "decisions": [
            "continue",
            "completed",
            "need_user_input",
            "blocked",
        ],
        "uses_confidence": False,
        "uses_llm_judge": True,
        "judge_failure": "continue",
    }
    assert "turn_status" not in {tool.name for tool in tools}

    await sandbox.close()
    await service.close()


@pytest.mark.asyncio
async def test_memory_provider_selection_applies_on_restart(tmp_path: Path):
    service = DesktopV2Service(tmp_path)

    selection = await service.select_component(
        "memory.provider",
        ComponentSelectionRequest(plugin_id="sage.memory.noop"),
        "user_1",
    )
    inventory = await service.component_inventory("user_1")
    memory = next(
        value
        for value in inventory
        if value["component"]["component_id"] == "memory.provider"
    )

    assert selection["pending_restart"] is True
    assert memory["active"]["plugin_id"] == "sage.memory.filesystem-bm25"
    assert memory["active"]["selected_plugin_id"] == "sage.memory.noop"
    assert memory["active"]["pending_restart"] is True
    await service.close()

    reopened = DesktopV2Service(tmp_path)
    inventory = await reopened.component_inventory("user_1")
    memory = next(
        value
        for value in inventory
        if value["component"]["component_id"] == "memory.provider"
    )
    assert reopened.memory_plugin_id == "sage.memory.noop"
    assert memory["active"]["plugin_id"] == "sage.memory.noop"
    assert memory["active"]["config"]["recall"] is False
    assert memory["active"]["config"]["auto_write"] is False
    assert memory["active"]["pending_restart"] is False
    await reopened.close()


@pytest.mark.asyncio
async def test_create_agent_uses_independent_runnable_defaults(
    tmp_path: Path,
):
    service = DesktopV2Service(tmp_path)
    created = await service.create_agent(
        AgentCreate(name="Research"),
        "user_1",
    )

    assert created["id"] != "sage"
    assert created["name"] == "Research"
    assert created["llm_provider_id"] == "model_main"
    assert created["fast_llm_provider_id"] == "model_main"
    assert created["agent_mode"] == "simple"
    assert created["max_loop_count"] == 48
    assert created["available_tools"]
    assert created["available_skills"] == []
    assert created["is_default"] is False
    assert {value["id"] for value in await service.list_agents("user_1")} == {
        "sage",
        created["id"],
    }
    await service.session_store.close()


@pytest.mark.asyncio
async def test_agent_settings_patch_persists_frozen_record_and_assignments(
    tmp_path: Path,
):
    data_root = tmp_path / "data"
    skill_source = tmp_path / "skill-source"
    skill_source.mkdir()
    (skill_source / "SKILL.md").write_text(
        "---\nname: review\ndescription: Review code\n---\n# Review\n",
        encoding="utf-8",
    )
    service = DesktopV2Service(data_root)
    await service.list_agents("user_1")
    await service.import_skill_folder(str(skill_source), "user_1")

    updated = await service.patch_agent_settings(
        "sage",
        AgentSettingsPatch(
            name="  Configured Sage  ",
            description="Configured from Desktop v2",
            llm_provider_id="model_main",
            agent_mode="team",
            max_loop_count=64,
            deep_thinking=True,
            thinking_level="high",
            runtime_variables={
                "language": "zh",
                "preferences": {"concise": True},
            },
            available_tools=["todo_write", "file_read", "file_read"],
            available_skills=["review", "review"],
            approved_shell_commands=[
                " git clean -fd ",
                "git reset --hard HEAD~1",
                "git clean -fd",
            ],
        ),
        "user_1",
    )

    assert updated["name"] == "Configured Sage"
    assert updated["description"] == "Configured from Desktop v2"
    assert updated["agent_mode"] == "team"
    assert updated["max_loop_count"] == 64
    assert updated["deep_thinking"] is True
    assert updated["thinking_level"] == "high"
    assert updated["runtime_variables"] == {
        "language": "zh",
        "preferences": {"concise": True},
    }
    assert updated["system_context"] == updated["runtime_variables"]
    assert updated["available_tools"] == ["file_read", "todo_write"]
    assert updated["available_skills"] == ["review"]
    assert updated["approved_shell_commands"] == [
        "git clean -fd",
        "git reset --hard HEAD~1",
    ]
    assert (
        updated["shell_policy"]["user_approved_commands"]
        == updated["approved_shell_commands"]
    )
    assert "git reset --hard" in updated["shell_policy"]["approval_keywords"]
    persisted = await service._agent("sage", "user_1")
    assert persisted.name == "Configured Sage"
    assert persisted.config["availableTools"] == ["file_read", "todo_write"]
    assert persisted.config["availableSkills"] == ["review"]
    assert persisted.config["systemContext"] == updated["runtime_variables"]
    await service.session_store.close()

    reopened = DesktopV2Service(data_root)
    restored = await reopened.get_agent_settings("sage", "user_1")
    assert restored["name"] == "Configured Sage"
    assert restored["available_tools"] == ["file_read", "todo_write"]
    assert restored["available_skills"] == ["review"]
    assert restored["approved_shell_commands"] == updated["approved_shell_commands"]
    assert restored["runtime_variables"] == updated["runtime_variables"]
    await reopened.session_store.close()


@pytest.mark.asyncio
async def test_team_member_assignments_are_validated_and_persisted(tmp_path: Path):
    service = DesktopV2Service(tmp_path)
    await service.list_agents("user_1")
    research = await service.create_agent(AgentCreate(name="Research"), "user_1")
    review = await service.create_agent(AgentCreate(name="Review"), "user_1")

    updated = await service.patch_agent_settings(
        "sage",
        AgentSettingsPatch(
            agent_mode="team",
            sub_agent_selection_mode="manual",
            available_sub_agent_ids=[review["id"], review["id"]],
        ),
        "user_1",
    )

    assert updated["sub_agent_selection_mode"] == "manual"
    assert updated["available_sub_agent_ids"] == [review["id"]]
    assert research["id"] not in updated["available_sub_agent_ids"]

    with pytest.raises(ValueError, match="cannot include itself"):
        await service.patch_agent_settings(
            "sage",
            AgentSettingsPatch(available_sub_agent_ids=["sage"]),
            "user_1",
        )
    with pytest.raises(ValueError, match="unknown sub-agents"):
        await service.patch_agent_settings(
            "sage",
            AgentSettingsPatch(available_sub_agent_ids=["missing"]),
            "user_1",
        )
    await service.close()


@pytest.mark.asyncio
async def test_agent_settings_accepts_legacy_system_context_alias(tmp_path: Path):
    service = DesktopV2Service(tmp_path)

    updated = await service.patch_agent_settings(
        "sage",
        AgentSettingsPatch(system_context={"legacy": True}),
        "user_1",
    )

    assert updated["runtime_variables"] == {"legacy": True}
    assert updated["system_context"] == updated["runtime_variables"]
    await service.session_store.close()


@pytest.mark.asyncio
async def test_shell_approval_can_be_remembered_in_agent_settings(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    service = DesktopV2Service(tmp_path)
    await service.list_agents("user_1")
    monkeypatch.setattr(
        service.session_store,
        "get_start_command",
        AsyncMock(return_value=SimpleNamespace(agent_id="sage")),
    )
    interaction = SimpleNamespace(
        allowed_decisions=(
            "approve_once",
            "approve_and_remember",
            "deny",
            "cancel",
        ),
        payload={
            "tool_name": "execute_shell_command",
            "arguments": {"command": " git reset --hard HEAD~1 "},
        },
    )

    remembered = await service._remember_approved_shell_command(
        run_id="run_1",
        interaction=interaction,
        user_id="user_1",
    )

    settings = await service.get_agent_settings("sage", "user_1")
    assert remembered == "git reset --hard HEAD~1"
    assert settings["approved_shell_commands"] == [remembered]
    assert settings["shell_policy"]["user_approved_commands"] == [remembered]
    await service.session_store.close()


@pytest.mark.asyncio
async def test_agent_assignment_patch_rejects_unknown_and_blank_names(tmp_path: Path):
    service = DesktopV2Service(tmp_path)
    await service.list_agents("user_1")

    with pytest.raises(ValueError, match="unknown tools: made_up_tool"):
        await service.patch_agent_settings(
            "sage",
            AgentSettingsPatch(available_tools=["made_up_tool"]),
            "user_1",
        )
    with pytest.raises(ValueError, match="tool names cannot be empty"):
        await service.patch_agent_settings(
            "sage",
            AgentSettingsPatch(available_tools=[""]),
            "user_1",
        )
    with pytest.raises(ValueError, match="unknown skills: made-up-skill"):
        await service.patch_agent_settings(
            "sage",
            AgentSettingsPatch(available_skills=["made-up-skill"]),
            "user_1",
        )
    await service.session_store.close()


@pytest.mark.asyncio
async def test_unavailable_mcp_does_not_block_native_tool_configuration(tmp_path: Path):
    service = DesktopV2Service(tmp_path)
    await service.list_agents("user_1")
    await service.catalog.save_mcp(
        DesktopMcpRecord(
            user_id="user_1",
            name="offline",
            protocol="stdio",
            command="sage-command-that-does-not-exist",
        )
    )

    catalog = await service.list_tools("user_1")
    assert "file_read" in {value["name"] for value in catalog}
    updated = await service.patch_agent_settings(
        "sage",
        AgentSettingsPatch(available_tools=["file_read", "todo_write"]),
        "user_1",
    )
    assert updated["available_tools"] == ["file_read", "todo_write"]
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
async def test_standalone_workspace_tree_includes_claw_seed_and_user_content(
    tmp_path: Path,
):
    service = DesktopV2Service(tmp_path / "data")
    root = await service.workspace_root(None, "sage")
    (root / "projects" / "demo").mkdir()
    (root / "projects" / "demo" / "index.html").write_text(
        "<h1>Demo</h1>", encoding="utf-8"
    )

    tree = await service.workspace_tree(None, "sage")
    by_name = {value["name"]: value for value in tree}

    assert {
        "AGENT.md",
        "IDENTITY.md",
        "SOUL.md",
        "USER.md",
        "MEMORY.md",
        "data",
        "logs",
        "memory",
        "projects",
        "temp",
    } <= set(by_name)
    demo = next(
        value for value in by_name["projects"]["children"] if value["name"] == "demo"
    )
    assert [value["path"] for value in demo["children"]] == ["projects/demo/index.html"]
    await service.session_store.close()


@pytest.mark.asyncio
async def test_agent_workspace_uses_the_selected_initializer_plugin(tmp_path: Path):
    service = DesktopV2Service(tmp_path / "data")
    await service.save_settings(
        DesktopV2Settings(
            component_selections={
                "workspace.initializer": "sage.workspace.initializer.bare"
            }
        )
    )

    root = await service.workspace_root(None, "sage")

    assert list(root.iterdir()) == []
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
    seeded_agent = await service._agent("sage", "user_1")
    await service.patch_agent_settings(
        "sage",
        AgentSettingsPatch(
            available_tools=[
                *seeded_agent.config.get("availableTools", ()),
                "search_memory",
            ]
        ),
        "user_1",
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
    assert loop.automatic_memory_recall is True
    assert isinstance(
        loop.memory_recall_query_generator, DirectMemoryRecallQueryGenerator
    )
    assert {"file_read", "execute_shell_command", "todo_write", "load_skill"} <= names
    await sandbox.close()
    await service.session_store.close()


@pytest.mark.asyncio
async def test_desktop_search_memory_assignment_controls_automatic_recall(
    tmp_path: Path,
):
    service = DesktopV2Service(tmp_path)
    await service.list_agents("user_1")
    await service.patch_model_provider(
        "model_main", ModelProviderPatch(api_keys=["test-key"]), "user_1"
    )
    await service.patch_agent_settings(
        "sage",
        AgentSettingsPatch(available_tools=["file_read"]),
        "user_1",
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

    assert resolved.agents["sage"].memory.recall is False
    assert resolved.agents["sage"].memory.auto_write is False
    assert loop.automatic_memory_recall is False
    await sandbox.close()
    await service.close()


@pytest.mark.asyncio
async def test_desktop_memory_recall_query_plugin_selects_llm_generator(tmp_path: Path):
    service = DesktopV2Service(tmp_path)
    await service.select_component(
        "memory.recall-query",
        ComponentSelectionRequest(plugin_id="sage.memory.recall-query.llm"),
        "user_1",
    )
    await service.list_agents("user_1")
    await service.patch_model_provider(
        "model_main", ModelProviderPatch(api_keys=["test-key"]), "user_1"
    )
    seeded = await service._agent("sage", "user_1")
    await service.patch_agent_settings(
        "sage",
        AgentSettingsPatch(
            available_tools=[
                *seeded.config.get("availableTools", ()),
                "search_memory",
            ]
        ),
        "user_1",
    )
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

    assert loop.automatic_memory_recall is True
    assert isinstance(loop.memory_recall_query_generator, LLMMemoryRecallQueryGenerator)
    await sandbox.close()
    await service.close()


@pytest.mark.asyncio
async def test_sandbox_workspace_root_is_generic_run_configuration(tmp_path: Path):
    service = DesktopV2Service(tmp_path)
    settings = await service.get_settings()
    await service.save_settings(
        settings.model_copy(
            update={
                "component_configs": {
                    "execution.sandbox": {
                        "workspace_root": "/project",
                        "workspace_mapping": "active_workspace",
                        "filesystem_mode": "workspace",
                    }
                }
            }
        )
    )
    await service.list_agents("user_1")
    await service.patch_model_provider(
        "model_main", ModelProviderPatch(api_keys=["test-key"]), "user_1"
    )
    agent = await service._agent("sage", "user_1")
    provider = await service._provider(agent, "user_1")
    workspace = await service.workspace_root(None, "sage")

    resolved, _, sandbox = await service._build_loop(
        agent=agent,
        provider=provider,
        workspace=workspace,
        preferred_skills=(),
        approval_mode="high_risk",
    )
    command = service._command(
        DesktopRunRequest(
            agent_id="sage", messages=[RunMessage(role="user", text="hello")]
        ),
        resolved,
        agent=agent,
        workspace=workspace,
    )
    uploaded = await service.upload(None, "sage", "note.txt", b"hello")

    assert sandbox.filesystem.normalize_path("note.txt") == "/project/note.txt"
    assert command.config.metadata["working_directory"] == "/project"
    assert command.config.metadata["workspace_files"].startswith(
        "Working directory: /project\n"
    )
    assert uploaded["virtual_path"] == "/project/uploads/note.txt"
    await sandbox.close()
    await service.session_store.close()


@pytest.mark.asyncio
async def test_plan_mode_is_a_read_only_run_contract(tmp_path: Path):
    service = DesktopV2Service(tmp_path)
    await service.list_agents("user_1")
    member = await service.create_agent(AgentCreate(name="Research"), "user_1")
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
        invocation_mode="plan",
    )
    command = service._command(
        DesktopRunRequest(
            agent_id="sage",
            messages=[RunMessage(role="user", text="plan this change")],
            invocation_mode="plan",
        ),
        resolved,
        agent=agent,
        workspace=workspace,
    )

    assert "file_read" in command.config.enabled_tools
    assert "todo_write" in command.config.enabled_tools
    assert "file_write" in command.config.enabled_tools
    assert "execute_shell_command" in command.config.enabled_tools
    assert "goal_submit" in command.config.enabled_tools
    roster = next(
        value
        for value in loop.context_assembler.providers
        if isinstance(value, AgentRosterContextProvider)
    )
    member_descriptor = next(
        value
        for value in await roster.registry.list()
        if value.agent_id == member["id"]
    )
    assert "file_read" in member_descriptor.tools
    assert "file_write" in member_descriptor.tools
    assert "execute_shell_command" in member_descriptor.tools
    assert command.config.metadata["invocation_mode"] == "plan"
    assert command.invocation_mode == "plan"
    await sandbox.close()
    await service.session_store.close()


@pytest.mark.asyncio
async def test_goal_mode_requires_goal_complete_after_rechecking(tmp_path: Path):
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
        invocation_mode="goal",
    )

    def assert_active_goal(request):
        system = "\n".join(
            block.text
            for message in request.messages
            if message.role in {"system", "developer"}
            for block in message.content
            if isinstance(block, TextBlock)
        )
        assert "<active_goal>" in system
        assert "Ship the verified change" in system

    loop.model = ScriptedModelProvider(
        (
            ScriptedModelStep(
                events=(
                    ModelStreamEvent(
                        kind=ModelEventKind.COMPLETED,
                        response=ModelResponse(
                            response_id="goal_submit_response",
                            text="I established the goal.",
                            tool_calls=(
                                ModelToolCall(
                                    tool_call_id="goal_submit_call",
                                    name="goal_submit",
                                    arguments={
                                        "content": "Ship the verified change",
                                    },
                                ),
                            ),
                            finish_reason="tool_calls",
                        ),
                    ),
                )
            ),
            ScriptedModelStep(
                assertion=assert_active_goal,
                events=(
                    ModelStreamEvent(
                        kind=ModelEventKind.COMPLETED,
                        response=ModelResponse(
                            response_id="premature_goal_response",
                            text="I think the goal is done.",
                            finish_reason="stop",
                        ),
                    ),
                ),
            ),
            ScriptedModelStep(
                events=(
                    ModelStreamEvent(
                        kind=ModelEventKind.COMPLETED,
                        response=ModelResponse(
                            response_id="goal_complete_response",
                            text="The tests pass and the goal is complete.",
                            tool_calls=(
                                ModelToolCall(
                                    tool_call_id="goal_complete_call",
                                    name="goal_complete",
                                    arguments={
                                        "summary": "All acceptance checks pass."
                                    },
                                ),
                            ),
                            finish_reason="tool_calls",
                        ),
                    ),
                )
            ),
        )
    )
    handle = await service.runtime.start_run(
        StartRun(
            agent_id="sage",
            input=(InputItem(role="user", content=(TextBlock(text="Do it"),)),),
            resolved_spec_hash=resolved.manifest_hash,
            idempotency_key="desktop-goal-mode",
            invocation_mode="goal",
        ),
        service._context("user_1"),
    )

    result = await loop.execute(handle.run_id, service._context("user_1"))
    events = await service.session_store.read_events(handle.run_id)
    decisions = [
        event.data.reason_code
        for event in events
        if event.type == "continuation.decided"
    ]

    assert result.state.value == "completed"
    assert decisions.count("goal.incomplete") == 2
    assert decisions[-1] == "goal.complete"
    await sandbox.close()
    await service.close()


@pytest.mark.asyncio
async def test_confirmed_plan_becomes_the_goal_system_context(tmp_path: Path):
    service = DesktopV2Service(tmp_path)
    await service.list_agents("user_1")
    await service.patch_model_provider(
        "model_main", ModelProviderPatch(api_keys=["test-key"]), "user_1"
    )
    agent = await service._agent("sage", "user_1")
    provider = await service._provider(agent, "user_1")
    workspace = await service.workspace_root(None, "sage")

    plan_resolved, plan_loop, plan_sandbox = await service._build_loop(
        agent=agent,
        provider=provider,
        workspace=workspace,
        preferred_skills=(),
        approval_mode="high_risk",
        invocation_mode="plan",
    )
    plan_loop.model = ScriptedModelProvider(
        (
            ScriptedModelStep(
                events=(
                    ModelStreamEvent(
                        kind=ModelEventKind.COMPLETED,
                        response=ModelResponse(
                            response_id="plan_response",
                            text="",
                            tool_calls=(
                                ModelToolCall(
                                    tool_call_id="submit_plan",
                                    name="goal_submit",
                                    arguments={
                                        "content": "1. Update the implementation.\n2. Run the tests."
                                    },
                                ),
                            ),
                            finish_reason="tool_calls",
                        ),
                    ),
                )
            ),
            ScriptedModelStep(
                events=(
                    ModelStreamEvent(
                        kind=ModelEventKind.COMPLETED,
                        response=ModelResponse(
                            response_id="plan_approved",
                            text="The approved Plan has been saved.",
                            finish_reason="stop",
                        ),
                    ),
                )
            ),
        )
    )
    plan_handle = await service.runtime.start_run(
        StartRun(
            agent_id="sage",
            input=(InputItem(role="user", content=(TextBlock(text="Plan it"),)),),
            resolved_spec_hash=plan_resolved.manifest_hash,
            idempotency_key="desktop-plan-before-goal",
            invocation_mode="plan",
        ),
        service._context("user_1"),
    )
    suspended_plan = await plan_loop.execute(
        plan_handle.run_id, service._context("user_1")
    )
    assert suspended_plan.state.value == "suspended"
    suspension = await service.session_store.get_suspension(
        suspended_plan.suspension_id
    )
    interaction = await service.session_store.get_interaction(suspension.interaction_id)
    assert interaction.payload["tool_name"] == "goal_submit"
    assert "Update the implementation" in interaction.payload["arguments"]["content"]
    await service.runtime.reply_interaction(
        ReplyInteraction(
            run_id=plan_handle.run_id,
            suspension_id=suspension.suspension_id,
            interaction_id=interaction.interaction_id,
            expected_revision=suspended_plan.revision,
            expected_suspension_revision=suspension.expected_revision,
            expected_interaction_revision=interaction.expected_revision,
            decision="approve_once",
            idempotency_key="approve-plan",
        ),
        service._context("user_1"),
    )
    plan_result = await plan_loop.resume(plan_handle.run_id, service._context("user_1"))
    assert plan_result.state.value == "completed"
    await plan_sandbox.close()

    goal_resolved, goal_loop, goal_sandbox = await service._build_loop(
        agent=agent,
        provider=provider,
        workspace=workspace,
        preferred_skills=(),
        approval_mode="high_risk",
        invocation_mode="goal",
    )

    def assert_confirmed_plan(request):
        system = "\n".join(
            block.text
            for message in request.messages
            if message.role in {"system", "developer"}
            for block in message.content
            if isinstance(block, TextBlock)
        )
        assert "<active_goal>" in system
        assert "<source>plan</source>" in system
        assert "Update the implementation" in system

    goal_loop.model = ScriptedModelProvider(
        (
            ScriptedModelStep(
                assertion=assert_confirmed_plan,
                events=(
                    ModelStreamEvent(
                        kind=ModelEventKind.COMPLETED,
                        response=ModelResponse(
                            response_id="confirmed_plan_complete",
                            text="The confirmed plan was executed and verified.",
                            tool_calls=(
                                ModelToolCall(
                                    tool_call_id="confirmed_plan_goal_complete",
                                    name="goal_complete",
                                    arguments={
                                        "summary": "The plan and checks passed."
                                    },
                                ),
                            ),
                            finish_reason="tool_calls",
                        ),
                    ),
                ),
            ),
        )
    )
    goal_handle = await service.runtime.start_run(
        StartRun(
            session_id=plan_handle.session_id,
            agent_id="sage",
            input=(InputItem(role="user", content=(TextBlock(text="Execute it"),)),),
            resolved_spec_hash=goal_resolved.manifest_hash,
            idempotency_key="desktop-confirm-plan",
            invocation_mode="goal",
        ),
        service._context("user_1"),
    )

    goal_result = await goal_loop.execute(
        goal_handle.run_id, service._context("user_1")
    )
    goal_events = await service.session_store.read_events(goal_handle.run_id)
    terminal = await service.session_store.get_run_result(goal_handle.run_id)

    assert goal_result.state.value == "completed", (terminal.error, goal_events)
    assert any(
        event.type == "tool.call.succeeded" and event.data.tool_name == "goal_complete"
        for event in goal_events
    )
    assert not any(
        event.type == "tool.call.succeeded" and event.data.tool_name == "goal_submit"
        for event in goal_events
    )
    await goal_sandbox.close()
    await service.close()


@pytest.mark.asyncio
async def test_sandbox_workspace_path_can_match_the_real_workspace(tmp_path: Path):
    service = DesktopV2Service(tmp_path)
    settings = await service.get_settings()
    await service.save_settings(
        settings.model_copy(
            update={
                "component_configs": {
                    "execution.sandbox": {
                        "workspace_root": "/workspace",
                        "workspace_path_mode": "host",
                        "workspace_mapping": "active_workspace",
                        "filesystem_mode": "workspace",
                    }
                }
            }
        )
    )
    await service.list_agents("user_1")
    await service.patch_model_provider(
        "model_main", ModelProviderPatch(api_keys=["test-key"]), "user_1"
    )
    agent = await service._agent("sage", "user_1")
    provider = await service._provider(agent, "user_1")
    workspace = await service.workspace_root(None, "sage")
    real_root = workspace.resolve().as_posix()

    resolved, _, sandbox = await service._build_loop(
        agent=agent,
        provider=provider,
        workspace=workspace,
        preferred_skills=(),
        approval_mode="high_risk",
    )
    command = service._command(
        DesktopRunRequest(
            agent_id="sage", messages=[RunMessage(role="user", text="hello")]
        ),
        resolved,
        agent=agent,
        workspace=workspace,
    )
    uploaded = await service.upload(None, "sage", "note.txt", b"hello")

    assert sandbox.filesystem.normalize_path("note.txt") == f"{real_root}/note.txt"
    assert command.config.metadata["working_directory"] == real_root
    assert command.config.metadata["workspace_files"].startswith(
        f"Working directory: {real_root}\n"
    )
    assert uploaded["virtual_path"] == f"{real_root}/uploads/note.txt"
    await sandbox.close()
    await service.session_store.close()


@pytest.mark.asyncio
async def test_isolated_sandbox_rejects_host_workspace_path_mode(tmp_path: Path):
    service = DesktopV2Service(tmp_path)
    settings = await service.get_settings()

    with pytest.raises(ValueError, match="requires a fixed virtual workspace path"):
        await service.save_settings(
            settings.model_copy(
                update={
                    "component_selections": {
                        **settings.component_selections,
                        "execution.sandbox": "sage.sandbox.ephemeral",
                    },
                    "component_configs": {
                        "execution.sandbox": {
                            "workspace_path_mode": "host",
                            "workspace_mapping": "isolated",
                        }
                    },
                }
            )
        )
    await service.session_store.close()


@pytest.mark.asyncio
async def test_sandbox_rejects_provider_incompatible_workspace_mapping(
    tmp_path: Path,
):
    service = DesktopV2Service(tmp_path)
    settings = await service.get_settings()

    with pytest.raises(ValueError, match="requires active_workspace"):
        await service.save_settings(
            settings.model_copy(
                update={
                    "component_configs": {
                        "execution.sandbox": {"workspace_mapping": "isolated"}
                    }
                }
            )
        )
    await service.session_store.close()


@pytest.mark.asyncio
async def test_ephemeral_sandbox_keeps_an_isolated_configured_workspace(
    tmp_path: Path,
):
    service = DesktopV2Service(tmp_path)
    settings = await service.get_settings()
    await service.save_settings(
        settings.model_copy(
            update={
                "component_selections": {
                    **settings.component_selections,
                    "execution.sandbox": "sage.sandbox.ephemeral",
                },
                "component_configs": {
                    "execution.sandbox": {
                        "workspace_root": "/sandbox",
                        "workspace_mapping": "isolated",
                        "filesystem_mode": "workspace",
                    }
                },
            }
        )
    )
    await service.list_agents("user_1")
    await service.patch_model_provider(
        "model_main", ModelProviderPatch(api_keys=["test-key"]), "user_1"
    )
    agent = await service._agent("sage", "user_1")
    provider = await service._provider(agent, "user_1")
    workspace = await service.workspace_root(None, "sage")

    resolved, _, sandbox = await service._build_loop(
        agent=agent,
        provider=provider,
        workspace=workspace,
        preferred_skills=(),
        approval_mode="high_risk",
    )
    command = service._command(
        DesktopRunRequest(
            agent_id="sage", messages=[RunMessage(role="user", text="hello")]
        ),
        resolved,
        agent=agent,
        workspace=workspace,
    )

    assert sandbox.filesystem.normalize_path(".") == "/sandbox"
    with pytest.raises(PermissionError, match="outside"):
        sandbox.filesystem.normalize_path(str(workspace / "AGENT.md"))
    assert command.config.metadata["working_directory"] == "/sandbox"
    assert command.config.metadata["workspace_files"] == (
        "Working directory: /sandbox\n(Empty isolated sandbox)"
    )
    await sandbox.close()
    await service.session_store.close()


@pytest.mark.asyncio
async def test_desktop_turn_status_drives_the_real_continuation_policy(
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
    loop.model = ScriptedModelProvider(
        (
            ScriptedModelStep(
                events=(
                    ModelStreamEvent(
                        kind=ModelEventKind.COMPLETED,
                        response=ModelResponse(
                            response_id="status_response",
                            text="The requested work is complete.",
                            tool_calls=(
                                ModelToolCall(
                                    tool_call_id="status_call",
                                    name="turn_status",
                                    arguments={"status": "task_done", "note": "done"},
                                ),
                            ),
                            finish_reason="tool_calls",
                        ),
                    ),
                )
            ),
        )
    )
    handle = await service.runtime.start_run(
        StartRun(
            agent_id="sage",
            input=(InputItem(role="user", content=(TextBlock(text="Do it"),)),),
            resolved_spec_hash=resolved.manifest_hash,
            idempotency_key="desktop-turn-status",
        ),
        service._context("user_1"),
    )

    result = await loop.execute(handle.run_id, service._context("user_1"))
    events = await service.session_store.read_events(handle.run_id)
    decision = next(event for event in events if event.type == "continuation.decided")

    assert result.state.value == "completed"
    assert decision.data.reason_code == "status.complete"
    assert any(event.type == "tool.call.succeeded" for event in events)
    await sandbox.close()
    await service.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("mode", "present", "absent"),
    [
        (
            "simple",
            set(),
            {"sys_spawn_agent", "sys_delegate_task", "sys_team_delegate_task"},
        ),
        ("fibre", {"sys_spawn_agent", "sys_delegate_task"}, {"sys_team_delegate_task"}),
        ("team", {"sys_team_delegate_task"}, {"sys_spawn_agent", "sys_delegate_task"}),
    ],
)
async def test_desktop_agent_modes_expose_only_their_real_delegation_tools(
    tmp_path: Path,
    mode: str,
    present: set[str],
    absent: set[str],
):
    service = DesktopV2Service(tmp_path / mode)
    await service.list_agents("user_1")
    member = await service.create_agent(AgentCreate(name="Research"), "user_1")
    await service.patch_model_provider(
        "model_main", ModelProviderPatch(api_keys=["test-key"]), "user_1"
    )
    await service.patch_agent_settings(
        "sage", AgentSettingsPatch(agent_mode=mode), "user_1"
    )
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
    names = {value.name for value in await loop.tool_catalog.list_tools(run_id="run")}
    roster = next(
        value
        for value in loop.context_assembler.providers
        if isinstance(value, AgentRosterContextProvider)
    )
    roster_segments = await roster.segments(
        StartRun(
            agent_id="sage",
            input=(InputItem(role="user", content=(TextBlock(text="work"),)),),
            resolved_spec_hash="sha256:roster",
            idempotency_key=f"roster-{mode}",
        )
    )

    assert present <= names
    assert names.isdisjoint(absent)
    if mode == "simple":
        assert roster_segments == ()
    else:
        assert member["id"] in roster_segments[0].content
        assert "Research" in roster_segments[0].content
        assert ("sys_spawn_agent" in roster_segments[0].content) is (mode == "fibre")
        assert ("fixed roster" in roster_segments[0].content) is (mode == "team")
    await sandbox.close()
    await service.close()


@pytest.mark.asyncio
async def test_new_fibre_session_composes_before_authoritative_session_exists(
    tmp_path: Path,
):
    service = DesktopV2Service(tmp_path / "new-fibre-session")
    await service.list_agents("user_1")
    await service.patch_model_provider(
        "model_main", ModelProviderPatch(api_keys=["test-key"]), "user_1"
    )
    await service.patch_agent_settings(
        "sage", AgentSettingsPatch(agent_mode="fibre"), "user_1"
    )
    agent = await service._agent("sage", "user_1")
    provider = await service._provider(agent, "user_1")
    workspace = await service.workspace_root(None, "sage")

    _, loop, sandbox = await service._build_loop(
        agent=agent,
        provider=provider,
        workspace=workspace,
        preferred_skills=(),
        approval_mode="high_risk",
        session_id="session_client_generated",
    )

    names = {value.name for value in await loop.tool_catalog.list_tools(run_id="run")}
    assert {"sys_spawn_agent", "sys_delegate_task"} <= names
    with pytest.raises(SageV2Error) as missing:
        await service.session_store.get_session("session_client_generated")
    assert missing.value.info.code == "session.not_found"
    await sandbox.close()
    await service.close()


@pytest.mark.asyncio
async def test_delegated_fibre_context_declares_a_leaf_execution_boundary():
    roster = AgentRosterContextProvider(
        AgentRegistry(),
        AgentMode.FIBRE,
        allow_delegation=False,
    )

    segments = await roster.segments(
        StartRun(
            agent_id="child",
            input=(InputItem(role="user", content=(TextBlock(text="work"),)),),
            resolved_spec_hash="sha256:leaf-context",
            idempotency_key="leaf-context",
            invocation_mode="delegation",
        )
    )

    assert len(segments) == 1
    assert segments[0].segment_id == "agent_delegation_boundary"
    assert "leaf agent" in segments[0].content
    assert "Do not create, spawn, or delegate" in segments[0].content
    assert "sys_spawn_agent" not in segments[0].content


@pytest.mark.asyncio
async def test_desktop_team_member_executes_as_leaf(tmp_path: Path):
    service = DesktopV2Service(tmp_path / "nested-team")
    await service.list_agents("user_1")
    member = await service.create_agent(AgentCreate(name="Team Lead"), "user_1")
    await service.patch_model_provider(
        "model_main", ModelProviderPatch(api_keys=["test-key"]), "user_1"
    )
    await service.patch_agent_settings(
        member["id"], AgentSettingsPatch(agent_mode="team"), "user_1"
    )
    await service.patch_agent_settings(
        "sage",
        AgentSettingsPatch(
            agent_mode="team",
            sub_agent_selection_mode="manual",
            available_sub_agent_ids=[member["id"]],
        ),
        "user_1",
    )
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
    controller = loop.delegated_run_controller
    assert controller is not None
    descriptor = await controller.descriptor_resolver(member["id"])

    assert descriptor.mode == AgentMode.TEAM
    assert descriptor.allow_delegation is False
    await sandbox.close()
    await service.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["fibre", "team"])
async def test_multi_agent_modes_register_only_manually_selected_members(
    tmp_path: Path, mode: str
):
    service = DesktopV2Service(tmp_path / mode)
    await service.list_agents("user_1")
    research = await service.create_agent(AgentCreate(name="Research"), "user_1")
    review = await service.create_agent(AgentCreate(name="Review"), "user_1")
    await service.patch_model_provider(
        "model_main", ModelProviderPatch(api_keys=["test-key"]), "user_1"
    )
    await service.patch_agent_settings(
        "sage",
        AgentSettingsPatch(
            agent_mode=mode,
            sub_agent_selection_mode="manual",
            available_sub_agent_ids=[review["id"]],
        ),
        "user_1",
    )
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
    roster = next(
        value
        for value in loop.context_assembler.providers
        if isinstance(value, AgentRosterContextProvider)
    )
    roster_segments = await roster.segments(
        StartRun(
            agent_id="sage",
            input=(InputItem(role="user", content=(TextBlock(text="work"),)),),
            resolved_spec_hash="sha256:selected-roster",
            idempotency_key="selected-roster",
        )
    )

    assert review["id"] in roster_segments[0].content
    assert "Review" in roster_segments[0].content
    assert research["id"] not in roster_segments[0].content
    assert "Research" not in roster_segments[0].content
    await sandbox.close()
    await service.close()


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
    agent = agent.model_copy(
        update={
            "config": {
                **agent.config,
                "systemContext": {
                    "response_language": "en-US",
                    "preference": "concise",
                },
            }
        }
    )
    provider = (await service.catalog.list_model_providers("user_1"))[0]
    resolved = service._manifest(agent, provider, ("todo_write",), ())
    resolved = CompositionResolver().resolve(resolved)
    workspace = await service.workspace_root(None, "sage")

    command = service._command(
        DesktopRunRequest(
            agent_id="sage",
            messages=[RunMessage(role="user", text="hello")],
            response_language="zh-CN",
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
    assert metadata["system_context"] == {"preference": "concise"}
    assert metadata["identity_documents"]["SOUL"] == "Be precise"
    assert set(metadata["identity_documents"]) == {
        "AGENT",
        "IDENTITY",
        "SOUL",
        "USER",
        "MEMORY",
    }
    assert metadata["working_directory"] == "/workspace"
    assert (
        datetime.strptime(metadata["current_time"], "%a, %d %b %Y %H:%M:%S %z").tzinfo
        is not None
    )
    assert metadata["workspace_files"].startswith("Working directory: /workspace\n")
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
    assert (
        tmp_path / "runtime" / "sessions" / handle.session_id / "state.json"
    ).is_file()
    assert (tmp_path / "runtime" / ".session-store" / "store.json").is_file()
    assert not (tmp_path / "runtime" / "session-store").exists()

    service.session_index.path.unlink()
    assert await service.list_sessions() == []
    assert (await service.session_store.get_session(handle.session_id)).session_id == (
        handle.session_id
    )
    await service.session_store.close()


@pytest.mark.asyncio
async def test_desktop_session_tree_exposes_child_run_routing_metadata(tmp_path: Path):
    service = DesktopV2Service(tmp_path)
    context = service._context("user_1")
    parent = await service.runtime.start_run(
        StartRun(
            agent_id="sage",
            input=(InputItem(role="user", content=(TextBlock(text="parent"),)),),
            resolved_spec_hash="sha256:test",
            idempotency_key="tree-parent",
        ),
        context,
    )
    child = await service.runtime.start_run(
        StartRun(
            session_id=parent.session_id,
            agent_id="reviewer",
            input=(InputItem(role="user", content=(TextBlock(text="child"),)),),
            config=RunConfig(
                metadata={
                    "task_name": "检查实现",
                    "original_task": "检查快速排序实现",
                    "parent_tool_call_id": "call_delegate_quicksort",
                }
            ),
            session_concurrency_mode=SessionConcurrencyMode.FORK,
            parent_run_id=parent.run_id,
            invocation_mode="delegation",
            resolved_spec_hash="sha256:test",
            idempotency_key="tree-child",
        ),
        context,
    )

    nodes = await service.session_tree(parent.session_id)

    assert len(nodes) == 1
    assert nodes[0]["session"]["session_id"] == child.session_id
    assert nodes[0]["session"]["parent_session_id"] == parent.session_id
    assert nodes[0]["run"]["run_id"] == child.run_id
    assert nodes[0]["parent_run_id"] == parent.run_id
    assert nodes[0]["parent_tool_call_id"] == "call_delegate_quicksort"
    assert nodes[0]["agent_id"] == "reviewer"
    assert nodes[0]["task_name"] == "检查实现"
    assert nodes[0]["original_task"] == "检查快速排序实现"
    stream = service.subscribe_session_tree(parent.session_id)
    discovered = json.loads(await anext(stream))
    child_event = json.loads(await anext(stream))
    assert discovered["kind"] == "session.discovered"
    assert discovered["session"]["session_id"] == child.session_id
    assert discovered["parent_tool_call_id"] == "call_delegate_quicksort"
    assert child_event["kind"] == "session.event"
    assert child_event["session_id"] == child.session_id
    assert child_event["parent_session_id"] == parent.session_id
    assert child_event["run_id"] == child.run_id
    await stream.aclose()
    await service.session_store.close()


@pytest.mark.asyncio
async def test_desktop_parent_delete_removes_descendants_from_index(tmp_path: Path):
    service = DesktopV2Service(tmp_path)
    context = service._context("user_1")
    parent = await service.runtime.start_run(
        StartRun(
            agent_id="sage",
            input=(InputItem(role="user", content=(TextBlock(text="parent"),)),),
            resolved_spec_hash="sha256:test",
            idempotency_key="delete-index-parent",
        ),
        context,
    )
    child = await service.runtime.start_run(
        StartRun(
            session_id=parent.session_id,
            agent_id="sage",
            input=(InputItem(role="user", content=(TextBlock(text="child"),)),),
            session_concurrency_mode=SessionConcurrencyMode.FORK,
            resolved_spec_hash="sha256:test",
            idempotency_key="delete-index-child",
        ),
        context,
    )
    await service._index_session(parent.session_id)
    await service._index_session(child.session_id)

    for handle, key in ((parent, "cancel-parent"), (child, "cancel-child")):
        await service.runtime.cancel_run(
            CancelRun(
                run_id=handle.run_id,
                expected_revision=handle.run_revision,
                idempotency_key=key,
            ),
            context,
        )
    await service.delete_session(parent.session_id)

    # DELETE is idempotent at the Desktop boundary. A stale UI record must still
    # be removable after the authoritative Session plugin has already deleted it.
    await service.delete_session(parent.session_id)

    assert await service.list_sessions() == []
    for session_id in (parent.session_id, child.session_id):
        with pytest.raises(SageV2Error) as missing:
            await service.session_store.get_session(session_id)
        assert missing.value.info.code == "session.not_found"
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
