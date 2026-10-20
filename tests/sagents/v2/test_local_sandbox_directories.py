from __future__ import annotations

import json
import sys
from types import SimpleNamespace
from pathlib import Path

import pytest

from sagents.v2.context.sandbox_environment import SandboxEnvironmentContextProvider
from sagents.v2.contracts.errors import SageV2Error
from sagents.v2.runtime.execution.sandbox.plugins.local.support.paths import LocalSandboxPaths
from tests.sagents.v2.test_official_tool_provider_matrix import (
    plugin_for,
    call,
    CONTEXT,
)


@pytest.mark.parametrize("platform", ["linux", "darwin"])
def test_runtime_directory_mapping_round_trips_without_host_environment(
    tmp_path, monkeypatch, platform
):
    monkeypatch.setenv("HOME", "/private-host-home")
    monkeypatch.setenv("TMPDIR", "/private-host-tmp")
    paths = LocalSandboxPaths(tmp_path, "/workspace", platform)
    for alias, host in (
        ("~/a", paths.home / "a"),
        ("$HOME/a", paths.home / "a"),
        ("${TMPDIR}/a", paths.temporary / "a"),
        ("$XDG_CACHE_HOME/a", paths.home / ".cache/a"),
    ):
        assert paths.host_path(alias) == host
        assert paths.host_path(paths.wire_path(host)) == host
    if platform == "linux":
        assert (
            paths.host_path("/tmp/a")
            == paths.host_path("/var/tmp/a")
            == paths.temporary / "a"
        )
        assert paths.environment["HOME"] == "/home/agent"
        assert paths.host_path("/tmp/../workspace/a") == tmp_path / "a"
        assert paths.host_path("/tmp/../etc/passwd") == Path("/etc/passwd")
    else:
        assert paths.host_path("/tmp/a") == Path("/tmp/a")
        assert paths.environment["HOME"] == str(paths.home)
    assert paths.home != paths.temporary


@pytest.mark.asyncio
async def test_runtime_directories_work_through_official_file_tools_and_context(
    tmp_path,
):
    plugin = await plugin_for(tmp_path)
    for index, prefix in enumerate(
        (
            "$TMPDIR",
            "~",
            "${XDG_CACHE_HOME}",
            "$XDG_CONFIG_HOME",
            "$XDG_DATA_HOME",
            "$XDG_STATE_HOME",
        )
    ):
        path = f"{prefix}/probe.txt"
        await plugin.executor.execute(
            call("file_write", {"file_path": path, "content": prefix}, index=index * 2),
            CONTEXT,
        )
        result = await plugin.executor.execute(
            call("file_read", {"file_path": path}, index=index * 2 + 1), CONTEXT
        )
        assert prefix in str(result.content)
    description = plugin.runtime.sandbox.describe_environment()
    segments = await SandboxEnvironmentContextProvider(plugin.runtime.sandbox).segments(
        None
    )
    assert len(segments) == 1
    for name, value in description["environment"].items():
        assert name in segments[0].content and value in segments[0].content
    assert description["os"] == sys.platform
    assert "not a VM" in segments[0].content
    assert description["environment"]["HOME"] != description["environment"]["TMPDIR"]
    with pytest.raises(SageV2Error):
        await plugin.executor.execute(
            call(
                "file_write",
                {"file_path": "$HOME/../../escape", "content": "x"},
                index=99,
            ),
            CONTEXT,
        )
    await plugin.executor.release_run("run_1")


@pytest.mark.asyncio
async def test_shell_and_file_tools_share_temp_home_cache_and_cwd(tmp_path):
    plugin = await plugin_for(tmp_path)
    command = """python -c 'import json, os, tempfile; from pathlib import Path
print(json.dumps({k: os.environ[k] for k in ["HOME", "TMPDIR", "TMP", "TEMP", "XDG_CACHE_HOME"]}))
for key in ["HOME", "TMPDIR", "XDG_CACHE_HOME"]: (Path(os.environ[key]) / "shell.txt").write_text(key)
print(tempfile.gettempdir())'
"""
    try:
        result = await plugin.executor.execute(
            call(
                "execute_shell_command",
                {
                    "command": command,
                    "block_until_ms": 5000,
                },
            ),
            CONTEXT,
        )
        output = result.content[0].value
        assert output["success"], output
        values = json.loads(output["stdout"].splitlines()[0])
        assert values == {
            k: plugin.runtime.sandbox.describe_environment()["environment"][k]
            for k in values
        }
        for index, key in enumerate(("HOME", "TMPDIR", "XDG_CACHE_HOME")):
            read = await plugin.executor.execute(
                call(
                    "file_read",
                    {
                        "file_path": values[key] + "/shell.txt",
                    },
                    index=index + 2,
                ),
                CONTEXT,
            )
            assert key in str(read.content)
        # Canonical paths returned by file tools are directly usable by Shell.
        path = plugin.runtime.virtual_path("$HOME")
        cwd = await plugin.executor.execute(
            call(
                "execute_shell_command",
                {
                    "command": "pwd",
                    "workdir": path,
                    "block_until_ms": 5000,
                },
                index=9,
            ),
            CONTEXT,
        )
        assert cwd.content[0].value["success"]
    finally:
        await plugin.executor.release_run("run_1")


@pytest.mark.asyncio
async def test_environment_context_is_optional_for_other_sandbox_plugins():
    assert (
        await SandboxEnvironmentContextProvider(SimpleNamespace()).segments(None) == ()
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "directory",
    [".sage-sandbox-tmp", ".sage-sandbox-home", ".sage-sandbox-home/.cache"],
)
async def test_runtime_directory_symlink_does_not_expose_host_storage(
    tmp_path, directory
):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "sentinel").write_text("unchanged")
    link = workspace / directory
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(outside, target_is_directory=True)
    with pytest.raises(PermissionError, match="symlink"):
        await plugin_for(workspace)
    assert (outside / "sentinel").read_text() == "unchanged"
    assert sorted(p.name for p in outside.iterdir()) == ["sentinel"]
