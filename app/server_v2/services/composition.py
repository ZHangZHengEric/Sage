"""Freeze what a Run is composed from at admission time.

A Run is admitted against one Agent, one set of immutable Skill versions and
one set of MCP servers. Composition happens later — after queueing, and again
after a suspend — so reading the live catalog at that point would execute a
different Agent than the caller was admitted for, with no record that it
changed.

The admitted configuration is therefore serialized into ``RunConfig.metadata``
and replayed verbatim. Credentials are deliberately excluded: model and MCP
records are re-resolved from the live catalog by the frozen id/name, so a
rotated key takes effect and no secret is written into the Run store.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from sagents.v2.contracts.commands import StartRun
from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo, SageV2Error

from app.server_v2.core.errors import ServerV2Error
from app.server_v2.domain.catalog import AgentRecord, McpServerRecord, UserCatalog
from app.server_v2.domain.skills import (
    SkillRecord,
    artifact_relative_path,
    normalize_skill_name,
)

RUN_COMPOSITION_METADATA_KEY = "server_v2.composition"


@dataclass(frozen=True)
class RunComposition:
    """The Agent, Skill versions and MCP servers a Run was admitted with."""

    agent: AgentRecord
    skills: tuple[SkillRecord, ...]
    mcp_servers: tuple[str, ...]


def composition_metadata(
    *,
    agent: AgentRecord,
    skills: tuple[SkillRecord, ...],
    mcp_servers: tuple[str, ...],
) -> dict[str, object]:
    """Serialize the composition admitted with a Run into Run metadata."""

    return {
        RUN_COMPOSITION_METADATA_KEY: {
            "agent": agent.model_dump(mode="json"),
            "skills": [asdict(record) for record in skills],
            "mcp_servers": list(mcp_servers),
        }
    }


def load_composition(command: StartRun, *, user_id: str) -> RunComposition | None:
    """Rebuild the frozen composition, or ``None`` for a Run without one."""

    raw = command.config.metadata.get(RUN_COMPOSITION_METADATA_KEY)
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise _invalid("run composition must be an object")
    try:
        agent = AgentRecord.model_validate(raw.get("agent"))
        skills = _skills(raw.get("skills"), user_id=user_id)
        mcp_servers = _names(raw.get("mcp_servers"))
    except (ServerV2Error, TypeError, ValueError) as exc:
        raise _invalid(str(exc)) from exc
    if agent.id != command.agent_id:
        raise _invalid("run composition does not match the Run agent")
    enabled = command.config.enabled_skills
    if enabled is None or tuple(record.name for record in skills) != tuple(enabled):
        raise _invalid("run composition does not match the Run Skill grant")
    return RunComposition(agent=agent, skills=skills, mcp_servers=mcp_servers)


def selected_mcp_servers(
    catalog: UserCatalog, names: tuple[str, ...]
) -> list[McpServerRecord]:
    """Resolve frozen server names against the live catalog, for credentials.

    A server removed or disabled since admission simply drops out: the Run
    loses those Tools rather than failing, which matches how the catalog
    already treats a disabled server.
    """

    wanted = set(names)
    return [
        item
        for item in catalog.mcp_servers
        if not item.disabled and item.name in wanted
    ]


def _skills(raw: object, *, user_id: str) -> tuple[SkillRecord, ...]:
    if not isinstance(raw, list):
        raise TypeError("skill snapshot must be a list")
    records: list[SkillRecord] = []
    for value in raw:
        if not isinstance(value, dict):
            raise TypeError("skill snapshot entries must be objects")
        record = SkillRecord(**value)
        normalize_skill_name(record.name)
        if record.dimension not in {"system", "user"}:
            raise ValueError(f"invalid skill dimension: {record.dimension!r}")
        if record.dimension == "user" and record.owner_user_id != user_id:
            raise ValueError(f"skill {record.name!r} belongs to another user")
        expected_path = artifact_relative_path(
            dimension=record.dimension,
            owner_user_id=record.owner_user_id,
            name=record.name,
            version_id=record.version_id,
        )
        if record.artifact_path != expected_path:
            raise ValueError(f"skill {record.name!r} has an invalid artifact path")
        records.append(record)
    return tuple(records)


def _names(raw: object) -> tuple[str, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list) or any(not isinstance(item, str) for item in raw):
        raise TypeError("mcp server snapshot must be a list of names")
    return tuple(raw)


def _invalid(message: str) -> SageV2Error:
    return SageV2Error(
        RuntimeErrorInfo(
            code="run.composition_invalid",
            category=ErrorCategory.VALIDATION,
            message=message,
            safe_to_resume=False,
        )
    )
