import asyncio
import importlib.util
import sys
import types
from pathlib import Path
from types import SimpleNamespace


def _load_self_check_agent(monkeypatch):
    def ensure_package(name: str) -> types.ModuleType:
        module = types.ModuleType(name)
        module.__path__ = []
        monkeypatch.setitem(sys.modules, name, module)
        return module

    ensure_package("sagents")
    ensure_package("sagents.agent")
    ensure_package("sagents.context")
    ensure_package("sagents.context.messages")
    ensure_package("sagents.utils")

    message_module = types.ModuleType("sagents.context.messages.message")

    class _EnumValue:
        def __init__(self, value):
            self.value = value

    class MessageRole:
        ASSISTANT = _EnumValue("assistant")
        USER = _EnumValue("user")

    class MessageType:
        OBSERVATION = _EnumValue("observation")
        AGENT_EXECUTION_ERROR = _EnumValue("agent_execution_error")

    class MessageChunk:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    message_module.MessageChunk = MessageChunk  # pyright: ignore[reportAttributeAccessIssue]
    message_module.MessageRole = MessageRole  # pyright: ignore[reportAttributeAccessIssue]
    message_module.MessageType = MessageType  # pyright: ignore[reportAttributeAccessIssue]
    monkeypatch.setitem(sys.modules, "sagents.context.messages.message", message_module)

    session_context_module = types.ModuleType("sagents.context.session_context")
    session_context_module.SessionContext = object  # pyright: ignore[reportAttributeAccessIssue]
    monkeypatch.setitem(
        sys.modules, "sagents.context.session_context", session_context_module
    )

    logger_module = types.ModuleType("sagents.utils.logger")
    logger_module.logger = SimpleNamespace(  # pyright: ignore[reportAttributeAccessIssue]
        info=lambda *args, **kwargs: None, warning=lambda *args, **kwargs: None
    )
    monkeypatch.setitem(sys.modules, "sagents.utils.logger", logger_module)

    agent_base_module = types.ModuleType("sagents.agent.agent_base")

    class AgentBase:
        def __init__(self, *args, **kwargs):
            pass

        def _should_abort_due_to_session(self, session_context):
            return False

        @staticmethod
        def _next_request_runtime_metadata(**extra):
            return {
                "hidden_from_chat": True,
                "hide_from_chat": True,
                "sse_visible": False,
                "llm_scope": "next_request",
                "llm_state": "pending",
                "llm_consumed_by": None,
                "llm_consumed_at": None,
                **extra,
            }

    agent_base_module.AgentBase = AgentBase  # pyright: ignore[reportAttributeAccessIssue]
    monkeypatch.setitem(sys.modules, "sagents.agent.agent_base", agent_base_module)

    repo_root = Path(__file__).resolve().parent.parent.parent
    module_path = repo_root / "sagents" / "agent" / "self_check_agent.py"
    spec = importlib.util.spec_from_file_location(
        "sagents.agent.self_check_agent", module_path
    )
    module = importlib.util.module_from_spec(spec)  # pyright: ignore[reportArgumentType]
    monkeypatch.setitem(sys.modules, "sagents.agent.self_check_agent", module)
    assert spec.loader is not None  # pyright: ignore[reportOptionalMemberAccess]
    spec.loader.exec_module(module)  # pyright: ignore[reportOptionalMemberAccess]
    return module.SelfCheckAgent


def _make_message(role, content):
    return SimpleNamespace(
        role=role,
        content=content,
        tool_calls=[],
        is_user_input_message=lambda: role == "user",
    )


def _assert_hidden_self_check_message(chunk):
    assert chunk.role == "user"
    assert chunk.metadata["hidden_from_chat"] is True
    assert chunk.metadata["hide_from_chat"] is True
    assert chunk.metadata["sse_visible"] is False
    assert chunk.metadata["llm_scope"] == "next_request"
    assert chunk.metadata["llm_state"] == "pending"
    assert chunk.metadata["runtime_diagnostic_source"] == "sage_self_check"


def test_only_latest_assistant_message_is_checked(monkeypatch):
    self_check_agent = _load_self_check_agent(monkeypatch)
    agent = self_check_agent(model=None, model_config={})

    session_context = SimpleNamespace(
        message_manager=SimpleNamespace(
            messages=[
                _make_message("user", "请继续"),
                _make_message("assistant", "[old](file:///tmp/old.md)"),
                _make_message("assistant", "[new](file:///tmp/new.md)"),
            ]
        )
    )

    referenced = agent._collect_recent_referenced_files(session_context)

    assert referenced == {"/tmp/new.md"}


def test_non_absolute_markdown_link_returns_guidance(monkeypatch):
    self_check_agent = _load_self_check_agent(monkeypatch)
    agent = self_check_agent(model=None, model_config={})

    class DummySandbox:
        async def file_exists(self, path):
            return True

        async def read_file(self, path, encoding="utf-8"):
            return ""

    session_context = SimpleNamespace(
        audit_status={},
        sandbox=DummySandbox(),
        message_manager=SimpleNamespace(
            messages=[
                _make_message("user", "请生成结果"),
                _make_message("assistant", "[README.md](README.md)"),
            ]
        ),
    )

    async def collect():
        chunks = []
        async for batch in agent.run_stream(session_context):
            chunks.extend(batch)
        return chunks

    chunks = asyncio.run(collect())

    assert session_context.audit_status["self_check_passed"] is False
    assert "必须使用绝对路径 Markdown 链接" in chunks[0].content
    assert "`README.md`" in chunks[0].content
    _assert_hidden_self_check_message(chunks[0])


def test_self_check_failure_message_uses_english_runtime_diagnostic(monkeypatch):
    self_check_agent = _load_self_check_agent(monkeypatch)
    agent = self_check_agent(model=None, model_config={})

    content = agent._format_failure_message(
        ["File does not exist: output.md"], ["/tmp/output.md"], language="en"
    )

    assert (
        '<runtime_diagnostic source="sage_self_check" generated_by="system">' in content
    )
    assert "not a new user request" in content
    assert "output the complete corrected result again" in content
    assert "Do not reply only that you are preparing to fix it" in content
    assert "complete tag again with valid JSON" in content
    assert "Checked files:" in content


def test_self_check_failure_message_uses_portuguese_runtime_diagnostic(monkeypatch):
    self_check_agent = _load_self_check_agent(monkeypatch)
    agent = self_check_agent(model=None, model_config={})

    content = agent._format_failure_message(
        ["Arquivo nao existe: output.md"], ["/tmp/output.md"], language="pt"
    )

    assert (
        '<runtime_diagnostic source="sage_self_check" generated_by="system">' in content
    )
    assert "nao uma nova solicitacao do usuario" in content
    assert "resultado corrigido completo" in content
    assert "Nao responda apenas que vai preparar a correcao" in content
    assert "tag completa com JSON valido" in content
    assert "Arquivos verificados:" in content


def test_self_check_failure_message_uses_chinese_reoutput_instruction(monkeypatch):
    self_check_agent = _load_self_check_agent(monkeypatch)
    agent = self_check_agent(model=None, model_config={})

    content = agent._format_failure_message(
        ["问卷 JSON 非法"], [], language="zh"
    )

    assert "不是新的用户需求" in content
    assert "重新输出修复后的完整结果" in content
    assert "禁止只回复“准备修复”" in content
    assert "重新输出完整标签" in content
    assert "JSON 合法" in content


def test_absolute_markdown_link_checks_file_existence(monkeypatch):
    self_check_agent = _load_self_check_agent(monkeypatch)
    agent = self_check_agent(model=None, model_config={})

    class MissingSandbox:
        async def file_exists(self, path):
            return False

    session_context = SimpleNamespace(
        audit_status={},
        sandbox=MissingSandbox(),
        message_manager=SimpleNamespace(
            messages=[
                _make_message("user", "请生成结果"),
                _make_message(
                    "assistant", "[README.md](file:///tmp/project/README.md)"
                ),
            ]
        ),
    )

    async def collect():
        chunks = []
        async for batch in agent.run_stream(session_context):
            chunks.extend(batch)
        return chunks

    chunks = asyncio.run(collect())

    assert session_context.audit_status["self_check_passed"] is False
    assert "文件不存在: /tmp/project/README.md" in chunks[0].content
    _assert_hidden_self_check_message(chunks[0])


def test_artifacts_tag_relative_path_checks_file_existence(monkeypatch, tmp_path):
    self_check_agent = _load_self_check_agent(monkeypatch)
    agent = self_check_agent(model=None, model_config={})

    workspace = tmp_path / "workspace"
    artifact = workspace / "reports" / "out.md"
    artifact.parent.mkdir(parents=True)
    artifact.write_text("ok", encoding="utf-8")

    class DummySandbox:
        def is_path_allowed(self, path, operation="read"):
            return str(path).startswith(str(workspace))

        async def file_exists(self, path):
            return Path(path).exists()

        async def read_file(self, path, encoding="utf-8"):
            return Path(path).read_text(encoding=encoding)

    session_context = SimpleNamespace(
        audit_status={},
        sandbox=DummySandbox(),
        sandbox_agent_workspace=str(workspace),
        system_context={"private_workspace": str(workspace)},
        message_manager=SimpleNamespace(
            messages=[
                _make_message("user", "请生成结果"),
                _make_message(
                    "assistant",
                    '<movo-artifacts>{"items":[{"title":"报告","path":"reports/out.md","status":"created"}]}</movo-artifacts>',
                ),
            ]
        ),
    )

    async def collect():
        chunks = []
        async for batch in agent.run_stream(session_context):
            chunks.extend(batch)
        return chunks

    chunks = asyncio.run(collect())

    assert chunks == []
    assert session_context.audit_status["self_check_passed"] is True
    assert session_context.audit_status["self_check_checked_files"] == [str(artifact)]


def test_artifacts_tag_escaped_payload_checks_file_existence(monkeypatch, tmp_path):
    self_check_agent = _load_self_check_agent(monkeypatch)
    agent = self_check_agent(model=None, model_config={})

    workspace = tmp_path / "workspace"
    artifact = workspace / "reports" / "escaped.md"
    artifact.parent.mkdir(parents=True)
    artifact.write_text("ok", encoding="utf-8")

    class DummySandbox:
        def is_path_allowed(self, path, operation="read"):
            return str(path).startswith(str(workspace))

        async def file_exists(self, path):
            return Path(path).exists()

        async def read_file(self, path, encoding="utf-8"):
            return Path(path).read_text(encoding=encoding)

    session_context = SimpleNamespace(
        audit_status={},
        sandbox=DummySandbox(),
        sandbox_agent_workspace=str(workspace),
        system_context={"private_workspace": str(workspace)},
        message_manager=SimpleNamespace(
            messages=[
                _make_message("user", "请生成结果"),
                _make_message(
                    "assistant",
                    r"&lt;ling-artifacts&gt;{\"items\":[{\"title\":\"报告\",\"path\":\"reports/escaped.md\",\"status\":\"created\"}]}<\/ling-artifacts&gt;",
                ),
            ]
        ),
    )

    async def collect():
        chunks = []
        async for batch in agent.run_stream(session_context):
            chunks.extend(batch)
        return chunks

    chunks = asyncio.run(collect())

    assert chunks == []
    assert session_context.audit_status["self_check_passed"] is True
    assert session_context.audit_status["self_check_checked_files"] == [str(artifact)]


def test_artifacts_tag_missing_path_is_execution_error(monkeypatch, tmp_path):
    self_check_agent = _load_self_check_agent(monkeypatch)
    agent = self_check_agent(model=None, model_config={})

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    missing = workspace / "reports" / "missing.pdf"

    class MissingSandbox:
        def is_path_allowed(self, path, operation="read"):
            return str(path).startswith(str(workspace))

        async def file_exists(self, path):
            return False

    session_context = SimpleNamespace(
        audit_status={},
        sandbox=MissingSandbox(),
        sandbox_agent_workspace=str(workspace),
        system_context={"private_workspace": str(workspace)},
        message_manager=SimpleNamespace(
            messages=[
                _make_message("user", "请生成结果"),
                _make_message(
                    "assistant",
                    '<sage-artifacts>{"items":[{"title":"报告","path":"reports/missing.pdf","status":"created"}]}</sage-artifacts>',
                ),
            ]
        ),
    )

    async def collect():
        chunks = []
        async for batch in agent.run_stream(session_context):
            chunks.extend(batch)
        return chunks

    chunks = asyncio.run(collect())

    assert session_context.audit_status["self_check_passed"] is False
    assert session_context.audit_status["self_check_checked_files"] == [str(missing)]
    assert "文件不存在: reports/missing.pdf" in chunks[0].content
    _assert_hidden_self_check_message(chunks[0])


def test_artifacts_tag_http_path_is_ignored(monkeypatch, tmp_path):
    self_check_agent = _load_self_check_agent(monkeypatch)
    agent = self_check_agent(model=None, model_config={})

    workspace = tmp_path / "workspace"
    workspace.mkdir()

    class DummySandbox:
        async def file_exists(self, path):
            raise AssertionError("HTTP artifact URLs should not be checked")

    session_context = SimpleNamespace(
        audit_status={},
        sandbox=DummySandbox(),
        sandbox_agent_workspace=str(workspace),
        system_context={"private_workspace": str(workspace)},
        message_manager=SimpleNamespace(
            messages=[
                _make_message("user", "请生成结果"),
                _make_message(
                    "assistant",
                    '<artifacts>{"items":[{"title":"网页","path":"https://example.com/report.pdf","status":"created"}]}</artifacts>',
                ),
            ]
        ),
    )

    async def collect():
        chunks = []
        async for batch in agent.run_stream(session_context):
            chunks.extend(batch)
        return chunks

    chunks = asyncio.run(collect())

    assert chunks == []
    assert session_context.audit_status["self_check_passed"] is True
    assert session_context.audit_status["self_check_summary"] == ("checked 0 files")


def test_malformed_artifacts_json_triggers_execution_error(monkeypatch, tmp_path):
    self_check_agent = _load_self_check_agent(monkeypatch)
    agent = self_check_agent(model=None, model_config={})

    workspace = tmp_path / "workspace"
    workspace.mkdir()

    class DummySandbox:
        async def file_exists(self, path):
            return True

    session_context = SimpleNamespace(
        audit_status={},
        sandbox=DummySandbox(),
        sandbox_agent_workspace=str(workspace),
        system_context={"private_workspace": str(workspace)},
        message_manager=SimpleNamespace(
            messages=[
                _make_message("user", "请生成结果"),
                _make_message(
                    "assistant",
                    "<movo-artifacts>{bad json</movo-artifacts>",
                ),
            ]
        ),
    )

    async def collect():
        chunks = []
        async for batch in agent.run_stream(session_context):
            chunks.extend(batch)
        return chunks

    chunks = asyncio.run(collect())

    assert session_context.audit_status["self_check_passed"] is False
    assert "<movo-artifacts> 标签内容不是合法 JSON" in chunks[0].content
    _assert_hidden_self_check_message(chunks[0])


def test_malformed_questionnaire_json_triggers_execution_error(monkeypatch, tmp_path):
    self_check_agent = _load_self_check_agent(monkeypatch)
    agent = self_check_agent(model=None, model_config={})

    workspace = tmp_path / "workspace"
    workspace.mkdir()

    class DummySandbox:
        async def file_exists(self, path):
            return True

    session_context = SimpleNamespace(
        audit_status={},
        sandbox=DummySandbox(),
        sandbox_agent_workspace=str(workspace),
        system_context={"private_workspace": str(workspace)},
        message_manager=SimpleNamespace(
            messages=[
                _make_message("user", "请确认"),
                _make_message(
                    "assistant",
                    '<sage-questionnaire>{"questions":[{"type":"single_choice"}]}</sage-questionnaire>',
                ),
            ]
        ),
    )

    async def collect():
        chunks = []
        async for batch in agent.run_stream(session_context):
            chunks.extend(batch)
        return chunks

    chunks = asyncio.run(collect())

    assert session_context.audit_status["self_check_passed"] is False
    assert "<sage-questionnaire>" in chunks[0].content
    _assert_hidden_self_check_message(chunks[0])


def test_malformed_questionnaire_model_payload_triggers_execution_error(
    monkeypatch, tmp_path
):
    self_check_agent = _load_self_check_agent(monkeypatch)
    agent = self_check_agent(model=None, model_config={})

    workspace = tmp_path / "workspace"
    workspace.mkdir()

    class DummySandbox:
        async def file_exists(self, path):
            return True

    bad_payload = (
        '<movo-questionnaire>{"title":"Choose a creative direction",'
        '"questions":[{"type":"single_choice",'
        '"text":"Which direction should this Greek yogurt promo take?",'
        '"options":["Open with an ultra-close creamy spoon lift and fruit drop, '
        'making texture and appetite the main conversion hook.",'
        '"default":"Open with an ultra-close creamy spoon lift and fruit drop, '
        'making texture and appetite the main conversion hook.",'
        '"allow_other":true},'
        '{"type":"free_text",'
        '"text":"Tell me the target audience, must-show elements, or anything '
        'you want adjusted before I write the plan.",'
        '"default":""}]}</movo-questionnaire>'
    )

    session_context = SimpleNamespace(
        audit_status={},
        sandbox=DummySandbox(),
        sandbox_agent_workspace=str(workspace),
        system_context={"private_workspace": str(workspace)},
        message_manager=SimpleNamespace(
            messages=[
                _make_message("user", "请确认"),
                _make_message("assistant", bad_payload),
            ]
        ),
    )

    async def collect():
        chunks = []
        async for batch in agent.run_stream(session_context):
            chunks.extend(batch)
        return chunks

    chunks = asyncio.run(collect())

    assert session_context.audit_status["self_check_passed"] is False
    assert "<movo-questionnaire> 标签内容不是合法 JSON" in chunks[0].content
    _assert_hidden_self_check_message(chunks[0])


def test_malformed_yiii_questionnaire_from_session_triggers_execution_error(
    monkeypatch, tmp_path
):
    self_check_agent = _load_self_check_agent(monkeypatch)
    agent = self_check_agent(model=None, model_config={})

    workspace = tmp_path / "workspace"
    workspace.mkdir()

    class DummySandbox:
        async def file_exists(self, path):
            return True

    malformed_payload = (
        '<yiii-questionnaire>{"title":"视频Brief确认","questions":'
        '[{"type":"single_choice","text":"执行？",'
        '"options":["执行生成视频计划","调整视频计划"],'
        '"default":"执行生成视频计划"}]}></yiii-questionnaire>'
    )
    session_context = SimpleNamespace(
        audit_status={},
        sandbox=DummySandbox(),
        sandbox_agent_workspace=str(workspace),
        system_context={"private_workspace": str(workspace)},
        message_manager=SimpleNamespace(
            messages=[
                _make_message("user", "请确认"),
                _make_message("assistant", malformed_payload),
            ]
        ),
    )

    async def collect():
        chunks = []
        async for batch in agent.run_stream(session_context):
            chunks.extend(batch)
        return chunks

    chunks = asyncio.run(collect())

    assert session_context.audit_status["self_check_passed"] is False
    assert "<yiii-questionnaire> 标签内容不是合法 JSON" in chunks[0].content
    _assert_hidden_self_check_message(chunks[0])


def test_valid_yiii_structured_aliases_are_accepted(monkeypatch):
    self_check_agent = _load_self_check_agent(monkeypatch)
    agent = self_check_agent(model=None, model_config={})

    content = (
        '<yiii-artifacts>{"items":[{"path":"result.md"}]}</yiii-artifacts>'
        '<yiii-questionnaire>{"title":"确认","questions":['
        '{"type":"single_choice","text":"继续？","options":["是","否"],'
        '"default":"是"}]}'
        '</yiii-questionnaire>'
        '<yiii-questionnaire-response>{"answers":[{"value":"是"}]}'
        '</yiii-questionnaire-response>'
    )

    assert agent._content_has_structured_tags(content) is True
    assert agent._validate_structured_tag_payloads(content) == []
    assert agent._extract_artifact_paths(content) == {"result.md"}


def test_invalid_yiii_questionnaire_field_structure_is_rejected(monkeypatch):
    self_check_agent = _load_self_check_agent(monkeypatch)
    agent = self_check_agent(model=None, model_config={})

    content = (
        '<yiii-questionnaire>{"title":"确认","questions":['
        '{"type":"single_choice","text":"继续？","options":["是","否"]}]}'
        '</yiii-questionnaire>'
    )

    issues = agent._validate_structured_tag_payloads(content)

    assert issues == [
        "<yiii-questionnaire> questions[1] 缺少 default 字段"
    ]


def test_valid_questionnaire_without_files_passes_self_check(monkeypatch, tmp_path):
    self_check_agent = _load_self_check_agent(monkeypatch)
    agent = self_check_agent(model=None, model_config={})

    workspace = tmp_path / "workspace"
    workspace.mkdir()

    class DummySandbox:
        async def file_exists(self, path):
            return True

    session_context = SimpleNamespace(
        audit_status={},
        sandbox=DummySandbox(),
        sandbox_agent_workspace=str(workspace),
        system_context={"private_workspace": str(workspace)},
        message_manager=SimpleNamespace(
            messages=[
                _make_message("user", "请确认"),
                _make_message(
                    "assistant",
                    '<yiii-questionnaire>{"title":"确认","questions":[{"type":"single_choice","text":"画幅？","options":["9:16","16:9"],"default":"16:9"}]}</yiii-questionnaire>',
                ),
            ]
        ),
    )

    async def collect():
        chunks = []
        async for batch in agent.run_stream(session_context):
            chunks.extend(batch)
        return chunks

    chunks = asyncio.run(collect())

    assert chunks == []
    assert session_context.audit_status["self_check_passed"] is True
    assert session_context.audit_status["self_check_summary"] == "checked 0 files"


def test_invalid_questionnaire_must_be_reoutput_before_requirement_clears(
    monkeypatch, tmp_path
):
    self_check_agent = _load_self_check_agent(monkeypatch)
    agent = self_check_agent(model=None, model_config={})

    workspace = tmp_path / "workspace"
    workspace.mkdir()

    class DummySandbox:
        async def file_exists(self, path):
            return True

    invalid_questionnaire = (
        '<yiii-questionnaire>{"title":"确认","questions":['
        '{"type":"single_choice","text":"继续？","options":["是","否"],'
        '"default":"是"}]}></yiii-questionnaire>'
    )
    valid_questionnaire = invalid_questionnaire.replace(
        "]}>", "]}"
    )
    session_context = SimpleNamespace(
        audit_status={},
        sandbox=DummySandbox(),
        sandbox_agent_workspace=str(workspace),
        system_context={"private_workspace": str(workspace)},
        message_manager=SimpleNamespace(messages=[]),
    )

    async def run_with_reply(reply):
        session_context.message_manager.messages = [
            _make_message("user", "请确认"),
            _make_message("assistant", reply),
        ]
        chunks = []
        async for batch in agent.run_stream(session_context):
            chunks.extend(batch)
        return chunks

    first_chunks = asyncio.run(run_with_reply(invalid_questionnaire))
    assert first_chunks
    assert session_context.audit_status[
        "self_check_required_structured_tags"
    ] == ["yiii-questionnaire"]

    second_chunks = asyncio.run(run_with_reply("我会继续处理。"))
    assert second_chunks
    assert "必须在修复后的完整回复中重新输出" in second_chunks[0].content
    assert session_context.audit_status["self_check_passed"] is False

    final_chunks = asyncio.run(run_with_reply(valid_questionnaire))
    assert final_chunks == []
    assert session_context.audit_status["self_check_passed"] is True
    assert "self_check_required_structured_tags" not in session_context.audit_status


def test_inline_code_wrapped_file_link_triggers_execution_error(monkeypatch):
    self_check_agent = _load_self_check_agent(monkeypatch)
    agent = self_check_agent(model=None, model_config={})

    class DummySandbox:
        async def file_exists(self, path):
            return True

        async def read_file(self, path, encoding="utf-8"):
            return ""

    session_context = SimpleNamespace(
        audit_status={},
        sandbox=DummySandbox(),
        message_manager=SimpleNamespace(
            messages=[
                _make_message("user", "请生成结果"),
                _make_message(
                    "assistant", "`[video_plan.md](file:///tmp/video_plan.md)`"
                ),
            ]
        ),
    )

    async def collect():
        chunks = []
        async for batch in agent.run_stream(session_context):
            chunks.extend(batch)
        return chunks

    chunks = asyncio.run(collect())

    assert session_context.audit_status["self_check_passed"] is False
    assert "真实文件引用不能放在反引号或代码块中" in chunks[0].content
    _assert_hidden_self_check_message(chunks[0])


def test_markdown_code_regions_reject_local_file_links(monkeypatch):
    self_check_agent = _load_self_check_agent(monkeypatch)
    agent = self_check_agent(model=None, model_config={})

    samples = [
        "``[report.md](file:///tmp/report.md)``",
        "```markdown\n[report.md](file:///tmp/report.md)\n```",
        "~~~\n![preview](file:///tmp/preview.png)\n~~~",
        "```\n[report.md](file:///tmp/report.md)",
        "`[report](<file:///tmp/report with spaces.md>)`",
    ]

    for content in samples:
        issues = agent._validate_markdown_file_link_syntax(content)
        assert len(issues) == 1, content
        assert "真实文件引用不能放在反引号或代码块中" in issues[0]


def test_markdown_indented_code_blocks_reject_local_file_links(monkeypatch):
    self_check_agent = _load_self_check_agent(monkeypatch)
    agent = self_check_agent(model=None, model_config={})

    samples = [
        "    [report.md](file:///tmp/report.md)",
        "\t[report.md](file:///tmp/report.md)",
        ">     [report.md](file:///tmp/report.md)",
        "结果如下：\n\n    [report.md](file:///tmp/report.md)",
    ]

    for content in samples:
        issues = agent._validate_markdown_file_link_syntax(content)
        assert len(issues) == 1, content
        assert "真实文件引用不能放在反引号或代码块中" in issues[0]


def test_indented_paragraph_continuation_keeps_file_link_clickable(monkeypatch):
    self_check_agent = _load_self_check_agent(monkeypatch)
    agent = self_check_agent(model=None, model_config={})
    content = "结果如下：\n    [report.md](file:///tmp/report.md)"

    assert agent._validate_markdown_file_link_syntax(content) == []


def test_escaped_backticks_do_not_hide_clickable_file_link(monkeypatch):
    self_check_agent = _load_self_check_agent(monkeypatch)
    agent = self_check_agent(model=None, model_config={})
    content = r"\`[report.md](file:///tmp/report.md)\`"
    session_context = SimpleNamespace(
        message_manager=SimpleNamespace(
            messages=[
                _make_message("user", "检查"),
                _make_message("assistant", content),
            ]
        )
    )

    assert agent._validate_markdown_file_link_syntax(content) == []
    assert agent._collect_recent_referenced_files(session_context) == {
        "/tmp/report.md"
    }


def test_code_file_links_are_not_collected_as_clickable_artifacts(monkeypatch):
    self_check_agent = _load_self_check_agent(monkeypatch)
    agent = self_check_agent(model=None, model_config={})
    session_context = SimpleNamespace(
        message_manager=SimpleNamespace(
            messages=[
                _make_message("user", "检查"),
                _make_message(
                    "assistant",
                    "```\n[hidden.md](file:///tmp/hidden.md)\n```\n"
                    "[visible.md](<file:///tmp/visible%20file.md>)",
                ),
            ]
        )
    )

    referenced = agent._collect_recent_referenced_files(session_context)

    assert referenced == {"/tmp/visible file.md"}


def test_balanced_parentheses_in_markdown_file_targets_are_collected(monkeypatch):
    self_check_agent = _load_self_check_agent(monkeypatch)
    agent = self_check_agent(model=None, model_config={})
    session_context = SimpleNamespace(
        message_manager=SimpleNamespace(
            messages=[
                _make_message("user", "检查"),
                _make_message(
                    "assistant",
                    "[report](file:///tmp/report(1).md)\n"
                    "![preview](file:///tmp/preview(2).png)",
                ),
            ]
        )
    )

    referenced = agent._collect_recent_referenced_files(session_context)

    assert referenced == {"/tmp/report(1).md", "/tmp/preview(2).png"}


def test_list_fence_file_link_is_code_only(monkeypatch):
    self_check_agent = _load_self_check_agent(monkeypatch)
    agent = self_check_agent(model=None, model_config={})
    content = (
        "- ```markdown\n"
        "  [hidden.md](file:///tmp/hidden.md)\n"
        "  ```"
    )
    session_context = SimpleNamespace(
        message_manager=SimpleNamespace(
            messages=[
                _make_message("user", "检查"),
                _make_message("assistant", content),
            ]
        )
    )

    issues = agent._validate_markdown_file_link_syntax(content)
    referenced = agent._collect_recent_referenced_files(session_context)

    assert len(issues) == 1
    assert "真实文件引用不能放在反引号或代码块中" in issues[0]
    assert referenced == set()


def test_inline_code_span_does_not_cross_fenced_block(monkeypatch):
    self_check_agent = _load_self_check_agent(monkeypatch)
    agent = self_check_agent(model=None, model_config={})
    content = (
        "`unmatched literal\n"
        "```text\n"
        "fenced\n"
        "```\n"
        "[visible.md](file:///tmp/visible.md) `"
    )
    session_context = SimpleNamespace(
        message_manager=SimpleNamespace(
            messages=[
                _make_message("user", "检查"),
                _make_message("assistant", content),
            ]
        )
    )

    assert agent._validate_markdown_file_link_syntax(content) == []
    assert agent._collect_recent_referenced_files(session_context) == {
        "/tmp/visible.md"
    }


def test_non_file_links_and_plain_code_do_not_trigger_file_link_issue(monkeypatch):
    self_check_agent = _load_self_check_agent(monkeypatch)
    agent = self_check_agent(model=None, model_config={})

    content = "```markdown\n[docs](https://example.com/docs)\n```\n`plain code`"

    assert agent._validate_markdown_file_link_syntax(content) == []


def test_standard_absolute_file_link_passes_self_check(monkeypatch):
    self_check_agent = _load_self_check_agent(monkeypatch)
    agent = self_check_agent(model=None, model_config={})

    class DummySandbox:
        async def file_exists(self, path):
            return True

        async def read_file(self, path, encoding="utf-8"):
            return ""

    session_context = SimpleNamespace(
        audit_status={},
        sandbox=DummySandbox(),
        message_manager=SimpleNamespace(
            messages=[
                _make_message("user", "请生成结果"),
                _make_message(
                    "assistant", "[video_plan.md](file:///tmp/video_plan.md)"
                ),
            ]
        ),
    )

    async def collect():
        chunks = []
        async for batch in agent.run_stream(session_context):
            chunks.extend(batch)
        return chunks

    chunks = asyncio.run(collect())

    assert chunks == []
    assert session_context.audit_status["self_check_passed"] is True


def test_absolute_markdown_link_outside_workspace_is_execution_error(
    monkeypatch, tmp_path
):
    self_check_agent = _load_self_check_agent(monkeypatch)
    agent = self_check_agent(model=None, model_config={})

    workspace = tmp_path / "agents" / "user_1" / "agent_1"
    outside = tmp_path / "agents" / "user_1" / "reports" / "out.md"

    class DummySandbox:
        def is_path_allowed(self, path, operation="read"):
            return str(path).startswith(str(workspace))

        async def file_exists(self, path):
            return True

        async def read_file(self, path, encoding="utf-8"):
            return ""

    session_context = SimpleNamespace(
        audit_status={},
        sandbox=DummySandbox(),
        sandbox_agent_workspace=str(workspace),
        system_context={"private_workspace": str(workspace)},
        message_manager=SimpleNamespace(
            messages=[
                _make_message("user", "请生成结果"),
                _make_message("assistant", f"[out.md](file://{outside})"),
            ]
        ),
    )

    async def collect():
        chunks = []
        async for batch in agent.run_stream(session_context):
            chunks.extend(batch)
        return chunks

    chunks = asyncio.run(collect())

    assert session_context.audit_status["self_check_passed"] is False
    assert "文件路径超出可访问工作区" in chunks[0].content
    assert str(outside) in chunks[0].content
    _assert_hidden_self_check_message(chunks[0])


def test_broad_sandbox_permission_is_authoritative(monkeypatch, tmp_path):
    self_check_agent = _load_self_check_agent(monkeypatch)
    agent = self_check_agent(model=None, model_config={})

    user_root = tmp_path / "agents" / "user_1"
    workspace = user_root / "agent_1"
    outside = user_root / "data" / "out.md"
    outside.parent.mkdir(parents=True)
    outside.write_text("ok", encoding="utf-8")

    class BroadSandbox:
        def is_path_allowed(self, path, operation="read"):
            return str(path).startswith(str(user_root))

        async def file_exists(self, path):
            return True

        async def read_file(self, path, encoding="utf-8"):
            return ""

    session_context = SimpleNamespace(
        audit_status={},
        sandbox=BroadSandbox(),
        sandbox_agent_workspace=str(workspace),
        system_context={"private_workspace": str(workspace)},
        message_manager=SimpleNamespace(
            messages=[
                _make_message("user", "请生成结果"),
                _make_message("assistant", f"[out.md](file://{outside})"),
            ]
        ),
    )

    async def collect():
        chunks = []
        async for batch in agent.run_stream(session_context):
            chunks.extend(batch)
        return chunks

    chunks = asyncio.run(collect())

    assert chunks == []
    assert session_context.audit_status["self_check_passed"] is True
    assert session_context.audit_status["self_check_checked_files"] == [str(outside)]
