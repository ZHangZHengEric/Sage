import asyncio

from sagents.tool.impl.execute_command_tool import ExecuteCommandTool
from sagents.tool.tool_progress import (
    bind_tool_progress_context,
    register_progress_queue,
    unregister_progress_queue,
)
from sagents.utils.sandbox.approval import (
    get_sandbox_approval_broker,
    resolve_sandbox_approval,
)
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

    async def start_background(
        self, command, workdir=None, env_vars=None, log_dir=None
    ):
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
            "log_path": f"{log_dir}/shtask_fake.log"
            if log_dir
            else "/fallback/shtask_fake.log",
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


def test_execute_shell_command_blocks_policy_ask_before_spawn(monkeypatch):
    monkeypatch.setattr(ExecuteCommandTool, "_BG_TASKS", {})
    monkeypatch.setattr(ExecuteCommandTool, "_COMPLETION_EVENTS", {})
    monkeypatch.setattr(ExecuteCommandTool, "_PENDING_APPROVALS", {})

    tool = ExecuteCommandTool()
    result = asyncio.run(
        tool.execute_shell_command(
            command="git push origin feature-x",
            session_id="session-1",
            block_until_ms=0,
        )
    )

    assert result["success"] is False
    assert result["error_code"] == "SAFETY_BLOCKED"
    assert result["policy_action"] == "ask"
    assert result["policy_category"] == "git_remote_write"
    assert result["policy_approval_mode"] == "on-request"
    assert result["approval_id"].startswith("shapproval_")
    assert result["approval_expires_at"].endswith("Z")
    assert ExecuteCommandTool._BG_TASKS == {}


def test_execute_shell_command_uses_session_approval_mode(monkeypatch):
    monkeypatch.setattr(ExecuteCommandTool, "_BG_TASKS", {})
    monkeypatch.setattr(ExecuteCommandTool, "_COMPLETION_EVENTS", {})
    monkeypatch.setattr(ExecuteCommandTool, "_PENDING_APPROVALS", {})

    tool = ExecuteCommandTool()
    result = asyncio.run(
        tool.execute_shell_command(
            command="git push origin feature-x",
            session_id="session-1",
            block_until_ms=0,
            sandbox_approval_mode="never",
        )
    )

    assert result["success"] is False
    assert result["error_code"] == "SAFETY_BLOCKED"
    assert result["policy_action"] == "deny"
    assert result["policy_approval_mode"] == "never"
    assert "approval_id" not in result
    assert ExecuteCommandTool._PENDING_APPROVALS == {}


def test_execute_shell_command_awaits_broker_approval_before_spawn(monkeypatch):
    fake_sandbox = _FakeBackgroundSandbox("/sage-workspace")
    fake_manager = _FakeSessionManager(fake_sandbox)
    monkeypatch.setattr(ExecuteCommandTool, "_BG_TASKS", {})
    monkeypatch.setattr(ExecuteCommandTool, "_COMPLETION_EVENTS", {})
    monkeypatch.setattr(ExecuteCommandTool, "_PENDING_APPROVALS", {})

    import sagents.session_runtime

    monkeypatch.setattr(
        sagents.session_runtime,
        "get_global_session_manager",
        lambda: fake_manager,
    )

    async def run_flow():
        queue = asyncio.Queue()
        register_progress_queue("session-approval", queue)
        try:
            tool = ExecuteCommandTool()
            with bind_tool_progress_context("session-approval", "tool-call-1"):
                task = asyncio.create_task(
                    tool.execute_shell_command(
                        command="git push origin feature-x",
                        session_id="session-approval",
                        block_until_ms=0,
                    )
                )
                event = await asyncio.wait_for(queue.get(), timeout=1)
                assert event["type"] == "sandbox_approval_requested"
                assert event["approval_id"].startswith("shapproval_")
                assert event["command"] == "git push origin feature-x"
                assert fake_sandbox.bg_calls == []
                status = resolve_sandbox_approval(
                    session_id="session-approval",
                    approval_id=event["approval_id"],
                    decision="approve",
                    command_hash_value=event["command_hash"],
                )
                assert status == "resolved"
                resolved_event = await asyncio.wait_for(queue.get(), timeout=1)
                assert resolved_event["type"] == "sandbox_approval_resolved"
                assert resolved_event["approval_id"] == event["approval_id"]
                assert resolved_event["decision"] == "approve"
                assert resolved_event["approval_status"] == "approved"
                assert resolved_event["command_hash"] == event["command_hash"]
                result = await asyncio.wait_for(task, timeout=1)
                return result
        finally:
            unregister_progress_queue("session-approval")

    result = asyncio.run(run_flow())

    assert result["success"] is True
    assert result["status"] == "running"
    assert fake_sandbox.bg_calls[0]["command"] == "git push origin feature-x"


def test_sandbox_approval_broker_discard_removes_pending_approval():
    async def run_flow():
        broker = get_sandbox_approval_broker()
        pending = broker.create(
            session_id="session-discard",
            command="git push origin feature-x",
            category="git_remote_write",
            reason="requires approval",
            approval_mode="on-request",
        )

        broker.discard(pending.approval_id)

        assert pending.future.done()
        assert pending.future.result() == "deny"
        audit = broker.list_audit(session_id="session-discard", limit=1)
        assert audit[0]["approval_id"] == pending.approval_id
        assert audit[0]["command_hash"] == pending.command_hash
        assert audit[0]["status"] == "discarded"
        assert audit[0]["decision"] == "deny"
        assert audit[0]["resolved_at"] is not None
        assert (
            resolve_sandbox_approval(
                session_id="session-discard",
                approval_id=pending.approval_id,
                decision="approve",
                command_hash_value=pending.command_hash,
            )
            == "not_found"
        )

    asyncio.run(run_flow())


def test_sandbox_approval_broker_records_resolved_decision_audit():
    async def run_flow():
        broker = get_sandbox_approval_broker()
        pending = broker.create(
            session_id="session-audit",
            command="git push origin feature-x",
            category="git_remote_write",
            reason="requires approval",
            approval_mode="on-request",
        )

        created_audit = broker.list_audit(session_id="session-audit", limit=1)
        assert created_audit[0]["approval_id"] == pending.approval_id
        assert created_audit[0]["status"] == "pending"
        assert created_audit[0]["decision"] is None
        assert created_audit[0]["created_at"].endswith("Z")

        status = resolve_sandbox_approval(
            session_id="session-audit",
            approval_id=pending.approval_id,
            decision="approve",
            command_hash_value=pending.command_hash,
        )

        assert status == "resolved"
        resolved_audit = broker.list_audit(session_id="session-audit", limit=1)
        assert resolved_audit[0]["approval_id"] == pending.approval_id
        assert resolved_audit[0]["command"] == "git push origin feature-x"
        assert resolved_audit[0]["status"] == "resolved"
        assert resolved_audit[0]["decision"] == "approve"
        assert resolved_audit[0]["resolved_at"].endswith("Z")

    asyncio.run(run_flow())


def test_execute_shell_command_uses_one_shot_approval_before_spawn(monkeypatch):
    fake_sandbox = _FakeBackgroundSandbox("/sage-workspace")
    fake_manager = _FakeSessionManager(fake_sandbox)
    monkeypatch.setattr(ExecuteCommandTool, "_BG_TASKS", {})
    monkeypatch.setattr(ExecuteCommandTool, "_COMPLETION_EVENTS", {})
    monkeypatch.setattr(ExecuteCommandTool, "_PENDING_APPROVALS", {})

    import sagents.session_runtime

    monkeypatch.setattr(
        sagents.session_runtime,
        "get_global_session_manager",
        lambda: fake_manager,
    )

    tool = ExecuteCommandTool()
    blocked = asyncio.run(
        tool.execute_shell_command(
            command="git push origin feature-x",
            session_id="session-1",
            block_until_ms=0,
        )
    )
    approval_id = blocked["approval_id"]

    started = asyncio.run(
        tool.execute_shell_command(
            command="git push origin feature-x",
            session_id="session-1",
            block_until_ms=0,
            approval_id=approval_id,
        )
    )

    assert started["success"] is True
    assert started["status"] == "running"
    assert fake_sandbox.bg_calls[0]["command"] == "git push origin feature-x"
    assert ExecuteCommandTool._PENDING_APPROVALS == {}

    reused = asyncio.run(
        tool.execute_shell_command(
            command="git push origin feature-x",
            session_id="session-1",
            block_until_ms=0,
            approval_id=approval_id,
        )
    )
    assert reused["success"] is False
    assert reused["policy_action"] == "ask"
    assert reused["approval_id"] != approval_id


def test_execute_shell_command_approval_id_must_match_command(monkeypatch):
    monkeypatch.setattr(ExecuteCommandTool, "_BG_TASKS", {})
    monkeypatch.setattr(ExecuteCommandTool, "_COMPLETION_EVENTS", {})
    monkeypatch.setattr(ExecuteCommandTool, "_PENDING_APPROVALS", {})

    tool = ExecuteCommandTool()
    blocked = asyncio.run(
        tool.execute_shell_command(
            command="git push origin feature-x",
            session_id="session-1",
            block_until_ms=0,
        )
    )

    mismatch = asyncio.run(
        tool.execute_shell_command(
            command="git push origin other-branch",
            session_id="session-1",
            block_until_ms=0,
            approval_id=blocked["approval_id"],
        )
    )

    assert mismatch["success"] is False
    assert mismatch["policy_action"] == "ask"
    assert mismatch["approval_id"] != blocked["approval_id"]


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
            env_vars={  # pyright: ignore[reportArgumentType]
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


def test_background_shell_passes_virtual_workspace_log_dir_to_provider(
    monkeypatch, tmp_path
):
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
