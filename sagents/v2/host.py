"""Multi-package Agent host for embedding SAgents v2 in application servers."""

from __future__ import annotations

import asyncio
import hashlib
import inspect
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Protocol

from pydantic import Field

from sagents.v2.builder import SAgentBuilder
from sagents.v2.contracts.commands import StartRun
from sagents.v2.contracts.common import Identifier, StrictModel
from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo, SageV2Error
from sagents.v2.contracts.principals import RequestContext
from sagents.v2.contracts.run_state import RunHandle
from sagents.v2.package.manifest.resolver import CompositionResolver
from sagents.v2.package.registry import AgentPackageRecord, PackageStage
from sagents.v2.sagent import SAgent, SAgentRunStream


class AgentRef(StrictModel):
    """Immutable address of one Agent in one immutable package version."""

    package_id: Identifier
    version: str = Field(min_length=1, max_length=128)
    agent_id: Identifier


class AgentPackageSource(Protocol):
    """Minimal package-registry surface required by ``AgentHost``."""

    async def get(self, package_id: str, version: str) -> AgentPackageRecord: ...


AgentRuntimeFactory = Callable[[AgentPackageRecord, str], SAgent | Awaitable[SAgent]]


class AgentHost:
    """Resolve published Agent packages and reuse one runtime per immutable Agent.

    HTTP routing, authentication, tenant ownership, persistent package storage,
    and plugin installation remain application responsibilities. The host owns
    only package validation, Agent selection, runtime construction, and a
    process-local cache.
    """

    def __init__(
        self,
        packages: AgentPackageSource,
        *,
        session_root: str | Path | None = None,
        runtime_factory: AgentRuntimeFactory | None = None,
        require_published: bool = True,
    ) -> None:
        if runtime_factory is None and session_root is None:
            raise ValueError("AgentHost requires session_root or runtime_factory")
        self.packages = packages
        self.session_root = (
            Path(session_root).expanduser().resolve()
            if session_root is not None
            else None
        )
        self.runtime_factory = runtime_factory or self._build_default_runtime
        self.require_published = require_published
        self._resolver = CompositionResolver()
        self._cache: dict[tuple[str, str, str, str], SAgent] = {}
        self._build_locks: dict[tuple[str, str, str, str], asyncio.Lock] = {}
        self._invalidating: set[tuple[str, str, str, str]] = set()
        self._state_lock = asyncio.Lock()
        self._closed = False

    async def get_agent(self, ref: AgentRef) -> SAgent:
        """Return the cached runtime for ``ref``, building it once if needed."""

        self._ensure_open()
        record = await self.packages.get(ref.package_id, ref.version)
        self._validate_record(ref, record)
        return await self._get_agent_for_record(ref, record)

    async def _get_agent_for_record(
        self, ref: AgentRef, record: AgentPackageRecord
    ) -> SAgent:
        key = self._cache_key(ref, record)
        async with self._state_lock:
            if self._closed:
                raise _error(
                    "agent_host.closed",
                    ErrorCategory.RESOURCE_LOST,
                    "AgentHost is closed",
                )
            cached = self._cache.get(key)
            if cached is not None and key not in self._invalidating:
                return cached
            build_lock = self._build_locks.setdefault(key, asyncio.Lock())

        async with build_lock:
            async with self._state_lock:
                cached = self._cache.get(key)
                if cached is not None and key not in self._invalidating:
                    return cached
            runtime = self.runtime_factory(record, ref.agent_id)
            if inspect.isawaitable(runtime):
                runtime = await runtime
            if not isinstance(runtime, SAgent):
                raise _error(
                    "agent_host.runtime_contract_invalid",
                    ErrorCategory.PROVIDER_PERMANENT,
                    "Agent runtime factory must return SAgent",
                )
            async with self._state_lock:
                rejected_code = (
                    "agent_host.closed"
                    if self._closed
                    else (
                        "agent_host.runtime_invalidated"
                        if key in self._invalidating
                        else None
                    )
                )
                if rejected_code is None:
                    self._cache[key] = runtime
            if rejected_code is not None:
                await runtime.close()
                raise _error(
                    rejected_code,
                    (
                        ErrorCategory.RESOURCE_LOST
                        if rejected_code == "agent_host.closed"
                        else ErrorCategory.CONFLICT
                    ),
                    (
                        "AgentHost is closed"
                        if rejected_code == "agent_host.closed"
                        else "Agent runtime was invalidated while it was building"
                    ),
                )
            return runtime

    async def start_run(
        self,
        ref: AgentRef,
        command: StartRun,
        context: RequestContext,
    ) -> RunHandle:
        self._ensure_open()
        record = await self.packages.get(ref.package_id, ref.version)
        self._validate_record(ref, record)
        agent = await self._get_agent_for_record(ref, record)
        return await agent.start_run(self._bind_command(ref, record, command), context)

    async def run_stream(
        self,
        ref: AgentRef,
        command: StartRun,
        context: RequestContext,
    ) -> SAgentRunStream:
        self._ensure_open()
        record = await self.packages.get(ref.package_id, ref.version)
        self._validate_record(ref, record)
        agent = await self._get_agent_for_record(ref, record)
        return await agent.run_stream(self._bind_command(ref, record, command), context)

    async def invalidate(self, ref: AgentRef | None = None) -> int:
        """Forget cached runtimes; durable Runs and Sessions are unchanged."""

        async with self._state_lock:
            candidates = set(self._cache)
            candidates.update(
                key for key, lock in self._build_locks.items() if lock.locked()
            )
            matching = tuple(
                key
                for key in candidates
                if ref is None or key[:3] == (ref.package_id, ref.version, ref.agent_id)
            )
            self._invalidating.update(matching)
            locks = {
                key: self._build_locks.setdefault(key, asyncio.Lock())
                for key in matching
            }
        for key in matching:
            async with locks[key]:
                async with self._state_lock:
                    runtime = self._cache.get(key)
                try:
                    if runtime is not None:
                        await runtime.close()
                except Exception:
                    async with self._state_lock:
                        self._invalidating.discard(key)
                    raise
                async with self._state_lock:
                    if self._cache.get(key) is runtime:
                        self._cache.pop(key, None)
                    self._invalidating.discard(key)
                    lock = self._build_locks.get(key)
                    if lock is not None and not lock.locked():
                        self._build_locks.pop(key, None)
        return len(matching)

    async def close(self) -> None:
        """Close every idle cached runtime and reject new requests."""

        async with self._state_lock:
            if self._closed and not self._cache:
                return
            self._closed = True
        await self.invalidate()

    async def cached_agents(self) -> tuple[AgentRef, ...]:
        async with self._state_lock:
            return tuple(
                AgentRef(package_id=key[0], version=key[1], agent_id=key[2])
                for key in sorted(self._cache)
                if key not in self._invalidating
            )

    def _ensure_open(self) -> None:
        if self._closed:
            raise _error(
                "agent_host.closed",
                ErrorCategory.RESOURCE_LOST,
                "AgentHost is closed",
            )

    def _validate_record(self, ref: AgentRef, record: AgentPackageRecord) -> None:
        if (record.package_id, record.version) != (ref.package_id, ref.version):
            raise _error(
                "agent_host.package_identity_mismatch",
                ErrorCategory.CORRUPT_STATE,
                "package source returned a record with a different identity",
            )
        if self.require_published and record.stage != PackageStage.PUBLISHED:
            raise _error(
                "agent_host.package_not_published",
                ErrorCategory.VALIDATION,
                f"package {ref.package_id!r} version {ref.version!r} is not published",
            )
        resolved = self._resolver.resolve(record.manifest)
        if resolved.manifest_hash != record.manifest_hash:
            raise _error(
                "agent_host.manifest_hash_mismatch",
                ErrorCategory.CORRUPT_STATE,
                "package record manifest hash does not match its content",
            )
        if ref.agent_id not in resolved.agents:
            raise _error(
                "agent_host.agent_not_found",
                ErrorCategory.VALIDATION,
                f"agent {ref.agent_id!r} is not defined by package {ref.package_id!r}",
            )

    @staticmethod
    def _cache_key(
        ref: AgentRef, record: AgentPackageRecord
    ) -> tuple[str, str, str, str]:
        return (ref.package_id, ref.version, ref.agent_id, record.manifest_hash)

    def _build_default_runtime(
        self, record: AgentPackageRecord, agent_id: str
    ) -> SAgent:
        assert self.session_root is not None
        identity = "\0".join(
            (record.package_id, record.version, agent_id, record.manifest_hash)
        )
        directory = hashlib.sha256(identity.encode()).hexdigest()[:32]
        return (
            SAgentBuilder()
            .with_defaults(session_root=self.session_root / "agents" / directory)
            .build(record.manifest, agent_id=agent_id)
        )

    @staticmethod
    def _bind_command(
        ref: AgentRef, record: AgentPackageRecord, command: StartRun
    ) -> StartRun:
        if command.agent_id != ref.agent_id:
            raise _error(
                "agent_host.command_agent_mismatch",
                ErrorCategory.VALIDATION,
                f"Run command targets {command.agent_id!r}, expected {ref.agent_id!r}",
            )
        metadata = {
            **command.config.metadata,
            "agent_package": {
                "package_id": ref.package_id,
                "version": ref.version,
                "agent_id": ref.agent_id,
                "manifest_hash": record.manifest_hash,
            },
        }
        return command.model_copy(
            update={
                "resolved_spec_hash": record.manifest_hash,
                "config": command.config.model_copy(update={"metadata": metadata}),
            }
        )


def _error(code: str, category: ErrorCategory, message: str) -> SageV2Error:
    return SageV2Error(
        RuntimeErrorInfo(
            code=code,
            category=category,
            message=message,
            safe_to_resume=True,
        )
    )
