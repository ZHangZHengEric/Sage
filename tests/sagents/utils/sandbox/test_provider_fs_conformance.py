"""Behavioral conformance tests for in-process sandbox providers.

`test_provider_interface_conformance.py` covers *structural* conformance
(subclassing, no abstract leftovers). This module covers *behavioral*
conformance: the same file-primitive scenario is run against every in-process
provider so their observable behavior cannot silently diverge.

Scope is intentionally limited to the providers that operate on the host
filesystem in-process (`Local`, `Passthrough`) — they run against ``tmp_path``
with no external services and stay within the unit-test budget. Remote
providers (`kubernetes`, `firecracker`, `opensandbox`) require a live sandbox
and are tracked as follow-up; the parametrization is structured so they can be
added behind an availability guard without reworking the test bodies.
"""

from __future__ import annotations

from typing import Callable

import pytest

from sagents.utils.sandbox.config import VolumeMount
from sagents.utils.sandbox.interface import ISandboxHandle
from sagents.utils.sandbox.providers.local.local import LocalSandboxProvider
from sagents.utils.sandbox.providers.passthrough.passthrough import (
    PassthroughSandboxProvider,
)


def _make_local(workspace) -> ISandboxHandle:
    return LocalSandboxProvider(
        sandbox_id="conformance",
        sandbox_agent_workspace=str(workspace),
        volume_mounts=[VolumeMount(str(workspace), str(workspace))],
        macos_isolation_mode="subprocess",
        linux_isolation_mode="subprocess",
    )


def _make_passthrough(workspace) -> ISandboxHandle:
    return PassthroughSandboxProvider(
        sandbox_id="conformance",
        sandbox_agent_workspace=str(workspace),
        volume_mounts=[VolumeMount(str(workspace), str(workspace))],
    )


# Each entry builds a provider rooted at a caller-supplied host workspace.
IN_PROCESS_PROVIDERS = [
    pytest.param(_make_local, id="local"),
    pytest.param(_make_passthrough, id="passthrough"),
]


@pytest.fixture(params=IN_PROCESS_PROVIDERS)
def provider_factory(request) -> Callable[[object], ISandboxHandle]:
    """Yield a ``workspace -> provider`` builder for each in-process provider."""
    return request.param


@pytest.fixture
def provider(provider_factory, tmp_path) -> ISandboxHandle:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    return provider_factory(workspace)


# --- write / read round-trip --------------------------------------------------


async def test_write_then_read_roundtrips(provider):
    await provider.write_file("notes.txt", "hello world\n")
    assert await provider.read_file("notes.txt") == "hello world\n"


async def test_write_preserves_non_ascii_utf8(provider):
    content = "中文 café \U0001f600\n"
    await provider.write_file("unicode.txt", content)
    assert await provider.read_file("unicode.txt") == content


async def test_write_creates_missing_parent_directories(provider):
    await provider.write_file("nested/deep/file.txt", "ok")
    assert await provider.read_file("nested/deep/file.txt") == "ok"


# --- append semantics ---------------------------------------------------------


async def test_append_mode_appends_to_existing_content(provider):
    await provider.write_file("log.txt", "first\n")
    await provider.write_file("log.txt", "second\n", mode="append")
    assert await provider.read_file("log.txt") == "first\nsecond\n"


async def test_append_mode_creates_file_when_missing(provider):
    await provider.write_file("fresh.txt", "only\n", mode="append")
    assert await provider.read_file("fresh.txt") == "only\n"


# --- existence ----------------------------------------------------------------


async def test_file_exists_true_for_written_file(provider):
    await provider.write_file("present.txt", "x")
    assert await provider.file_exists("present.txt") is True


async def test_file_exists_false_for_missing_file(provider):
    assert await provider.file_exists("nope.txt") is False


async def test_file_exists_true_for_directory(provider):
    await provider.ensure_directory("adir")
    assert await provider.file_exists("adir") is True


# --- error taxonomy -----------------------------------------------------------


async def test_read_missing_file_raises_file_not_found(provider):
    with pytest.raises(FileNotFoundError):
        await provider.read_file("absent.txt")


async def test_write_outside_workspace_raises_permission_error(provider, tmp_path):
    outside = tmp_path / "outside.txt"
    with pytest.raises(PermissionError):
        await provider.write_file(str(outside), "nope")
    assert not outside.exists()


async def test_parent_traversal_escape_is_rejected(provider, tmp_path):
    # workspace/../escape.txt resolves outside the mounted workspace.
    with pytest.raises(PermissionError):
        await provider.write_file("../escape.txt", "nope")
    assert not (tmp_path / "escape.txt").exists()


# --- delete -------------------------------------------------------------------


async def test_delete_removes_file(provider):
    await provider.write_file("temp.txt", "bye")
    await provider.delete_file("temp.txt")
    assert await provider.file_exists("temp.txt") is False
