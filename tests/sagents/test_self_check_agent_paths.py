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

    class MessageChunk:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    message_module.MessageChunk = MessageChunk
    message_module.MessageRole = MessageRole
    message_module.MessageType = MessageType
    monkeypatch.setitem(sys.modules, "sagents.context.messages.message", message_module)

    session_context_module = types.ModuleType("sagents.context.session_context")
    session_context_module.SessionContext = object
    monkeypatch.setitem(sys.modules, "sagents.context.session_context", session_context_module)

    logger_module = types.ModuleType("sagents.utils.logger")
    logger_module.logger = SimpleNamespace(info=lambda *args, **kwargs: None, warning=lambda *args, **kwargs: None)
    monkeypatch.setitem(sys.modules, "sagents.utils.logger", logger_module)

    agent_base_module = types.ModuleType("sagents.agent.agent_base")

    class AgentBase:
        def __init__(self, *args, **kwargs):
            pass

        def _should_abort_due_to_session(self, session_context):
            return False

    agent_base_module.AgentBase = AgentBase
    monkeypatch.setitem(sys.modules, "sagents.agent.agent_base", agent_base_module)

    module_path = Path("/Users/zhangzheng/workspace/Sage/sagents/agent/self_check_agent.py")
    spec = importlib.util.spec_from_file_location("sagents.agent.self_check_agent", module_path)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "sagents.agent.self_check_agent", module)
    assert spec.loader is not None
    spec.loader.exec_module(module)
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
                _make_message("assistant", "[README.md](file:///tmp/project/README.md)"),
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
