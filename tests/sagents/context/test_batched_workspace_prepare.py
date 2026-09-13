import asyncio
import threading
from pathlib import Path
from unittest.mock import patch

import pytest

from sagents.context.session_context import SessionContext
from sagents.utils.sandbox.config import VolumeMount
from sagents.utils.sandbox.providers.local.local import LocalSandboxProvider


class SeparateCalls(LocalSandboxProvider):
    """Use the original provider-independent session preparation path."""


def provider_at(root, cls=LocalSandboxProvider):
    root.mkdir(exist_ok=True)
    return cls(
        sandbox_id="batch-test",
        sandbox_agent_workspace=str(root),
        volume_mounts=[VolumeMount(str(root), str(root))],
        macos_isolation_mode="subprocess",
        linux_isolation_mode="subprocess",
    )


def context_at(root, provider):
    ctx = object.__new__(SessionContext)
    ctx.sandbox = provider
    ctx.sandbox_agent_workspace = str(root)
    ctx.system_context = {"use_claw_mode": True}
    ctx.user_id = "user"
    ctx.session_id = "session"
    ctx.external_paths = []
    ctx._get_default_md_content = lambda key, filename: "default " + filename
    return ctx


def test_existing_and_new_workspace_match_original_with_fewer_worker_handoffs(tmp_path):
    results, jobs = [], []
    for cls in (SeparateCalls, LocalSandboxProvider):
        root = tmp_path / cls.__name__
        provider = provider_at(root, cls)
        (root / "USER.md").write_text("keep user changes")
        ctx = context_at(root, provider)
        names = []

        async def counted(name, fn, *args, **kwargs):
            names.append(name)
            return await asyncio.to_thread(fn, *args, **kwargs)

        async def run():
            await provider.initialize()
            names.clear()
            with (
                patch("sagents.context.session_context.diagnostic_to_thread", counted),
                patch(
                    "sagents.utils.sandbox.providers.local.local.diagnostic_to_thread",
                    counted,
                ),
            ):
                await ctx._prepare_workspace_bootstrap_files()
                await ctx._finalize_system_context()
                first = len(names)
                names.clear()
                await ctx._prepare_workspace_bootstrap_files()
                await ctx._finalize_system_context()
                return first, len(names)

        jobs.append(asyncio.run(run()))
        results.append(
            {
                str(p.relative_to(root)): p.read_text() if p.is_file() else None
                for p in root.rglob("*")
            }
        )
    assert results[0] == results[1]
    assert results[1]["USER.md"] == "keep user changes"
    assert jobs == [(14, 10), (2, 2)]


def test_batch_checks_permissions_off_loop_and_continues_after_bad_bootstrap_file(
    tmp_path,
):
    root, outside = tmp_path / "root", tmp_path / "outside"
    outside.mkdir()
    secret = outside / "AGENT.md"
    secret.write_text("outside")
    provider = provider_at(root)
    (root / "AGENT.md").symlink_to(secret)
    ctx = context_at(root, provider)
    loop_thread = threading.get_ident()
    checked = []
    original = provider._validate_host_path_allowed

    def check(*args, **kwargs):
        checked.append(threading.get_ident())
        return original(*args, **kwargs)

    async def run():
        await provider.initialize()
        with patch.object(provider, "_validate_host_path_allowed", check):
            await ctx._prepare_workspace_bootstrap_files()
            with pytest.raises(PermissionError):
                await provider.ensure_directories(
                    [str(root / "first"), str(outside / "denied"), str(root / "last")]
                )

    asyncio.run(run())
    assert checked and all(t != loop_thread for t in checked)
    assert secret.read_text() == "outside"
    assert (root / "USER.md").read_text() == "default USER.md"
    assert (root / "memory").is_dir() and (root / "first").is_dir()
    assert not (outside / "denied").exists() and not (root / "last").exists()
