"""Agent-scoped prompt and Skill ZIP synchronization for machine credentials."""

from __future__ import annotations

import asyncio
from pathlib import Path

from app.v2.server.skills.files import inspect_skill_zip
from app.v2.server.skills.records import normalize_skill_name
from app.v2.server.skills.workspaces import sync_workspaces
from sagents.v2.contracts.errors import SageV2Error

_LOCK = asyncio.Lock()
_MAX_PROMPT_BYTES = 128 * 1024


async def sync_agent_guidance(host, *, owner_id: str, agent_id: str, prompt: str,
                              files: list[tuple[str, bytes]]) -> dict:
    """Update the prompt, then report each Skill ZIP independently.

    The router authenticates the Agent-bound key. This service never accepts
    an owner or workspace path from the request body.
    """
    if not prompt.strip() or len(prompt.encode()) > _MAX_PROMPT_BYTES:
        raise ValueError("Agent prompt is empty or exceeds 128 KiB")
    if not files or len(files) > 32:
        raise ValueError("between 1 and 32 Skill ZIP files are required")

    async with _LOCK:
        agent = await host.catalog.get_agent(owner_id, agent_id)
        prompt_changed = agent["instructions"] != prompt
        if prompt_changed:
            await host.catalog.update_agent_instructions(owner_id, agent_id, prompt)
        results = []
        for filename, payload in files:
            try:
                result = await _sync_one_skill(host, owner_id=owner_id, agent_id=agent_id,
                                               filename=filename, payload=payload)
                results.append({"filename": filename, "success": True, **result})
            except SageV2Error as exc:
                results.append({"filename": filename, "success": False,
                                "message": exc.info.message})
            except (ValueError, OSError, RuntimeError) as exc:
                results.append({"filename": filename, "success": False,
                                "message": str(exc)[:200]})
            except Exception:
                results.append({"filename": filename, "success": False,
                                "message": "Skill synchronization failed"})
        return {"prompt_changed": prompt_changed, "results": results,
                "success_count": sum(item["success"] for item in results),
                "failed_count": sum(not item["success"] for item in results)}


async def _sync_one_skill(host, *, owner_id: str, agent_id: str,
                          filename: str, payload: bytes) -> dict:
    if not filename.lower().endswith(".zip"):
        raise ValueError("Skill file must be a ZIP")
    package = inspect_skill_zip(payload, filename=filename)
    name = normalize_skill_name(package.name)
    agent = await host.catalog.get_agent(owner_id, agent_id)
    catalog = await host.catalog.get(owner_id)
    if any(other.id != agent_id and name in other.skills for other in catalog.agents):
        raise ValueError("Skill is shared with another Agent")
    visible = await host.skill_catalog.list_visible(user_id=owner_id, role="user")
    previous = next((item for item in visible if item.name == name and item.owner_user_id == owner_id), None)
    record = await host.skill_catalog.publish_zip(payload, filename=filename,
                                                  user_id=owner_id, role="user")
    if name not in agent["skills"]:
        await host.catalog.bind_agent_skills(owner_id, agent_id, [*agent["skills"], name])
    workspace = await asyncio.to_thread(sync_workspaces, Path(host.paths.data_root), agent_id,
                                         {name: package.files})
    current = await host.catalog.get_agent(owner_id, agent_id)
    if name not in current["skills"] or record.package_sha256 != package.package_sha256:
        raise RuntimeError("Skill synchronization verification failed")
    return {"name": name, "changed": previous is None or previous.version_id != record.version_id
            or name not in agent["skills"] or workspace["changed_workspaces"] > 0,
            "workspaces": workspace["workspaces"]}
