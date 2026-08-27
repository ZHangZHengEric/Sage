import asyncio
import logging
from types import SimpleNamespace

from app.server import bootstrap, lifecycle
from mcp_servers.task_scheduler import task_scheduler_server
from sagents.tool import tool_manager as tool_manager_module
from sagents.tool.tool_manager import ToolManager


class _RecordingLogger:
    def __init__(self):
        self.debug_messages = []
        self.info_messages = []
        self.warning_messages = []
        self.error_messages = []

    def debug(self, message):
        self.debug_messages.append(str(message))

    def info(self, message):
        self.info_messages.append(str(message))

    def warning(self, message):
        self.warning_messages.append(str(message))

    def error(self, message):
        self.error_messages.append(str(message))


def test_task_scheduler_uses_centralized_logging_handlers():
    scheduler_logger = logging.getLogger("TaskScheduler")

    assert scheduler_logger is task_scheduler_server.logger
    assert scheduler_logger.handlers == []
    assert scheduler_logger.level == logging.NOTSET
    assert scheduler_logger.propagate is True


def test_empty_mcp_refresh_is_debug_not_warning(monkeypatch):
    recording_logger = _RecordingLogger()
    monkeypatch.setattr(tool_manager_module, "logger", recording_logger)
    manager = ToolManager(is_auto_discover=False, isolated=True)

    removed = asyncio.run(manager.remove_tool_by_mcp("ling", close_pool=False))

    assert removed is True
    assert recording_logger.warning_messages == []
    assert recording_logger.debug_messages[-1] == (
        "No MCP tools found for server 'ling' to remove"
    )


def test_post_start_scheduler_reports_success_once(monkeypatch):
    recording_logger = _RecordingLogger()

    async def no_wait(_seconds):
        return None

    monkeypatch.setattr(lifecycle, "logger", recording_logger)
    monkeypatch.setattr(lifecycle.asyncio, "sleep", no_wait)
    monkeypatch.setattr(task_scheduler_server, "ensure_scheduler_started", lambda: True)

    asyncio.run(lifecycle._start_task_scheduler())

    assert recording_logger.info_messages == []
    assert recording_logger.debug_messages == ["Sage：TaskScheduler 已启动"]


def test_default_anytool_activation_does_not_repeat_registration_success(monkeypatch):
    recording_logger = _RecordingLogger()

    async def no_wait(_seconds):
        return None

    async def ensure_ready(**_kwargs):
        return object()

    monkeypatch.setattr(lifecycle, "logger", recording_logger)
    monkeypatch.setattr(lifecycle.asyncio, "sleep", no_wait)
    monkeypatch.setattr(
        "common.services.mcp_service.ensure_default_anytool_server", ensure_ready
    )

    asyncio.run(lifecycle._ensure_default_anytool_server_ready())

    assert recording_logger.info_messages == []
    assert recording_logger.debug_messages == ["默认 AnyTool MCP server 已激活"]


def test_mcp_validation_keeps_summary_without_per_server_success(monkeypatch):
    recording_logger = _RecordingLogger()
    server = SimpleNamespace(
        name="ling",
        config={"disabled": False, "kind": "external"},
    )

    class FakeDao:
        async def get_list(self):
            return [server]

        async def save_mcp_server(self, **_kwargs):
            return None

    class FakeToolManager:
        async def register_mcp_server(self, _name, _config):
            return [object()]

    async def ensure_default(**_kwargs):
        return None

    monkeypatch.setattr(bootstrap, "logger", recording_logger)
    monkeypatch.setattr(bootstrap, "ensure_default_anytool_server", ensure_default)
    monkeypatch.setattr("common.models.mcp_server.MCPServerDao", FakeDao)
    monkeypatch.setattr(
        ToolManager, "get_instance", classmethod(lambda _cls: FakeToolManager())
    )

    asyncio.run(bootstrap.validate_and_disable_mcp_servers())

    assert "MCP server ling 刷新成功" not in recording_logger.info_messages
    assert "MCP server ling 刷新成功" in recording_logger.debug_messages
    assert recording_logger.info_messages == [
        "开始刷新MCP server: ling",
        "MCP 验证完成：成功 1 个，禁用 0 个不可用服务器",
    ]
