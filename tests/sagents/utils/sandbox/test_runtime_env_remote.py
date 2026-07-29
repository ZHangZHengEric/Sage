from types import SimpleNamespace

import pytest

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
