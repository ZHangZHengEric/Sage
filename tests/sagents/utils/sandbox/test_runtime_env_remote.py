from types import SimpleNamespace
import sys

import pytest

from sagents.utils.sandbox.providers.remote.kubernetes import (
    KubernetesSandboxProvider,
)
from sagents.utils.sandbox.providers.remote.opensandbox import OpenSandboxProvider


@pytest.mark.asyncio
async def test_opensandbox_command_runtime_env_overrides_tool_env():
    captured = {}

    class Commands:
        async def run(self, command, *, timeout, env):
            captured.update(command=command, timeout=timeout, env=env)
            return SimpleNamespace(
                exit_code=0,
                logs=SimpleNamespace(stdout=[], stderr=[]),
                duration=0,
            )

    class SDK:
        commands = Commands()

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return False

    provider = OpenSandboxProvider(
        sandbox_id="sandbox",
        server_url="https://sandbox.invalid",
    )
    provider._sdk = SDK()
    provider._is_initialized = True
    provider.set_runtime_env_vars({"TOKEN": "api-owned"})

    result = await provider.execute_command(
        "printenv TOKEN",
        env_vars={"TOKEN": "tool-owned", "MODEL_ONLY": "value"},
    )

    assert result.success is True
    assert captured["env"] == {
        "TOKEN": "api-owned",
        "MODEL_ONLY": "value",
    }


@pytest.mark.asyncio
async def test_kubernetes_runtime_env_uses_stdin_not_exec_argv(monkeypatch):
    captured = {}

    class WebSocket:
        returncode = 0

        def __init__(self):
            self.open = True
            self.stdin = ""

        def write_stdin(self, value):
            self.stdin += value

        def close_stdin(self):
            self.open = False

        def is_open(self):
            return self.open

        def update(self, timeout):
            self.open = False

        def read_stdout(self):
            return "ok"

        def read_stderr(self):
            return ""

        def close(self):
            self.open = False

    websocket = WebSocket()

    def fake_stream(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return websocket

    monkeypatch.setitem(
        sys.modules,
        "kubernetes",
        SimpleNamespace(stream=SimpleNamespace(stream=fake_stream)),
    )
    provider = KubernetesSandboxProvider("sandbox")
    provider._is_initialized = True
    provider._k8s_client = SimpleNamespace(
        connect_get_namespaced_pod_exec=object()
    )
    provider._pod_name = "pod"
    provider.set_runtime_env_vars({"TOKEN": "very-secret-value"})

    result = await provider.execute_command("printenv TOKEN")

    assert result.success is True
    assert "very-secret-value" not in repr(captured["kwargs"]["command"])
    assert "very-secret-value" in websocket.stdin
    assert captured["kwargs"]["stdin"] is True
    assert captured["kwargs"]["_preload_content"] is False


@pytest.mark.asyncio
async def test_opensandbox_maps_logical_session_digest_to_physical_sdk_id(
    monkeypatch,
):
    calls = []

    class SDK:
        def __init__(self, sandbox_id):
            self.id = sandbox_id

    class Sandbox:
        @classmethod
        async def get(cls, sandbox_id, **kwargs):
            calls.append(("get", sandbox_id))
            if sandbox_id != "physical-id":
                raise RuntimeError("not found")
            return SDK(sandbox_id)

        @classmethod
        async def create(cls, **kwargs):
            calls.append(("create", kwargs.get("labels")))
            return SDK("physical-id")

    monkeypatch.setitem(
        sys.modules,
        "opensandbox",
        SimpleNamespace(Sandbox=Sandbox),
    )
    monkeypatch.setitem(
        sys.modules,
        "opensandbox.models",
        SimpleNamespace(Mount=object),
    )
    OpenSandboxProvider._REMOTE_IDS.clear()

    first = OpenSandboxProvider(
        sandbox_id="sage-session-logical",
        server_url="https://sandbox.invalid",
    )
    await first.initialize()

    second = OpenSandboxProvider(
        sandbox_id="sage-session-logical",
        server_url="https://sandbox.invalid",
    )
    await second.initialize()

    assert first.sandbox_id == "sage-session-logical"
    assert first.remote_sandbox_id == "physical-id"
    assert second.remote_sandbox_id == "physical-id"
    assert calls == [
        ("create", {"sandbox_id": "sage-session-logical", "persistent": "True"}),
        ("get", "physical-id"),
    ]
