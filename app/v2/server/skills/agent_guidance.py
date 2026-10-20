"""Agent-scoped prompt and bound/ZIP Skill synchronization."""

from __future__ import annotations

import asyncio
from pathlib import Path

from app.v2.server.skills.files import (
    finish_skill_write,
    inspect_skill_directory,
    inspect_skill_zip,
    skill_io,
)
from app.v2.server.skills.records import normalize_skill_name
from app.v2.server.skills.workspaces import discover_agent_workspaces, sync_workspaces
from sagents.v2.contracts.errors import SageV2Error

_MAX_PROMPT_BYTES = 128 * 1024


def _lock(locks, key: tuple[str, str]) -> asyncio.Lock:
    # The catalog service belongs to one host/event loop. Weak entries disappear
    # after the holder and any waiters finish.
    lock = locks.get(key)
    if lock is None:
        locks[key] = lock = asyncio.Lock()
    return lock


def _failure(exc: Exception) -> dict:
    if isinstance(exc, SageV2Error):
        message = exc.info.message
    elif isinstance(exc, (ValueError, OSError, RuntimeError)):
        message = str(exc)[:200]
    else:
        message = "Skill synchronization failed"
    return {"success": False, "message": message}


def _response(prompt_changed: bool, results: list[dict]) -> dict:
    return {"prompt_changed": prompt_changed, "results": results,
            "success_count": sum(item["success"] for item in results),
            "failed_count": sum(not item["success"] for item in results)}


async def sync_bound_agent_skills(host, *, owner_id: str, agent_id: str) -> dict:
    """Sync current catalog versions of saved bindings without changing the Agent."""
    async with _lock(host.skill_catalog.guidance_locks, (owner_id, agent_id)):
        await host.catalog.get_agent(owner_id, agent_id)
        records = await host.skill_catalog.bound_skills(owner_user_id=owner_id, agent_id=agent_id)
        try:
            tenants = await skill_io(discover_agent_workspaces, Path(host.paths.data_root), agent_id)
        except Exception as exc:
            return _response(False, [{"name": record.name, **_failure(exc)} for record in records])
        results = []
        for record in records:
            try:
                result = await _sync_bound_skill(host, record, agent_id, tenants)
                results.append({"name": record.name, "success": True, **result})
            except Exception as exc:
                results.append({"name": record.name, **_failure(exc)})
        return _response(False, results)


async def _sync_bound_skill(host, record, agent_id: str, tenants: tuple[str, ...]) -> dict:
    package = await skill_io(lambda: inspect_skill_directory(record.absolute_path(host.paths.data_root)))
    if package.package_sha256 != record.package_sha256:
        raise ValueError("Skill artifact no longer matches its catalog version")
    workspace = await finish_skill_write(
        sync_workspaces, Path(host.paths.data_root), agent_id, {record.name: package.files}, tenants=tenants,
    )
    return {"changed": workspace["changed_workspaces"] > 0, "workspaces": workspace["workspaces"]}


async def sync_agent_guidance(host, *, owner_id: str, agent_id: str, prompt: str,
                              files: list[tuple[str, bytes]]) -> dict:
    """Update the prompt, then report each Skill ZIP independently.

    The router resolves the Agent owner from the catalog. This service never
    accepts an owner or workspace path from the request body.
    """
    if not prompt.strip() or len(prompt.encode()) > _MAX_PROMPT_BYTES:
        raise ValueError("Agent prompt is empty or exceeds 128 KiB")
    if not files or len(files) > 32:
        raise ValueError("between 1 and 32 Skill ZIP files are required")

    async with _lock(host.skill_catalog.guidance_locks, (owner_id, agent_id)):
        agent = await host.catalog.get_agent(owner_id, agent_id)
        prompt_changed = agent["instructions"] != prompt
        if prompt_changed:
            await host.catalog.update_agent_instructions(owner_id, agent_id, prompt)
        try:
            tenants = await skill_io(discover_agent_workspaces, Path(host.paths.data_root), agent_id)
        except Exception as exc:
            return _response(prompt_changed, [{"filename": filename, **_failure(exc)} for filename, _ in files])
        results = []
        for filename, payload in files:
            try:
                result = await _sync_one_skill(
                    host, owner_id=owner_id, agent_id=agent_id, filename=filename, payload=payload, tenants=tenants,
                )
                results.append({"filename": filename, "success": True, **result})
            except Exception as exc:
                results.append({"filename": filename, **_failure(exc)})
        return _response(prompt_changed, results)


async def _sync_one_skill(host, *, owner_id: str, agent_id: str,
                          filename: str, payload: bytes, tenants: tuple[str, ...]) -> dict:
    if not filename.lower().endswith(".zip"):
        raise ValueError("Skill file must be a ZIP")
    package = await skill_io(inspect_skill_zip, payload, filename=filename)
    name = normalize_skill_name(package.name)
    # Different Agents may update different Skills concurrently. For one owner's
    # same Skill, keep the shared-binding check and publish/bind indivisible.
    async with _lock(host.skill_catalog.guidance_skill_locks, (owner_id, name)):
        agent = await host.catalog.get_agent(owner_id, agent_id)
        catalog = await host.catalog.get(owner_id)
        if any(other.id != agent_id and name in other.skills for other in catalog.agents):
            raise ValueError("Skill is shared with another Agent")
        visible = await host.skill_catalog.list_visible(user_id=owner_id, role="user")
        previous = next((item for item in visible if item.name == name and item.owner_user_id == owner_id), None)
        record = await host.skill_catalog.publish_package(package, owner_user_id=owner_id)
        if name not in agent["skills"]:
            await host.catalog.bind_agent_skills(owner_id, agent_id, [*agent["skills"], name])
    workspace = await finish_skill_write(
        sync_workspaces, Path(host.paths.data_root), agent_id, {name: package.files}, tenants=tenants,
    )
    current = await host.catalog.get_agent(owner_id, agent_id)
    if name not in current["skills"] or record.package_sha256 != package.package_sha256:
        raise RuntimeError("Skill synchronization verification failed")
    return {"name": name, "changed": previous is None or previous.version_id != record.version_id
            or name not in agent["skills"] or workspace["changed_workspaces"] > 0,
            "workspaces": workspace["workspaces"]}
