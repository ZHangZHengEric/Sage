"""Verify the process policy actually selected by standard Server Run loading."""

from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from importlib.abc import Loader
    from importlib.machinery import ModuleSpec

from importlib.abc import Loader

from types import SimpleNamespace

from app.v2.server.runtime.sdk_plugins import execution_selection
from sagents.v2.package.manifest.agents import AgentSandboxConfig
from app.v2.server.runtime.workspace_binding import ServerExecutionBindingConfig as LocalExecutionBindingConfig
from tests.app.v2.server.conftest import make_settings


def test_frontend_commands_and_paths_preserve_offline_workspace_policy(tmp_path):
    settings = make_settings(tmp_path)
    host = SimpleNamespace(settings=settings, paths=SimpleNamespace(workspace_dir=lambda user, agent: tmp_path / user / agent))
    selected = execution_selection(host, owner="owner", agent_id="agent", command=None, sandbox=AgentSandboxConfig())
    config = LocalExecutionBindingConfig.model_validate(selected.config)
    assert config.workspace_alias == "/workspace"
    assert {"node", "sage-frontend-test"} <= set(config.policy.process.allowed_executables)
    assert {"NODE_PATH", "PLAYWRIGHT_BROWSERS_PATH", "FONTCONFIG_FILE"} <= set(config.policy.process.allowed_env_names)
    assert "npm" not in config.policy.process.allowed_executables
    assert "npx" not in config.policy.process.allowed_executables
    assert "LD_PRELOAD" not in config.policy.process.allowed_env_names
    assert config.policy.filesystem.allowed_roots == ("/workspace",)
    assert config.policy.network.mode.value == "none"


def test_explicit_process_policy_replaces_product_defaults(tmp_path):
    settings = make_settings(tmp_path, plugin_overrides={"execution.binding": {"config": {"policy": {
        "process": {"allowed_executables": ["python3"], "max_wall_time_seconds": 7200},
        "resources": {"disk_mb": 32768, "require_hard_limits": False},
    }}}})
    host = SimpleNamespace(settings=settings, paths=SimpleNamespace(workspace_dir=lambda user, agent: tmp_path / user / agent))
    selected = execution_selection(host, owner="owner", agent_id="agent", command=None, sandbox=AgentSandboxConfig())
    config = LocalExecutionBindingConfig.model_validate(selected.config)
    assert config.policy.process.allowed_executables == ("python3",)
    assert config.policy.process.max_wall_time_seconds == 7200
    assert config.policy.filesystem.max_total_bytes == 32768 * 1024**2


async def test_image_acceptance_collects_actual_standard_tool_receipts(tmp_path, monkeypatch):
    """Exercise runner plumbing locally; Linux browser behavior is a separate gate."""
    import importlib.util
    import json
    from pathlib import Path

    path = Path(__file__).resolve().parents[4] / "deploy/images/frontend-test/acceptance.py"
    spec = importlib.util.spec_from_file_location("frontend_acceptance", path)
    module = importlib.util.module_from_spec(cast('ModuleSpec', spec))
    cast('Loader', cast('ModuleSpec', spec).loader).exec_module(module)
    monkeypatch.setattr(module.tempfile, "mkdtemp", lambda **kwargs: str(tmp_path))
    join = module.shlex.join
    def local_command(argv):
        # This test verifies SDK receipt collection; real Node/browser probes
        # run in the candidate Linux image, independent of host installations.
        return join(("bash", "-c", "printf '%s\\n' \"$1\"", "plumbing", join(argv)))
    monkeypatch.setattr(module.shlex, "join", local_command)
    assert await module.main() == 0
    summary = json.loads((tmp_path / "acceptance.json").read_text())
    assert summary["state"] == "completed"
    assert len(summary["checks"]) == 5
    assert all(result["passed"] for result in summary["checks"].values())
    assert summary["diagnostics"]["sandbox"]["owner_run_id"] == summary["run_id"]
    assert summary["checks"]["file_api_boundary"]["receipt"]["error"]
