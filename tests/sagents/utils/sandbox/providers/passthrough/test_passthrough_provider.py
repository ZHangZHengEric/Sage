import asyncio
import os
import sys
from unittest.mock import patch

import pytest

from sagents.utils.sandbox.providers.passthrough.passthrough import (
    PassthroughSandboxProvider,
)


@pytest.fixture
def provider(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    return PassthroughSandboxProvider(
        sandbox_id="test-sandbox",
        sandbox_agent_workspace=str(workspace),
    )


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_execute_command_accepts_workdir_and_env_vars(provider):
    result = await provider.execute_command(
        command=f'{sys.executable} -c "import os; print(os.getenv(\'TEST_KEY\', \'\'))"',
        workdir=provider.workspace_path,
        env_vars={"TEST_KEY": "hello"},
        timeout=10,
    )

    assert result.success is True
    assert result.stdout.strip() == "hello"


@pytest.mark.anyio
async def test_write_file_supports_overwrite_and_append(provider):
    target = os.path.join(provider.workspace_path, "notes.txt")

    await provider.write_file(target, "first", mode="overwrite")
    await provider.write_file(target, "\nsecond", mode="append")

    content = await provider.read_file(target)
    assert content == "first\nsecond"


@pytest.mark.anyio
async def test_list_directory_respects_include_hidden(provider):
    await provider.write_file(os.path.join(provider.workspace_path, "visible.txt"), "ok")
    await provider.write_file(os.path.join(provider.workspace_path, ".hidden.txt"), "secret")

    visible_entries = await provider.list_directory(provider.workspace_path)
    all_entries = await provider.list_directory(provider.workspace_path, include_hidden=True)

    visible_paths = {os.path.basename(entry.path) for entry in visible_entries}
    all_paths = {os.path.basename(entry.path) for entry in all_entries}

    assert "visible.txt" in visible_paths
    assert ".hidden.txt" not in visible_paths
    assert ".hidden.txt" in all_paths
    assert all(entry.path.startswith(provider.workspace_path) for entry in all_entries)


@pytest.mark.anyio
async def test_execute_python_returns_unified_execution_result(provider):
    result = await provider.execute_python(
        code="print('py-ok')",
        workdir=provider.workspace_path,
        timeout=10,
    )

    assert result.success is True
    assert result.output.strip() == "py-ok"
    assert result.error is None
    assert result.installed_packages == []


@pytest.mark.anyio
async def test_execute_javascript_returns_clean_error_when_node_missing(provider):
    original = asyncio.create_subprocess_exec

    async def fake_create_subprocess_exec(*args, **kwargs):
        if args and args[0] == "node":
            raise FileNotFoundError("node not found")
        return await original(*args, **kwargs)

    with patch("asyncio.create_subprocess_exec", side_effect=fake_create_subprocess_exec):
        result = await provider.execute_javascript(
            code="console.log('js-ok')",
            workdir=provider.workspace_path,
            timeout=10,
        )

    assert result.success is False
    assert result.output == ""
    assert "Node.js not found" in (result.error or "")
    assert result.installed_packages == []


@pytest.mark.anyio
async def test_file_info_paths_are_usable_for_matching_and_deletion(provider):
    target = os.path.join(provider.workspace_path, "delete-me.txt")
    await provider.write_file(target, "bye")

    entries = await provider.list_directory(provider.workspace_path)
    matching = next(entry for entry in entries if os.path.basename(entry.path) == "delete-me.txt")

    assert matching.is_file is True
    await provider.delete_file(matching.path)
    assert await provider.file_exists(target) is False
