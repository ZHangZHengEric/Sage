import asyncio

from sagents.tool.impl.execute_command_tool import ExecuteCommandTool
from sagents.utils.sandbox.interface import CommandResult


class _FakeSandbox:
    def __init__(self):
        self.workspace_path = "/sage-workspace"
        self.calls = []

    async def execute_command(self, command, workdir=None, timeout=30, env_vars=None):
        self.calls.append(
            {
                "command": command,
                "workdir": workdir,
                "timeout": timeout,
                "env_vars": env_vars,
            }
        )
        return CommandResult(
            success=True,
            stdout="/sage-workspace\n",
            stderr="",
            return_code=0,
            execution_time=0.1,
        )


class _FakeSessionContext:
    def __init__(self, sandbox):
        self.sandbox = sandbox


class _FakeSession:
    def __init__(self, sandbox):
        self.session_context = _FakeSessionContext(sandbox)


class _FakeSessionManager:
    def __init__(self, sandbox):
        self._session = _FakeSession(sandbox)

    def get(self, session_id):
        return self._session

    def get_live_session(self, session_id):
        return self._session


class _FakeBackgroundSandbox(_FakeSandbox):
    def __init__(self, agent_workspace):
        super().__init__()
        self.workspace_path = str(agent_workspace)
        self.host_workspace_path = str(agent_workspace)
        self.bg_calls = []

    def supports_background(self):
        return True

    async def start_background(self, command, workdir=None, env_vars=None, log_dir=None):
        self.bg_calls.append(
            {
                "command": command,
                "workdir": workdir,
                "env_vars": env_vars,
                "log_dir": log_dir,
            }
        )
        return {
            "task_id": "shtask_fake",
            "pid": 123,
            "log_path": f"{log_dir}/shtask_fake.log" if log_dir else "/fallback/shtask_fake.log",
        }

    async def read_background_output(self, task_id, max_bytes=8192):
        return ""


def test_execute_shell_command_uses_provider_default_workdir(monkeypatch):
    fake_sandbox = _FakeBackgroundSandbox("/sage-workspace")
    fake_manager = _FakeSessionManager(fake_sandbox)
    monkeypatch.setattr(ExecuteCommandTool, "_BG_TASKS", {})
    monkeypatch.setattr(ExecuteCommandTool, "_COMPLETION_EVENTS", {})

    import sagents.session_runtime

    monkeypatch.setattr(
        sagents.session_runtime,
        "get_global_session_manager",
        lambda: fake_manager,
    )

    tool = ExecuteCommandTool()
    result = asyncio.run(
        tool.execute_shell_command(
            command="pwd",
            session_id="session-1",
            block_until_ms=0,
        )
    )

    assert result["success"] is True
    assert result["status"] == "running"
    assert fake_sandbox.bg_calls == [
        {
            "command": "pwd",
            "workdir": None,
            "env_vars": None,
            "log_dir": "/sage-workspace/bg",
        }
    ]


def test_execute_shell_command_passes_tool_env_to_background_runner(monkeypatch):
    fake_sandbox = _FakeBackgroundSandbox("/sage-workspace")
    fake_manager = _FakeSessionManager(fake_sandbox)
    monkeypatch.setattr(ExecuteCommandTool, "_BG_TASKS", {})
    monkeypatch.setattr(ExecuteCommandTool, "_COMPLETION_EVENTS", {})

    import sagents.session_runtime

    monkeypatch.setattr(
        sagents.session_runtime,
        "get_global_session_manager",
        lambda: fake_manager,
    )

    tool = ExecuteCommandTool()
    result = asyncio.run(
        tool.execute_shell_command(
            command="printenv SHARED",
            session_id="session-1",
            block_until_ms=0,
            env_vars={
                "SHARED": "tool-override",
                "TOOL_ONLY": "tool-value",
            },
        )
    )

    assert result["success"] is True
    assert result["status"] == "running"
    assert fake_sandbox.bg_calls == [
        {
            "command": "printenv SHARED",
            "workdir": None,
            "env_vars": {
                "SHARED": "tool-override",
                "TOOL_ONLY": "tool-value",
            },
            "log_dir": "/sage-workspace/bg",
        }
    ]


def test_execute_shell_command_parses_json_env_vars_for_background_runner(monkeypatch):
    fake_sandbox = _FakeBackgroundSandbox("/sage-workspace")
    fake_manager = _FakeSessionManager(fake_sandbox)
    monkeypatch.setattr(ExecuteCommandTool, "_BG_TASKS", {})
    monkeypatch.setattr(ExecuteCommandTool, "_COMPLETION_EVENTS", {})

    import sagents.session_runtime

    monkeypatch.setattr(
        sagents.session_runtime,
        "get_global_session_manager",
        lambda: fake_manager,
    )

    tool = ExecuteCommandTool()
    result = asyncio.run(
        tool.execute_shell_command(
            command="printenv MOVO_SUBTITLE_PROVIDER",
            session_id="session-1",
            block_until_ms=0,
            env_vars='{"MOVO_SUBTITLE_PROVIDER":"debug_stub","CUSTOM":"custom-value"}',
        )
    )

    assert result["success"] is True
    assert result["status"] == "running"
    assert fake_sandbox.bg_calls[0]["env_vars"] == {
        "MOVO_SUBTITLE_PROVIDER": "debug_stub",
        "CUSTOM": "custom-value",
    }
    assert fake_sandbox.bg_calls[0]["log_dir"] == "/sage-workspace/bg"


def test_background_shell_logs_under_agent_workspace(monkeypatch, tmp_path):
    agent_workspace = tmp_path / "agents" / "agent-1"
    fake_sandbox = _FakeBackgroundSandbox(agent_workspace)
    fake_manager = _FakeSessionManager(fake_sandbox)
    monkeypatch.setattr(ExecuteCommandTool, "_BG_TASKS", {})
    monkeypatch.setattr(ExecuteCommandTool, "_COMPLETION_EVENTS", {})

    import sagents.session_runtime

    monkeypatch.setattr(
        sagents.session_runtime,
        "get_global_session_manager",
        lambda: fake_manager,
    )

    tool = ExecuteCommandTool()
    result = asyncio.run(
        tool.execute_shell_command(
            command="sleep 1",
            session_id="session-1",
            block_until_ms=0,
        )
    )

    expected_log_dir = str(agent_workspace / "bg")
    assert result["output_file"] == f"{expected_log_dir}/shtask_fake.log"
    assert fake_sandbox.bg_calls[0]["log_dir"] == expected_log_dir


def test_background_shell_passes_virtual_workspace_log_dir_to_provider(monkeypatch, tmp_path):
    host_workspace = tmp_path / "host-agent-workspace"
    fake_sandbox = _FakeBackgroundSandbox(host_workspace)
    fake_sandbox.workspace_path = "/sandbox-agent-workspace"
    fake_manager = _FakeSessionManager(fake_sandbox)
    monkeypatch.setattr(ExecuteCommandTool, "_BG_TASKS", {})
    monkeypatch.setattr(ExecuteCommandTool, "_COMPLETION_EVENTS", {})

    import sagents.session_runtime

    monkeypatch.setattr(
        sagents.session_runtime,
        "get_global_session_manager",
        lambda: fake_manager,
    )

    tool = ExecuteCommandTool()
    result = asyncio.run(
        tool.execute_shell_command(
            command="sleep 1",
            session_id="session-1",
            block_until_ms=0,
        )
    )

    assert result["output_file"] == "/sandbox-agent-workspace/bg/shtask_fake.log"
    assert fake_sandbox.bg_calls[0]["log_dir"] == "/sandbox-agent-workspace/bg"
