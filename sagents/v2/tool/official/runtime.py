"""Run-scoped services used by the official V2 Tool plugin.

The Tool layer never opens host files, starts host processes, or performs
network I/O itself. Every resource operation is expressed as a signed
``OperationIntent`` and executed by the Runtime Execution sandbox selected by
the host. This keeps authorization, containment, quotas, and cancellation in
one execution layer.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import re
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any, Awaitable, Callable, Iterator, Protocol
from urllib.parse import urlsplit

from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo, SageV2Error
from sagents.v2.memory import MemoryService
from sagents.v2.session_memory import SessionMemoryService
from sagents.v2.agent.policy import ContinuationSignals, InteractionDraft

if TYPE_CHECKING:
    from sagents.v2.goal.state import GoalStateService
from sagents.v2.contracts.jobs import (
    JobExecutionAffinity,
    JobCompletion,
    JobCursor,
    JobPauseBehavior,
    JobSpec,
    JobState,
)
from sagents.v2.runtime.execution.jobs import InMemoryJobRuntime, JobRuntime
from sagents.v2.runtime.execution.sandbox import (
    FileOperation,
    NetworkRequest,
    NetworkResult,
    OperationIntent,
    ProcessRequest,
    SandboxGrantIssuer,
    SandboxHandle,
)
from sagents.v2.tool import ToolInvocation
from sagents.v2.tool.selection import ToolSelectionPolicy


class ImageContextPublisher(Protocol):
    async def __call__(
        self,
        *,
        image_path: str,
        prompt: str | None,
        run_id: str,
    ) -> dict[str, Any]: ...


ToolCatalogResolver = Callable[[str], Awaitable[tuple[str, ...]] | tuple[str, ...]]

# Sandbox error codes that a provider raises from its authorization gate,
# before it touches the workspace. Each of them proves that the requested
# operation was not applied, so the Tool executor can report a clean failure
# instead of escalating to the unknown-side-effect reconciliation flow.
SANDBOX_DENIAL_CODES = frozenset(
    {
        "sandbox.permission_denied",
        "sandbox.protected_path",
        "sandbox.grant_mismatch",
        "sandbox.grant_invalid",
        "sandbox.grant_expired",
        "sandbox.grant_replayed",
        "sandbox.policy_stale",
        "sandbox.resource_exhausted",
        "sandbox.unavailable",
        "sandbox.lost",
        "sandbox.ref_mismatch",
    }
)


def sandbox_denial_as_not_applied(exc: BaseException) -> SageV2Error | None:
    """Return the typed ``not_applied`` form of a sandbox denial, else ``None``.

    Only failures that the sandbox contract guarantees happened before any
    mutation are mapped. Anything else (an ``OSError`` from inside the write,
    a lost response, an unknown code) keeps its identity so the executor still
    treats a write-class failure as an unknown outcome.
    """

    if isinstance(exc, SageV2Error):
        info = exc.info
        if info.code not in SANDBOX_DENIAL_CODES:
            return None
        if info.metadata.get("side_effect_state") == "not_applied":
            return None
        return SageV2Error(
            info.model_copy(
                update={
                    "safe_to_resume": True,
                    "metadata": {**info.metadata, "side_effect_state": "not_applied"},
                }
            )
        )
    # Providers raise a bare ``PermissionError(message)`` for policy, path and
    # grant violations, always before any I/O. A ``PermissionError`` raised by
    # the operating system from inside an I/O call carries ``errno`` and is
    # deliberately left alone.
    if isinstance(exc, PermissionError) and exc.errno is None:
        return SageV2Error(
            RuntimeErrorInfo(
                code="sandbox.permission_denied",
                category=ErrorCategory.POLICY_DENIED,
                message=str(exc) or "sandbox denied the operation",
                safe_to_resume=True,
                metadata={"side_effect_state": "not_applied"},
            )
        )
    return None


@contextmanager
def sandbox_denials_not_applied() -> Iterator[None]:
    """Re-raise sandbox denials as typed errors carrying ``not_applied``."""

    try:
        yield
    except (SageV2Error, PermissionError) as exc:
        typed = sandbox_denial_as_not_applied(exc)
        if typed is None:
            raise
        raise typed from exc


class OfficialToolRuntime:
    """Bridge decorated Tools to a host-provisioned Runtime Execution sandbox.

    The host owns sandbox policy and grant signing. Requiring both objects here
    prevents a Tool plugin from silently replacing policy with direct host I/O.
    """

    def __init__(
        self,
        sandbox: SandboxHandle,
        grant_issuer: SandboxGrantIssuer,
        *,
        memory_service: MemoryService | None = None,
        session_memory_service: SessionMemoryService | None = None,
        image_context_publisher: ImageContextPublisher | None = None,
        tool_catalog_resolver: ToolCatalogResolver | None = None,
        tool_selection_policy: ToolSelectionPolicy | None = None,
        job_runtime: JobRuntime | None = None,
        goal_state_service: GoalStateService | None = None,
    ) -> None:
        self.sandbox = sandbox
        self.grant_issuer = grant_issuer
        self.memory_service = memory_service
        self.session_memory_service = session_memory_service
        self.image_context_publisher = image_context_publisher
        self.tool_catalog_resolver = tool_catalog_resolver
        self.tool_selection_policy = tool_selection_policy
        self.goal_state_service = goal_state_service
        self._owns_job_runtime = job_runtime is None
        self._shell_job_runner = self._run_shell_job
        self._registered_shell_owner: str | None = None
        self.job_runtime = job_runtime or InMemoryJobRuntime(
            {"official.shell": self._shell_job_runner}
        )
        self._expanded_tools: dict[str, set[str]] = {}
        self._turn_status: dict[str, dict[str, Any]] = {}

    def bind_job_runtime(self, job_runtime: JobRuntime) -> None:
        """Bind the composition-owned lifecycle service before tool execution."""

        self.job_runtime = job_runtime
        self._owns_job_runtime = False

    def virtual_path(self, value: str | None) -> str:
        """Ask the active sandbox to resolve a canonical resource path."""

        with sandbox_denials_not_applied():
            return self.sandbox.filesystem.normalize_path(value or ".")

    def _intent(
        self,
        invocation: ToolInvocation,
        operation: str,
        *,
        path: str | None = None,
        executable: str | None = None,
        argv: tuple[str, ...] = (),
        network_host: str | None = None,
        network_port: int | None = None,
    ) -> OperationIntent:
        return OperationIntent(
            operation=operation,
            run_id=invocation.call.owner_run_id,
            tool_call_id=invocation.call.tool_call_id,
            sandbox_id=self.sandbox.ref.sandbox_id,
            path=path,
            executable=executable,
            argv=argv,
            network_host=network_host,
            network_port=network_port,
        )

    def _grant(self, intent: OperationIntent):
        return self.grant_issuer.issue(
            ref=self.sandbox.ref,
            intent=intent,
            allowed_operations=frozenset({intent.operation}),
        )

    async def read_bytes(self, path: str, invocation: ToolInvocation) -> bytes:
        path = self.virtual_path(path)
        intent = self._intent(invocation, FileOperation.READ.value, path=path)
        with sandbox_denials_not_applied():
            return await self.sandbox.filesystem.read_bytes(
                path, intent=intent, grant=self._grant(intent)
            )

    async def read_text(self, path: str, invocation: ToolInvocation) -> str:
        return (await self.read_bytes(path, invocation)).decode("utf-8")

    async def exists(self, path: str, invocation: ToolInvocation) -> bool:
        path = self.virtual_path(path)
        intent = self._intent(invocation, FileOperation.READ.value, path=path)
        try:
            with sandbox_denials_not_applied():
                await self.sandbox.filesystem.stat(
                    path, intent=intent, grant=self._grant(intent)
                )
        except FileNotFoundError:
            return False
        return True

    async def stat(self, path: str, invocation: ToolInvocation):
        path = self.virtual_path(path)
        intent = self._intent(invocation, FileOperation.READ.value, path=path)
        with sandbox_denials_not_applied():
            return await self.sandbox.filesystem.stat(
                path, intent=intent, grant=self._grant(intent)
            )

    async def write_bytes(
        self,
        path: str,
        content: bytes,
        invocation: ToolInvocation,
        *,
        overwrite: bool = True,
    ) -> str:
        path = self.virtual_path(path)
        operation = (
            FileOperation.WRITE
            if await self.exists(path, invocation)
            else FileOperation.CREATE
        )
        intent = self._intent(invocation, operation.value, path=path)
        with sandbox_denials_not_applied():
            stat = await self.sandbox.filesystem.write_bytes(
                path,
                content,
                intent=intent,
                grant=self._grant(intent),
                overwrite=overwrite,
            )
        return stat.path

    async def write_text(
        self,
        path: str,
        content: str,
        invocation: ToolInvocation,
        *,
        append: bool = False,
    ) -> str:
        payload = content.encode()
        if append and await self.exists(path, invocation):
            payload = await self.read_bytes(path, invocation) + payload
        return await self.write_bytes(path, payload, invocation)

    async def delete_file(self, path: str, invocation: ToolInvocation) -> None:
        path = self.virtual_path(path)
        intent = self._intent(invocation, FileOperation.DELETE.value, path=path)
        with sandbox_denials_not_applied():
            await self.sandbox.filesystem.delete(
                path, intent=intent, grant=self._grant(intent)
            )

    async def list_paths(self, path: str | None, invocation: ToolInvocation):
        path = self.virtual_path(path)
        intent = self._intent(invocation, FileOperation.LIST.value, path=path)
        with sandbox_denials_not_applied():
            return await self.sandbox.filesystem.list_paths(
                path, intent=intent, grant=self._grant(intent)
            )

    async def shell(
        self,
        command: str,
        invocation: ToolInvocation,
        *,
        workdir: str | None,
        env_vars: dict[str, str],
        block_until_ms: int,
    ) -> dict[str, Any]:
        cwd = self.virtual_path(workdir)
        # A non-login shell preserves command semantics without sourcing host
        # profile files that are outside the sandbox's declared environment.
        register_runner = getattr(self.job_runtime, "register_runner", None)
        if register_runner is not None:
            register_runner(
                "official.shell",
                self._shell_job_runner,
                owner_run_id=invocation.call.owner_run_id,
            )
            self._registered_shell_owner = invocation.call.owner_run_id
        handle = await self.job_runtime.submit(
            JobSpec(
                owner_run_id=invocation.call.owner_run_id,
                kind="official.shell",
                payload={
                    "command": command,
                    "cwd": cwd,
                    "env": env_vars,
                    "tool_call_id": invocation.call.tool_call_id,
                },
                pause_behavior=JobPauseBehavior.DETACH,
                execution_affinity=JobExecutionAffinity.SANDBOX,
                idempotency_key=invocation.call.idempotency_key,
            )
        )
        if block_until_ms == 0:
            return {
                "success": True,
                "status": "running",
                "task_id": handle.job_id,
            }
        return await self.await_shell(
            handle.job_id, block_until_ms=block_until_ms, pattern=None
        )

    async def close(self) -> None:
        """Cancel private ephemeral jobs before their sandbox is released."""

        unregister_runner = getattr(self.job_runtime, "unregister_runner", None)
        if unregister_runner is not None and self._registered_shell_owner is not None:
            unregister_runner(
                "official.shell",
                owner_run_id=self._registered_shell_owner,
                runner=self._shell_job_runner,
            )
            self._registered_shell_owner = None
        if self._owns_job_runtime:
            await self.job_runtime.close()

    async def _run_shell_job(self, spec, emit, cancel_event) -> JobCompletion:
        del cancel_event
        command = str(spec.payload["command"])
        cwd = str(spec.payload["cwd"])
        env = dict(spec.payload.get("env") or {})
        argv = ("bash", "-c", command)
        request = ProcessRequest(argv=argv, cwd=cwd, env=env)
        intent = OperationIntent(
            operation="process.run",
            run_id=spec.owner_run_id,
            tool_call_id=str(spec.payload["tool_call_id"]),
            sandbox_id=self.sandbox.ref.sandbox_id,
            path=cwd,
            executable="bash",
            argv=argv,
        )
        result = await self.sandbox.process.run(
            request, intent=intent, grant=self._grant(intent)
        )
        if result.stdout:
            await emit("stdout", result.stdout)
        if result.stderr:
            await emit("stderr", result.stderr)
        return JobCompletion(exit_code=result.exit_code)

    async def await_shell(
        self,
        task_id: str,
        *,
        block_until_ms: int,
        pattern: str | None = None,
    ) -> dict[str, Any]:
        timeout = max(0, block_until_ms) / 1000
        try:
            snapshot = await asyncio.wait_for(
                self.job_runtime.wait(task_id), timeout=timeout
            )
        except TimeoutError:
            snapshot = await self.job_runtime.inspect(task_id)
        output = await self._job_output(task_id)
        terminal = snapshot.state in {
            JobState.COMPLETED,
            JobState.FAILED,
            JobState.KILLED,
        }
        if not terminal:
            return {
                "success": True,
                "status": "running",
                "task_id": task_id,
                "stdout": output,
                "pattern_matched": bool(re.search(pattern, output))
                if pattern
                else None,
            }
        return {
            "success": snapshot.state == JobState.COMPLETED and snapshot.exit_code == 0,
            "status": snapshot.state.value,
            "task_id": task_id,
            "exit_code": snapshot.exit_code,
            "stdout": output,
            "pattern_matched": bool(re.search(pattern, output)) if pattern else None,
            "error": snapshot.error.model_dump(mode="json") if snapshot.error else None,
        }

    async def _job_output(self, job_id: str) -> str:
        chunks = await self.job_runtime.read_output(JobCursor(job_id=job_id))
        return b"".join(value.data for value in chunks).decode(
            "utf-8", errors="replace"
        )

    async def kill_shell(self, task_id: str) -> dict[str, Any]:
        snapshot = await self.job_runtime.cancel(task_id, force=True)
        return {
            "success": True,
            "status": "terminated",
            "task_id": task_id,
            "exit_code": snapshot.exit_code,
            "stdout": await self._job_output(task_id),
        }

    async def network_request(
        self,
        url: str,
        invocation: ToolInvocation,
        *,
        timeout_seconds: float,
        headers: dict[str, str] | None = None,
    ) -> NetworkResult:
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("network URL must use http or https")
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        request = NetworkRequest(
            method="GET",
            url=url,
            headers=headers or {},
            timeout_seconds=timeout_seconds,
        )
        intent = self._intent(
            invocation,
            "network.request",
            network_host=parsed.hostname,
            network_port=port,
        )
        return await self.sandbox.network.request(
            request, intent=intent, grant=self._grant(intent)
        )

    async def save_todos(
        self, tasks: list[dict[str, Any]], invocation: ToolInvocation
    ) -> str:
        payload = json.dumps(tasks, ensure_ascii=False, indent=2) + "\n"
        return await self.write_text(".sage/todos.json", payload, invocation)

    async def load_todos(self, invocation: ToolInvocation) -> list[dict[str, Any]]:
        target = ".sage/todos.json"
        if not await self.exists(target, invocation):
            return []
        value = json.loads(await self.read_text(target, invocation))
        return value if isinstance(value, list) else []

    def set_turn_status(self, run_id: str, value: dict[str, Any]) -> None:
        self._turn_status[run_id] = value

    def consume_continuation_signals(self, run_id: str) -> ContinuationSignals:
        """Consume one explicit status so it cannot leak into a later Step."""

        value = self._turn_status.pop(run_id, None)
        if value is None:
            return ContinuationSignals()
        status = value.get("status")
        note = value.get("note")
        interaction = value.get("interaction")
        return ContinuationSignals(
            explicit_status=str(status) if status is not None else None,
            explicit_status_note=str(note) if note is not None else None,
            interaction=(
                InteractionDraft.model_validate(interaction)
                if isinstance(interaction, dict)
                else None
            ),
        )

    async def expand_tools(self, run_id: str, names: list[str]) -> dict[str, Any]:
        if self.tool_selection_policy is not None:
            return self.tool_selection_policy.expand_tools(
                run_id=run_id,
                names=tuple(names),
            )
        available: tuple[str, ...] = ()
        if self.tool_catalog_resolver is not None:
            value = self.tool_catalog_resolver(run_id)
            available = await value if inspect.isawaitable(value) else value
        unknown = sorted(set(names) - set(available))
        if unknown:
            return {"status": "error", "unknown_tools": unknown}
        active = self._expanded_tools.setdefault(run_id, set())
        active.update(names)
        return {"status": "success", "expanded_tools": sorted(active)}
