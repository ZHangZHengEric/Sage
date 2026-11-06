from dataclasses import replace

import pytest

from app.v2.server.runtime.sdk_plugins import execution_selection
from tests.app.v2.server.conftest import make_settings


def test_cube_is_opt_in_and_requires_explicit_backend_configuration(tmp_path):
    settings = make_settings(tmp_path)
    assert settings.sandbox_plugin == "sage.sandbox.local-workspace"
    with pytest.raises(ValueError, match="Cube"):
        replace(settings, sandbox_plugin="sage.sandbox.cube-volume")


def test_cube_selection_contains_no_host_workspace_or_secret(tmp_path):
    from types import SimpleNamespace
    from sagents.v2.package.manifest.agents import AgentSandboxConfig

    settings = make_settings(
        tmp_path,
        sandbox_plugin="sage.sandbox.cube-volume",
        cube_api_url="http://cube:3000",
        cube_template_id="python",
        cube_proxy_node_ip="cube",
        cube_api_key="must-not-be-in-the-run",
    )
    host = SimpleNamespace(settings=settings)
    selection = execution_selection(
        host,
        owner="alice",
        agent_id="agent",
        command=None,
        sandbox=AgentSandboxConfig(network="unrestricted"),
    )
    assert selection.plugin == "com.sage.server.execution-binding.cube-volume"
    assert "must-not-be-in-the-run" not in str(selection.config)
    assert "workspace" not in selection.config
    assert selection.config["policy"]["network"]["mode"] == "unrestricted"
