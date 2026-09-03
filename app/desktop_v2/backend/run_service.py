from __future__ import annotations

import asyncio
import json
import logging
import os
from collections.abc import AsyncIterator
from typing import Any


from app.desktop_v2.backend.shell_policy import (
    ShellCommandOperationAssessor,
    normalize_shell_command,
)
from sagents.v2 import SAgent
from sagents.v2.contracts.commands import (
    CancelRun,
    InputItem,
    PauseRun,
    ReplyInteraction,
    ResumeRun,
    RunConfig,
    StartRun,
    SteerRun,
)
from sagents.v2.contracts.common import new_id, utc_now
from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo, SageV2Error
from sagents.v2.contracts.principals import (
    RequestContext,
)
from sagents.v2.contracts.run_state import (
    EventCursor,
    RunState,
    SessionConcurrencyMode,
    TERMINAL_RUN_STATES,
)
from sagents.v2.package.manifest.resolver import CompositionResolver
from sagents.v2.runtime.execution.sandbox import (
    SandboxReleaseDisposition,
)
from sagents.v2.runtime.execution import (
    ExecutionBindingLifecycleCoordinator,
    ExecutionResourceState,
)
from sagents.v2.runtime.execution.jobs import InMemoryJobRuntime
from sagents.v2.runtime.observability import (
    LogError,
    LogLevel,
    LogRecord,
)
from app.desktop_v2.backend.schemas import (
    DesktopRunRequest,
    RunMessage,
    RunMessageContent,
)
from app.desktop_v2.backend.run_lifecycle import (
    DesktopDriver as _DesktopDriver,
)
from app.desktop_v2.backend.run_composition import DesktopRunCompositionMixin
from app.desktop_v2.backend.runtime_config import (
    _SKILL_NAME,
    _TOOL_NAME,
    _agent_memory_enabled,
)
from app.desktop_v2.backend.usage_analytics import (
    _usage_percentile as _usage_percentile,
)

LOGGER = logging.getLogger(__name__)


class DesktopRunServiceMixin(DesktopRunCompositionMixin):
    """Run commands, recovery, and per-Run composition for Desktop v2."""

    async def run_events(
        self, request: DesktopRunRequest, user_id: str
    ) -> AsyncIterator[str]:
        await self.start()
        accepted_handle = None
        driver: _DesktopDriver | None = None
        run_logger = self.logger.bind(correlation_id=request.idempotency_key)
        run_logger.info(
            "agent.run.requested",
            "Agent run requested",
            attributes={
                "agent_id": request.agent_id,
                "workspace_id": request.workspace_id,
                "approval_mode": request.approval_mode,
                "invocation_mode": request.invocation_mode,
            },
        )
        try:
            request = await self._normalize_desktop_fork_request(request, user_id)
            agent = await self._agent(request.agent_id, user_id)
            provider = await self._provider(agent, user_id)
            workspace = await self.workspace_root(
                request.workspace_id, request.agent_id
            )
            configured_tools = agent.config.get("availableTools")
            valid_tools = tuple(
                value
                for value in (
                    configured_tools
                    if configured_tools is not None
                    else tuple(
                        value["name"] for value in await self.list_tools(agent.user_id)
                    )
                )
                if isinstance(value, str) and _TOOL_NAME.fullmatch(value)
            )
            valid_skills = tuple(
                value
                for value in (agent.config.get("availableSkills") or ())
                if isinstance(value, str) and _SKILL_NAME.fullmatch(value)
            )
            if valid_skills and "load_skill" not in valid_tools:
                valid_tools = (*valid_tools, "load_skill")
            resolved = CompositionResolver().resolve(
                self._manifest(agent, provider, valid_tools, valid_skills)
            )
            command = self._command(
                request,
                resolved,
                agent=agent,
                provider=provider,
                workspace=workspace,
            )
            context = self._context(
                user_id,
                language=str(command.config.metadata.get("response_language") or "en"),
            )
            accepted_handle = await self.runtime.start_run(command, context)

            async def build_driver():
                return await self._build_loop(
                    agent=agent,
                    provider=provider,
                    workspace=workspace,
                    preferred_skills=tuple(request.preferred_skills),
                    approval_mode=request.approval_mode,
                    invocation_mode=request.invocation_mode,
                    session_id=accepted_handle.session_id,
                    run_id=accepted_handle.run_id,
                    resolved_spec_hash=command.resolved_spec_hash,
                    component_snapshot=command.config.metadata.get(
                        "runtime_components"
                    ),
                )

            driver = _DesktopDriver(
                self, None, workspace, None, lazy_builder=build_driver
            )
            memory_enabled = _agent_memory_enabled(
                agent, self.memory_plugin_id, self.session_memory_plugin_id
            )
            facade = SAgent(
                runtime=self.runtime,
                driver_factory=lambda _run_id: driver,
                memory_service=(self.memory_service if memory_enabled else None),
                memory_scope={
                    "recall": memory_enabled,
                    "auto_write": memory_enabled,
                    "scope": "agent",
                    "recall_limit": 8,
                },
            )
            facade.attach_dispatcher(self.dispatcher)
            stream = await facade.schedule_accepted_run(accepted_handle, context)
            stream._execution.add_done_callback(
                lambda _completed, agent=facade: self._schedule_agent_close(agent)
            )
        except asyncio.CancelledError:
            if driver is not None:
                await asyncio.shield(driver.close_binding())
            raise
        except Exception as exc:
            if driver is not None:
                try:
                    await driver.close_binding()
                except BaseException as close_exc:
                    run_logger.exception(
                        "agent.run.start_cleanup_failed",
                        "Agent run resources failed to close after startup failure",
                        close_exc,
                        attributes={"agent_id": request.agent_id},
                    )
            run_logger.exception(
                "agent.run.start_failed",
                "Agent run failed before execution started",
                exc,
                attributes={"agent_id": request.agent_id},
            )
            language = str(
                request.response_language or self._read_settings_sync().language or "en"
            )
            if language == "system":
                language = "zh"
            context = self._context(user_id, language=language)
            fallback = StartRun(
                agent_id=request.agent_id or "desktop_unconfigured_agent",
                input=tuple(
                    InputItem(
                        role=value.role,
                        content=content,
                    )
                    for value in request.messages
                    if (
                        content := self._run_message_content(
                            value,
                            provider=None,
                            workspace=None,
                            workspace_root="/workspace",
                        )
                    )
                ),
                config=RunConfig(metadata={"response_language": language}),
                resolved_spec_hash="sha256:desktop-preflight-v1",
                idempotency_key=(
                    request.idempotency_key or new_id("desktop_preflight_failure")
                ),
            )
            handle = accepted_handle or await self.runtime.start_run(fallback, context)
            failed = await self.runtime.fail_run(
                run_id=handle.run_id,
                expected_revision=(await self.runtime.get_run(handle.run_id)).revision,
                error=RuntimeErrorInfo(
                    code="desktop.run_start_failed",
                    category=(
                        exc.info.category
                        if isinstance(exc, SageV2Error)
                        else ErrorCategory.VALIDATION
                        if isinstance(
                            exc,
                            (ValueError, FileNotFoundError, PermissionError),
                        )
                        else ErrorCategory.INTERNAL
                    ),
                    message=(
                        exc.info.message if isinstance(exc, SageV2Error) else str(exc)
                    ),
                    safe_to_resume=False,
                ),
                context=context,
                idempotency_key=f"desktop-preflight-fail:{handle.run_id}",
            )
            await self._index_session(failed.session_id)
            yield (
                json.dumps(
                    {
                        "kind": "stream.opened",
                        "handle": handle.model_dump(mode="json"),
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
            async for event in self.runtime.subscribe_events(
                EventCursor(run_id=handle.run_id, run_sequence=0)
            ):
                yield event.model_dump_json() + "\n"
                if event.type == "run.failed":
                    return
        await self._index_session(stream.handle.session_id)
        self._drivers[stream.handle.run_id] = driver
        self._ensure_run_observer(stream.handle.run_id)
        self.logger.info(
            "agent.run.opened",
            "Agent run stream opened",
            session_id=stream.handle.session_id,
            run_id=stream.handle.run_id,
            attributes={"agent_id": request.agent_id},
        )
        stream._execution.add_done_callback(
            lambda _completed, key=stream.handle.run_id, value=driver: (
                asyncio.create_task(self._discard_driver_if_terminal(key, value))
            )
        )
        yield (
            json.dumps(
                {
                    "kind": "stream.opened",
                    "handle": stream.handle.model_dump(mode="json"),
                },
                ensure_ascii=False,
            )
            + "\n"
        )
        observed_boundary = False
        try:
            async for event in stream.events:
                yield event.model_dump_json() + "\n"
            observed_boundary = True
        finally:
            if observed_boundary:
                await stream.wait()
            if stream._execution.done():
                await self._discard_driver_if_terminal(stream.handle.run_id, driver)
            await self._index_session(stream.handle.session_id)

    async def _normalize_desktop_fork_request(
        self, request: DesktopRunRequest, user_id: str
    ) -> DesktopRunRequest:
        await self.start()
        if request.session_concurrency_mode != SessionConcurrencyMode.FORK:
            if request.fork_source_run_id is not None:
                raise ValueError("fork_source_run_id requires fork concurrency mode")
            return request
        if not request.session_id or not request.fork_source_run_id:
            raise ValueError("Desktop fork requires session_id and fork_source_run_id")
        parent = await self.session_access.get_run(
            request.fork_source_run_id, self._context(user_id)
        )
        if parent.session_id != request.session_id:
            raise ValueError("fork parent Run does not belong to the parent Session")
        if parent.state not in TERMINAL_RUN_STATES:
            raise ValueError("Desktop can only branch from a terminal Run result")
        if parent.concurrency_mode == SessionConcurrencyMode.SNAPSHOT_ISOLATED:
            raise ValueError("Desktop cannot branch from an unpublished snapshot Run")
        base_revision = parent.accepted_session_revision + parent.revision
        if (
            request.base_session_revision is not None
            and request.base_session_revision != base_revision
        ):
            raise ValueError(
                "fork base revision does not match the selected Run result"
            )
        return request.model_copy(update={"base_session_revision": base_revision})

    async def snapshot(self, run_id: str, user_id: str) -> dict[str, Any]:
        await self.start()
        context = self._context(user_id)
        run = await self.session_access.get_run(run_id, context)
        data: dict[str, Any] = {"run": run.model_dump(mode="json")}
        if run.suspension_id:
            suspension = await self.session_access.get_suspension(
                run.suspension_id, context
            )
            data["suspension"] = suspension.model_dump(mode="json")
            if suspension.interaction_id:
                interaction = await self.session_access.get_interaction(
                    suspension.interaction_id, context
                )
                data["interaction"] = interaction.model_dump(mode="json")
        return data

    async def _index_session(self, session_id: str) -> None:
        """Publish one known Session into the Desktop-owned global index."""

        try:
            await self.session_index.upsert(
                await self.session_store.get_session(session_id)
            )
        except Exception:
            # The product index is downstream of the authoritative commit. It
            # may be rebuilt or repaired without changing authoritative Session state.
            LOGGER.exception("Desktop Session index update failed for %s", session_id)

    async def _index_run(self, run_id: str) -> None:
        try:
            run = await self.session_store.get_run(run_id)
            await self._index_session(run.session_id)
        except Exception as exc:
            self.logger.exception(
                "session.index_run_failed",
                "Desktop Run could not be projected into the Session index",
                exc,
                run_id=run_id,
            )

    async def subscribe_events(
        self, run_id: str, after_sequence: int, user_id: str
    ) -> AsyncIterator[str]:
        await self.start()
        context = self._context(user_id)
        async for event in self.session_access.subscribe_events(
            EventCursor(run_id=run_id, run_sequence=after_sequence), context
        ):
            yield event.model_dump_json() + "\n"
            if event.type in {
                "run.suspended",
                "run.completed",
                "run.failed",
                "run.cancelled",
            }:
                await self._index_run(run_id)
                return

    async def pause(self, run_id: str, user_id: str):
        await self.start()
        context = await self._run_context(run_id, user_id)
        run = await self.session_access.get_run(run_id, context)
        result = await self.runtime.pause_run(
            PauseRun(
                run_id=run_id,
                expected_revision=run.revision,
                idempotency_key=new_id("pause"),
            ),
            context,
        )
        await self._index_session(run.session_id)
        return result

    async def cancel(self, run_id: str, user_id: str):
        await self.start()
        context = await self._run_context(run_id, user_id)
        run = await self.session_access.get_run(run_id, context)
        result = await self.runtime.cancel_run(
            CancelRun(
                run_id=run_id,
                expected_revision=run.revision,
                idempotency_key=new_id("cancel"),
            ),
            context,
        )
        await self._index_session(run.session_id)
        return result

    async def steer(
        self,
        run_id: str,
        turn_id: str,
        text: str,
        user_id: str,
        *,
        content: list[RunMessageContent] | None = None,
    ):
        await self.start()
        context = await self._run_context(run_id, user_id)
        run = await self.session_access.get_run(run_id, context)
        message = RunMessage(role="user", text=text, content=content or [])
        message_content = self._run_message_content(
            message,
            provider=None,
            workspace=None,
            workspace_root="/workspace",
        )
        result = await self.runtime.steer_run(
            SteerRun(
                run_id=run_id,
                expected_revision=run.revision,
                expected_turn_id=turn_id,
                input=(InputItem(role="user", content=message_content),),
                idempotency_key=new_id("steer"),
            ),
            context,
        )
        await self._index_session(run.session_id)
        return result

    async def resume(self, run_id: str, user_id: str):
        await self.start()
        context = await self._run_context(run_id, user_id)
        run = await self.session_access.get_run(run_id, context)
        if run.suspension_id is None:
            raise ValueError("run has no suspension")
        suspension = await self.session_access.get_suspension(
            run.suspension_id, context
        )
        receipt = await self.runtime.resume_run(
            ResumeRun(
                run_id=run_id,
                suspension_id=suspension.suspension_id,
                expected_revision=run.revision,
                expected_suspension_revision=suspension.expected_revision,
                idempotency_key=new_id("resume"),
            ),
            context,
        )
        if receipt.decision.value != "rejected":
            await self._continue(run_id, user_id)
        await self._index_session(run.session_id)
        return receipt

    async def reply_interaction(
        self,
        run_id: str,
        interaction_id: str,
        decision: str,
        payload: dict[str, Any],
        user_id: str,
    ):
        await self.start()
        context = await self._run_context(run_id, user_id)
        run = await self.session_access.get_run(run_id, context)
        if run.suspension_id is None:
            raise ValueError("run has no suspension")
        suspension = await self.session_access.get_suspension(
            run.suspension_id, context
        )
        interaction = await self.session_access.get_interaction(interaction_id, context)
        if interaction.run_id != run_id or suspension.interaction_id != interaction_id:
            raise ValueError("interaction does not belong to the active Run suspension")
        receipt = await self.runtime.reply_interaction(
            ReplyInteraction(
                run_id=run_id,
                suspension_id=suspension.suspension_id,
                interaction_id=interaction_id,
                expected_revision=run.revision,
                expected_suspension_revision=suspension.expected_revision,
                expected_interaction_revision=interaction.expected_revision,
                decision=decision,
                payload=payload,
                idempotency_key=new_id("interaction"),
            ),
            context,
        )
        if receipt.decision.value != "rejected":
            try:
                if decision == "approve_and_remember":
                    await self._remember_approved_shell_command(
                        run_id=run_id,
                        interaction=interaction,
                        user_id=user_id,
                    )
            finally:
                await self._continue(run_id, user_id)
        await self._index_session(run.session_id)
        return receipt

    async def _remember_approved_shell_command(
        self,
        *,
        run_id: str,
        interaction,
        user_id: str,
    ) -> str:
        if "approve_and_remember" not in interaction.allowed_decisions:
            raise ValueError("this approval cannot be remembered")
        payload = interaction.payload
        if payload.get("tool_name") != "execute_shell_command":
            raise ValueError("only shell command approvals can be remembered")
        arguments = payload.get("arguments")
        command_value = (
            arguments.get("command") if isinstance(arguments, dict) else None
        )
        command = normalize_shell_command(command_value)
        if not command:
            raise ValueError("shell approval has no command to remember")

        start_command = await self.session_store.get_start_command(run_id)
        agent = await self._agent(start_command.agent_id, user_id)
        config = dict(agent.config or {})
        remembered = {
            normalized
            for value in config.get("approvedShellCommands") or ()
            if (normalized := normalize_shell_command(value))
        }
        remembered.add(command)
        config["approvedShellCommands"] = sorted(remembered)
        await self.catalog.save_agent(
            agent.model_copy(update={"config": config, "updated_at": utc_now()})
        )

        driver = self._drivers.get(run_id)
        assessor = (
            getattr(driver.loop.tool_policy, "operation_assessor", None)
            if driver is not None and driver.loop is not None
            else None
        )
        if isinstance(assessor, ShellCommandOperationAssessor):
            assessor.approve_command(command)
        return command

    async def _continue(self, run_id: str, user_id: str) -> None:
        await self.start()
        self._ensure_run_observer(run_id)
        command = await self.session_store.get_start_command(run_id)
        agent = await self._agent_for_command(command, user_id)
        memory_enabled = _agent_memory_enabled(
            agent, self.memory_plugin_id, self.session_memory_plugin_id
        )
        driver = self._drivers.get(run_id)
        if driver is None:
            provider = await self._provider_for_command(command, agent, user_id)
            workspace_id = command.config.metadata.get("workspace_id")
            workspace = await self.workspace_root(workspace_id, command.agent_id)

            async def build_driver():
                return await self._build_loop(
                    agent=agent,
                    provider=provider,
                    workspace=workspace,
                    preferred_skills=tuple(
                        command.config.metadata.get("preferred_skills") or ()
                    ),
                    approval_mode=str(
                        command.config.metadata.get("approval_mode") or "high_risk"
                    ),
                    invocation_mode=command.invocation_mode or "normal",
                    session_id=(await self.runtime.get_run(run_id)).session_id,
                    run_id=run_id,
                    resolved_spec_hash=command.resolved_spec_hash,
                    component_snapshot=command.config.metadata.get(
                        "runtime_components"
                    ),
                )

            driver = _DesktopDriver(
                self, None, workspace, None, lazy_builder=build_driver
            )
            self._drivers[run_id] = driver
        facade = SAgent(
            runtime=self.runtime,
            driver_factory=lambda _: driver,
            memory_service=(self.memory_service if memory_enabled else None),
            memory_scope={
                "recall": memory_enabled,
                "auto_write": memory_enabled,
                "scope": "agent",
                "recall_limit": 8,
            },
        )
        facade.attach_dispatcher(self.dispatcher)
        task = await facade.continue_run(
            run_id,
            self._context(
                user_id,
                language=str(command.config.metadata.get("response_language") or "en"),
            ),
        )
        task.add_done_callback(
            lambda _completed, agent=facade: self._schedule_agent_close(agent)
        )
        task.add_done_callback(
            lambda _completed, key=run_id, value=driver: asyncio.create_task(
                self._discard_driver_if_terminal(key, value)
            )
        )
        task.add_done_callback(
            lambda _completed, key=run_id: asyncio.create_task(self._index_run(key))
        )

    def _discard_driver(self, run_id: str, driver: _DesktopDriver) -> None:
        if self._drivers.get(run_id) is driver:
            self._drivers.pop(run_id, None)

    def _schedule_agent_close(self, agent: SAgent) -> None:
        task = asyncio.create_task(agent.close())
        self._application_close_tasks.add(task)

        def completed(value: asyncio.Task) -> None:
            self._application_close_tasks.discard(value)
            if value.cancelled():
                return
            error = value.exception()
            if error is not None:
                self.logger.exception(
                    "agent.close_failed",
                    "Per-Run SAgent failed to close",
                    error,
                )

        task.add_done_callback(completed)

    def _schedule_blocked_sandbox_cleanup(
        self, resources, lifecycle, record, context: RequestContext
    ) -> None:
        async def cleanup() -> None:
            try:
                await asyncio.gather(
                    *(
                        lifecycle.job_runtime.wait(job_id)
                        for job_id in record.blocking_job_ids
                    )
                )
                future = await self.dispatcher.submit_cleanup(
                    run_id=record.run_id,
                    context=context,
                    generation=record.generation,
                    operation=lambda: lifecycle.reconcile_run(
                        run_id=record.run_id, context=context
                    ),
                )
                settled = await future
                if settled.state in {
                    ExecutionResourceState.RELEASE_REQUESTED,
                    ExecutionResourceState.RELEASE_FAILED,
                }:
                    self._schedule_sandbox_reconcile_loop(
                        lifecycle=lifecycle,
                        record=settled,
                        context=context,
                    )
            finally:
                resources.defer_close = False
                await resources.close_now()

        task = asyncio.create_task(
            cleanup(), name=f"sandbox-cleanup:{record.run_id}:{record.generation}"
        )
        self._sandbox_cleanup_tasks.add(task)
        task.add_done_callback(self._sandbox_cleanup_completed)

    def _sandbox_cleanup_completed(self, task: asyncio.Task) -> None:
        self._sandbox_cleanup_tasks.discard(task)
        if task.cancelled():
            return
        error = task.exception()
        if error is not None:
            self.logger.exception(
                "sandbox.cleanup_task_failed",
                "Background sandbox cleanup failed",
                error,
            )

    async def _recover_pending_sandbox_cleanups(self) -> None:
        """Resume cleanup intents whose owning process disappeared while paused."""

        for record in await self.session_store.list_pending_execution_releases():
            if (
                record.state == ExecutionResourceState.RELEASE_BLOCKED
                and record.release_disposition == SandboxReleaseDisposition.DETACH
            ):
                continue
            try:
                run = await self.session_store.get_run(record.run_id)
                session = await self.session_store.get_session(run.session_id)
                if session.owner is None:
                    continue
                command = await self.session_store.get_start_command(record.run_id)
                context = self._context(
                    session.owner.principal_id,
                    language=str(
                        command.config.metadata.get("response_language") or "en"
                    ),
                )
                provider = self._sandbox_provider(record.sandbox_ref.provider_id)
                lifecycle = ExecutionBindingLifecycleCoordinator(
                    sandbox_provider=provider,
                    session_store=self.driver_session_store,
                    job_runtime=InMemoryJobRuntime({}),
                )
                self._schedule_sandbox_reconcile_loop(
                    lifecycle=lifecycle,
                    record=record,
                    context=context,
                )
            except Exception as exc:
                self.logger.warning(
                    "sandbox.cleanup_recovery_failed",
                    "Failed to schedule pending sandbox cleanup",
                    attributes={"run_id": record.run_id, "error": str(exc)},
                )

    def _schedule_sandbox_reconcile_loop(
        self, *, lifecycle, record, context: RequestContext
    ) -> None:
        async def reconcile() -> None:
            current = record
            attempt = current.retry_count
            while current.state in {
                ExecutionResourceState.RELEASE_BLOCKED,
                ExecutionResourceState.RELEASE_REQUESTED,
                ExecutionResourceState.RELEASE_FAILED,
            }:
                if current.next_retry_at is not None:
                    delay = (current.next_retry_at - utc_now()).total_seconds()
                    if delay > 0:
                        await asyncio.sleep(min(delay, 300))
                future = await self.dispatcher.submit_cleanup(
                    run_id=current.run_id,
                    context=context,
                    generation=current.generation,
                    attempt=attempt,
                    operation=lambda: lifecycle.reconcile_run(
                        run_id=current.run_id, context=context
                    ),
                )
                current = await future
                if (
                    current.state == ExecutionResourceState.RELEASE_BLOCKED
                    and current.release_disposition == SandboxReleaseDisposition.DETACH
                ):
                    return
                attempt += 1

        task = asyncio.create_task(
            reconcile(), name=f"sandbox-reconcile:{record.run_id}:{record.generation}"
        )
        self._sandbox_cleanup_tasks.add(task)
        task.add_done_callback(self._sandbox_cleanup_completed)

    async def _discard_driver_if_terminal(
        self, run_id: str, driver: _DesktopDriver
    ) -> None:
        try:
            run = await self.runtime.get_run(run_id)
        except Exception:
            return
        if run.state in TERMINAL_RUN_STATES or run.state == RunState.SUSPENDED:
            try:
                await driver.close_binding()
            except BaseException as exc:
                self.logger.exception(
                    "driver.close_failed",
                    "Run driver cleanup failed and remains available for retry",
                    exc,
                    run_id=run_id,
                )
                return
            self._discard_driver(run_id, driver)

    def _ensure_run_observer(self, run_id: str) -> None:
        current = self._run_observers.get(run_id)
        if current is not None and not current.done():
            return
        task = asyncio.create_task(
            self._observe_run(run_id),
            name=f"desktop-log-observer:{run_id}",
        )
        self._run_observers[run_id] = task
        task.add_done_callback(
            lambda completed, key=run_id: (
                self._run_observers.pop(key, None)
                if self._run_observers.get(key) is completed
                else None
            )
        )

    async def _observe_run(self, run_id: str) -> None:
        try:
            async for event in self.runtime.subscribe_events(
                EventCursor(run_id=run_id, run_sequence=0)
            ):
                self._write_runtime_event(event)
                if event.type in {
                    "run.completed",
                    "run.failed",
                    "run.cancelled",
                }:
                    return
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.logger.exception(
                "agent.run.observer_failed",
                "Agent run log observer failed",
                exc,
                run_id=run_id,
            )

    def _write_runtime_event(self, event) -> None:
        if event.data.kind in {"item", "usage", "protocol"}:
            return
        data = event.data.model_dump(mode="json", exclude_none=True)
        data.pop("arguments", None)
        runtime_error = data.pop("error", None)
        level = (
            LogLevel.ERROR
            if event.type.endswith(".failed") or runtime_error is not None
            else LogLevel.WARNING
            if event.type.endswith(".unknown")
            or event.type.endswith(".cancelled")
            or event.type.endswith(".rejected")
            else LogLevel.INFO
        )
        tool_call_id = data.get("tool_call_id")
        self.log_sink.write(
            LogRecord(
                level=level,
                event=event.type,
                message=f"Runtime event {event.type}",
                component=f"agent.{event.source.source_type.value}",
                process_id=os.getpid(),
                session_id=event.session_id,
                run_id=event.run_id,
                turn_id=event.turn_id,
                step_id=event.step_id,
                tool_call_id=(str(tool_call_id) if tool_call_id is not None else None),
                correlation_id=event.correlation_id,
                error=(
                    LogError(
                        type="RuntimeErrorInfo",
                        message=str(runtime_error.get("message") or "Runtime failure"),
                        code=runtime_error.get("code"),
                        category=runtime_error.get("category"),
                    )
                    if isinstance(runtime_error, dict)
                    else None
                ),
                attributes={
                    "event_id": event.event_id,
                    "run_sequence": event.run_sequence,
                    "session_sequence": event.session_sequence,
                    "durability": event.durability.value,
                    "source_id": event.source.source_id,
                    "data": data,
                },
            )
        )
