from __future__ import annotations

import asyncio
import hashlib
import posixpath
import shutil
import tempfile
from pathlib import Path
from typing import Any

from sagents.v2.agent.multi_agent import AgentMode, AgentRegistry
from sagents.v2.context import ContextSegment, ContextStability
from sagents.v2.contracts.commands import StartRun
from sagents.v2.runtime.execution.sandbox import (
    FileOperation,
    OperationIntent,
    SandboxGrantIssuer,
    SandboxHandle,
)
from sagents.v2.skill.contracts import SkillBundle


def _virtual_workspace_root(value: Any) -> str:
    raw = str(value or "/workspace").strip().replace("\\", "/")
    normalized = posixpath.normpath(raw)
    if not normalized.startswith("/") or normalized == "/" or ".." in raw.split("/"):
        raise ValueError("sandbox workspace_root must be a contained absolute path")
    return normalized


class LocalSkillWorkspace:
    """Materialize exactly one Skill after an explicit load_skill call."""

    def __init__(self, root: Path, *, workspace_root: str = "/workspace") -> None:
        self.root = root.resolve()
        self.workspace_root = _virtual_workspace_root(workspace_root)
        self._lock = asyncio.Lock()

    async def materialize(
        self, bundle: SkillBundle, *, run_id: str, destination: str
    ) -> str:
        del run_id
        prefix = self.workspace_root.rstrip("/") + "/"
        if not destination.startswith(prefix):
            raise PermissionError("skill destination is outside the active workspace")
        relative = destination.removeprefix(prefix).lstrip("/")
        target = (self.root / relative).resolve()
        if self.root != target and self.root not in target.parents:
            raise PermissionError("skill destination is outside the active workspace")
        async with self._lock:
            await asyncio.to_thread(self._materialize_sync, bundle, target)
        return self.workspace_root.rstrip("/") + f"/{relative}"

    def _materialize_sync(self, bundle: SkillBundle, target: Path) -> None:
        if target.exists():
            if (
                not target.is_dir()
                or self._hash_directory(target) != bundle.content_hash
            ):
                from sagents.v2.contracts.errors import (
                    ErrorCategory,
                    RuntimeErrorInfo,
                    SageV2Error,
                )

                raise SageV2Error(
                    RuntimeErrorInfo(
                        code="skill.workspace_conflict",
                        category=ErrorCategory.CONFLICT,
                        message=(
                            f"workspace skill {target.name!r} already exists with "
                            "different content; it was not overwritten"
                        ),
                        safe_to_resume=True,
                    )
                )
            return
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = Path(
            tempfile.mkdtemp(prefix=f".{target.name}.sage-load-", dir=target.parent)
        )
        try:
            for relative, content in bundle.files.items():
                candidate = temporary / relative
                candidate.parent.mkdir(parents=True, exist_ok=True)
                candidate.write_bytes(content)
            temporary.replace(target)
        except Exception:
            shutil.rmtree(temporary, ignore_errors=True)
            raise

    @staticmethod
    def _hash_directory(root: Path) -> str:
        digest = hashlib.sha256()
        for candidate in sorted(root.rglob("*")):
            if candidate.is_symlink() or not candidate.is_file():
                continue
            relative = candidate.relative_to(root).as_posix()
            digest.update(relative.encode("utf-8"))
            digest.update(b"\0")
            digest.update(candidate.read_bytes())
            digest.update(b"\0")
        return f"sha256:{digest.hexdigest()}"


class SandboxSkillWorkspace:
    """Materialize Skill bundles inside an isolated sandbox namespace."""

    def __init__(self, sandbox: SandboxHandle, issuer: SandboxGrantIssuer) -> None:
        self.sandbox = sandbox
        self.issuer = issuer
        self._lock = asyncio.Lock()
        self._operation_index = 0

    def _intent(self, run_id: str, operation: FileOperation, path: str):
        self._operation_index += 1
        intent = OperationIntent(
            operation=operation.value,
            run_id=run_id,
            tool_call_id=f"skill_materialize_{self._operation_index}",
            sandbox_id=self.sandbox.ref.sandbox_id,
            path=path,
        )
        return intent, self.issuer.issue(
            ref=self.sandbox.ref,
            intent=intent,
            allowed_operations=frozenset({operation.value}),
        )

    async def _read_optional(self, path: str, run_id: str) -> bytes | None:
        intent, grant = self._intent(run_id, FileOperation.READ, path)
        try:
            return await self.sandbox.filesystem.read_bytes(
                path, intent=intent, grant=grant
            )
        except FileNotFoundError:
            return None

    async def materialize(
        self, bundle: SkillBundle, *, run_id: str, destination: str
    ) -> str:
        destination = self.sandbox.filesystem.normalize_path(destination)
        async with self._lock:
            missing: list[tuple[str, bytes]] = []
            for relative, content in bundle.files.items():
                path = destination.rstrip("/") + f"/{relative}"
                existing = await self._read_optional(path, run_id)
                if existing is None:
                    missing.append((path, content))
                elif existing != content:
                    raise PermissionError(
                        f"workspace skill {bundle.descriptor.name!r} conflicts "
                        "with existing sandbox content"
                    )
            for path, content in missing:
                intent, grant = self._intent(run_id, FileOperation.CREATE, path)
                await self.sandbox.filesystem.write_bytes(
                    path,
                    content,
                    intent=intent,
                    grant=grant,
                    overwrite=False,
                )
        return destination


class PreferredSkillsContextProvider:
    """Project selected Skills into context without fetching or copying them."""

    async def segments(
        self, command: StartRun, *, run_id: str | None = None
    ) -> tuple[ContextSegment, ...]:
        del run_id
        selected = command.config.metadata.get("preferred_skills") or []
        if not selected:
            return ()
        return (
            ContextSegment(
                segment_id="desktop_preferred_skills",
                content=(
                    "The user marked these Skills as relevant: "
                    + ", ".join(selected)
                    + ". They are not loaded. Call load_skill before using one."
                ),
                stability=ContextStability.SEMI_STABLE,
                priority=-45,
            ),
        )


class AgentRosterContextProvider:
    """Expose exact multi-Agent identities and mode semantics to the model."""

    def __init__(
        self,
        registry: AgentRegistry,
        mode: AgentMode,
        *,
        allow_delegation: bool = True,
    ) -> None:
        self.registry = registry
        self.mode = mode
        self.allow_delegation = allow_delegation

    async def segments(
        self, command: StartRun, *, run_id: str | None = None
    ) -> tuple[ContextSegment, ...]:
        del command, run_id
        if not self.allow_delegation:
            return (
                ContextSegment(
                    segment_id="agent_delegation_boundary",
                    content=(
                        "<multi_agent_mode>\n"
                        "You are executing a delegated task as a leaf agent. "
                        "Do not create, spawn, or delegate to other agents; "
                        "complete the assigned task directly with your available "
                        "non-delegation tools.\n"
                        "</multi_agent_mode>"
                    ),
                    stability=ContextStability.STABLE,
                    priority=-55,
                ),
            )
        if self.mode == AgentMode.SIMPLE:
            return ()
        members = await self.registry.list()
        roster = "\n".join(
            f"- {member.agent_id}: {member.name} — "
            f"{member.description or 'no description'}"
            for member in members
        )
        if not roster:
            roster = "- No existing agents are registered."
        behavior = (
            "Fibre may create a Session-scoped reusable expert with sys_spawn_agent, "
            "then must delegate concrete work with sys_delegate_task using the exact "
            "agent_id returned by spawn or listed below. Independent tasks may be "
            "batched."
            if self.mode == AgentMode.FIBRE
            else "Team has a fixed roster and cannot create agents. Delegate concrete "
            "work with sys_team_delegate_task using exact agent_id values listed below. "
            "Independent tasks may be batched."
        )
        return (
            ContextSegment(
                segment_id="agent_roster",
                content=f"<multi_agent_mode>\n{behavior}\n{roster}\n</multi_agent_mode>",
                stability=ContextStability.SEMI_STABLE,
                priority=-55,
            ),
        )


