import asyncio
import json
from types import SimpleNamespace

import pytest

from app.desktop.core.services.browser_tools import BrowserBridgeTool
from sagents.agent.agent_base import AgentBase
from sagents.agent.fibre.tools import FibreTools
from sagents.agent.team.tools import TeamTools
from sagents.skill.skill_tool import SkillTool
from sagents.tool.impl.codebase_tool import CodebaseTool
from sagents.tool.impl.execute_command_tool import ExecuteCommandTool
from sagents.tool.impl.file_system_tool import FileSystemTool
from sagents.tool.impl.image_understanding_tool import ImageUnderstandingTool
from sagents.tool.impl.lint_tool import LintTool
from sagents.tool.impl.memory_tool import MemoryTool
from sagents.tool.impl.questionnaire_tool import QuestionnaireTool
from sagents.tool.impl.todo_tool import ToDoTool
from sagents.tool.impl.tool_expansion_tool import ToolExpansionTool
from sagents.tool.impl.turn_status_tool import TurnStatusTool
from sagents.tool.impl.web_fetcher_tool import WebFetcherTool
from sagents.tool.tool_schema import ToolSpec, convert_spec_to_openai_format
from sagents.tool.tool_manager import ToolManager
from sagents.utils.i18n import MESSAGES, get_tool_language, tool_language


BUILTIN_TOOL_CLASSES = (
    FileSystemTool,
    CodebaseTool,
    ExecuteCommandTool,
    LintTool,
    ToDoTool,
    QuestionnaireTool,
    MemoryTool,
    WebFetcherTool,
    ImageUnderstandingTool,
    ToolExpansionTool,
    TurnStatusTool,
    SkillTool,
    FibreTools,
    TeamTools,
    BrowserBridgeTool,
)


def _specs():
    for cls in BUILTIN_TOOL_CLASSES:
        for value in cls.__dict__.values():
            spec = getattr(value, "_tool_spec", None)
            if spec is not None:
                yield spec


_SCHEMA_LIST_KEYWORDS = ("anyOf", "oneOf", "allOf", "prefixItems")
_SCHEMA_CHILD_KEYWORDS = (
    "additionalProperties",
    "contains",
    "not",
    "if",
    "then",
    "else",
)


def _assert_recursive_i18n(node, path, *, description_required=False):
    if not isinstance(node, dict):
        return
    if description_required:
        assert node.get("description"), path
    if node.get("description"):
        translations = node.get("description_i18n") or {}
        assert all(translations.get(lang) for lang in ("zh", "en", "pt")), path
    for name, child in (node.get("properties") or {}).items():
        _assert_recursive_i18n(child, f"{path}.{name}", description_required=True)
    if isinstance(node.get("items"), dict):
        _assert_recursive_i18n(node["items"], f"{path}[]", description_required=True)
    for keyword in _SCHEMA_LIST_KEYWORDS:
        for index, child in enumerate(node.get(keyword) or []):
            _assert_recursive_i18n(
                child,
                f"{path}.{keyword}[{index}]",
                description_required=True,
            )
    for keyword in _SCHEMA_CHILD_KEYWORDS:
        if isinstance(node.get(keyword), dict):
            _assert_recursive_i18n(
                node[keyword],
                f"{path}.{keyword}",
                description_required=True,
            )


def _assert_exported_schema_is_clean(node, path, language):
    if not isinstance(node, dict):
        return
    assert "description_i18n" not in node, path
    description = node.get("description")
    if description and language == "pt":
        assert not any("\u4e00" <= char <= "\u9fff" for char in description), (
            path,
            description,
        )
    for name, child in (node.get("properties") or {}).items():
        assert child.get("description"), f"{path}.{name}"
        _assert_exported_schema_is_clean(child, f"{path}.{name}", language)
    if isinstance(node.get("items"), dict):
        _assert_exported_schema_is_clean(node["items"], f"{path}[]", language)
    for keyword in _SCHEMA_LIST_KEYWORDS:
        for index, child in enumerate(node.get(keyword) or []):
            _assert_exported_schema_is_clean(
                child, f"{path}.{keyword}[{index}]", language
            )
    for keyword in _SCHEMA_CHILD_KEYWORDS:
        if isinstance(node.get(keyword), dict):
            _assert_exported_schema_is_clean(
                node[keyword], f"{path}.{keyword}", language
            )


def test_all_34_builtin_tools_have_complete_recursive_zh_en_pt_metadata():
    specs = list(_specs())
    assert len(specs) == 34
    names = {spec.name for spec in specs}
    assert "questionnaire" not in names
    assert "questionnaire_async" in names
    assert len(names) == 34

    for spec in specs:
        assert all(spec.description_i18n.get(lang) for lang in ("zh", "en", "pt")), (
            spec.name
        )
        for name, schema in spec.parameters.items():
            _assert_recursive_i18n(
                schema, f"{spec.name}.{name}", description_required=True
            )
        _assert_recursive_i18n(spec.return_data, f"{spec.name}.returns")


@pytest.mark.parametrize("language", ["zh", "en", "pt"])
def test_exported_schema_recursively_localizes_and_removes_internal_metadata(language):
    for spec in _specs():
        exported = convert_spec_to_openai_format(spec, lang=language)["function"]
        _assert_exported_schema_is_clean(
            exported["parameters"], f"{spec.name}.parameters", language
        )
        if "returns" in exported:
            _assert_exported_schema_is_clean(
                exported["returns"], f"{spec.name}.returns", language
            )


def test_portuguese_schema_localizes_anyof_and_nested_return_fields():
    specs = {spec.name: spec for spec in _specs()}
    questionnaire = convert_spec_to_openai_format(specs["questionnaire_async"], lang="pt")[
        "function"
    ]["parameters"]["properties"]
    default_schema = questionnaire["questions"]["items"]["properties"]["default"]
    assert default_schema["anyOf"][0]["description"] == "Valor padrão"

    file_write_returns = convert_spec_to_openai_format(specs["file_write"], lang="pt")[
        "function"
    ]["returns"]["properties"]
    validation = file_write_returns["validation"]["properties"]
    assert validation["enabled"]["description"] == "Se está ativado"
    assert validation["errors"]["description"] == "Erros de validação"


def test_openai_schema_hides_trusted_identity_and_has_no_language_argument():
    for spec in _specs():
        schema = convert_spec_to_openai_format(spec, lang="pt")
        properties = schema["function"]["parameters"]["properties"]
        assert "session_id" not in properties
        assert "user_id" not in properties
        assert "response_language" not in properties


def test_runtime_message_catalog_has_equal_zh_en_pt_key_coverage():
    assert set(MESSAGES["zh"]) == set(MESSAGES["en"]) == set(MESSAGES["pt"])


@pytest.mark.asyncio
async def test_tool_language_context_is_isolated_between_concurrent_tasks():
    ready = asyncio.Event()

    async def observe(language):
        with tool_language(language):
            ready.set()
            await asyncio.sleep(0)
            return get_tool_language()

    first, second, third = await asyncio.gather(
        observe("zh-CN"), observe("en-US"), observe("pt-BR")
    )
    assert (first, second, third) == ("zh", "en", "pt")
    assert get_tool_language() == "en"


@pytest.mark.asyncio
async def test_load_skill_localizes_sage_headings_but_preserves_skill_content(
    monkeypatch,
):
    skill = SimpleNamespace(
        name="demo-skill",
        file_list="- SKILL.md\n- scripts/run.py",
        instructions="KEEP THIS ORIGINAL SKILL TEXT",
    )
    manager = SimpleNamespace(
        skills={"demo-skill": skill}, list_skills=lambda: ["demo-skill"]
    )
    context = SimpleNamespace(
        sandbox_skill_manager=manager,
        sandbox=SimpleNamespace(workspace_path="/sage-workspace"),
        system_context={},
    )
    monkeypatch.setattr(
        "sagents.utils.agent_session_helper.get_live_session",
        lambda *_args, **_kwargs: SimpleNamespace(session_context=context),
    )

    with tool_language("pt-BR"):
        result = await SkillTool().load_skill("demo-skill", session_id="session-1")

    injected = context.system_context["active_skills"][0]["skill_content"]
    assert "Caminho da pasta do skill" in injected
    assert "Estrutura de arquivos" in injected
    assert "Instruções (SKILL.md)" in injected
    assert "KEEP THIS ORIGINAL SKILL TEXT" in injected
    assert "/sage-workspace/skills/demo-skill/" in injected
    assert "carregado com sucesso" in result


@pytest.mark.asyncio
async def test_tool_manager_localizes_common_validation_errors(monkeypatch):
    context = SimpleNamespace(
        get_language=lambda: "pt",
        user_id="user-1",
        system_context={"session_id": "session-1"},
        current_request_id=lambda: None,
    )
    monkeypatch.setattr(
        "sagents.tool.tool_manager._resolve_session_context",
        lambda _session_id: context,
    )
    manager = ToolManager(is_auto_discover=False, isolated=True)
    manager.register_tool(FileSystemTool.file_read._tool_spec)

    result = await manager.run_tool_async("file_read", session_id="session-1")
    payload = json.loads(result)
    assert payload["status"] == "error"
    assert "Parâmetros obrigatórios ausentes" in payload["error"]
    assert payload["required_params"] == ["file_path"]


@pytest.mark.asyncio
async def test_localized_summary_preserves_raw_builtin_payload(monkeypatch):
    async def raw_browser_result():
        return {
            "ok": False,
            "error": "RAW_EXTENSION_ERROR",
            "result": {"page_text": "RAW PAGE CONTENT"},
        }

    context = SimpleNamespace(
        get_language=lambda: "pt",
        user_id="user-1",
        system_context={},
        current_request_id=lambda: None,
    )
    monkeypatch.setattr(
        "sagents.tool.tool_manager._resolve_session_context",
        lambda _session_id: context,
    )
    manager = ToolManager(is_auto_discover=False, isolated=True)
    manager.register_tool(
        ToolSpec(
            name="browser_get_context",
            description="",
            description_i18n={},
            func=raw_browser_result,
            parameters={},
            required=[],
        )
    )

    result = await manager.run_tool_async("browser_get_context", session_id="session-1")
    payload = json.loads(result)
    assert "falhou" in payload["content"]["localized_summary"]
    assert payload["content"]["error"] == "RAW_EXTENSION_ERROR"
    assert payload["content"]["result"]["page_text"] == "RAW PAGE CONTENT"

    base_agent = SimpleNamespace(agent_name="test-agent")
    [tool_message] = AgentBase.process_tool_response(base_agent, result, "tool-call-1")
    model_payload = json.loads(tool_message.content)
    assert "falhou" in model_payload["localized_summary"]
    assert model_payload["error"] == "RAW_EXTENSION_ERROR"
    assert model_payload["result"]["page_text"] == "RAW PAGE CONTENT"
