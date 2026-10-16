"""Frontend runtime access must retain the Server's workspace/network boundary."""

from app.v2.server.runtime.official import workspace_sandbox_spec
from sagents.v2.runtime.execution.sandbox import NetworkMode


def test_frontend_commands_and_paths_preserve_offline_workspace_policy(tmp_path):
    spec = workspace_sandbox_spec(tmp_path)
    assert {"node", "sage-frontend-test"} <= set(spec.process.allowed_executables)
    assert {"NODE_PATH", "PLAYWRIGHT_BROWSERS_PATH", "FONTCONFIG_FILE"} <= set(
        spec.process.allowed_env_names
    )
    assert "npm" not in spec.process.allowed_executables
    assert "npx" not in spec.process.allowed_executables
    assert "LD_PRELOAD" not in spec.process.allowed_env_names
    assert spec.filesystem.allowed_roots == ("/workspace",)
    assert spec.network.mode == NetworkMode.NONE
