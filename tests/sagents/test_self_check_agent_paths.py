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
    assert chunks[0].message_type == "agent_execution_error"


def test_self_check_failure_message_uses_english_runtime_diagnostic(monkeypatch):
    self_check_agent = _load_self_check_agent(monkeypatch)
    agent = self_check_agent(model=None, model_config={})

    content = agent._format_failure_message(
        ["File does not exist: output.md"], ["/tmp/output.md"], language="en"
    )

    assert "<runtime_diagnostic source=\"sage_self_check\" generated_by=\"system\">" in content
    assert "not a reply authored by the assistant/agent" in content
    assert "Self-check found issues" in content
    assert "Checked files:" in content


def test_self_check_failure_message_uses_portuguese_runtime_diagnostic(monkeypatch):
    self_check_agent = _load_self_check_agent(monkeypatch)
    agent = self_check_agent(model=None, model_config={})

    content = agent._format_failure_message(
        ["Arquivo nao existe: output.md"], ["/tmp/output.md"], language="pt"
    )

    assert "<runtime_diagnostic source=\"sage_self_check\" generated_by=\"system\">" in content
    assert "nao uma resposta escrita pelo assistant/agent" in content
    assert "Arquivos verificados:" in content


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
    assert chunks[0].message_type == "agent_execution_error"


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
    assert chunks[0].message_type == "agent_execution_error"


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
    assert session_context.audit_status["self_check_summary"] == (
        "skip: no candidate files detected"
    )


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
    assert chunks[0].message_type == "agent_execution_error"


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
