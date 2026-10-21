from __future__ import annotations

import asyncio
import json
import logging
import os
from collections.abc import AsyncIterator
from typing import Any


from app.v2.desktop.backend.shell_policy import (
    normalize_shell_command,
)
from sagents.v2.contracts.commands import (
    CancelRun,
    InputItem,
    PauseRun,
    ReplyInteraction,
    ResumeRun,
    SteerRun,
)
from sagents.v2.contracts.common import new_id, utc_now
from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo, SageV2Error
from sagents.v2.contracts.run_state import (
    EventCursor,
    RunState,
    SessionConcurrencyMode,
    TERMINAL_RUN_STATES,
)
from sagents.v2.package.manifest.resolver import CompositionResolver
from sagents.v2.runtime.observability import (
    LogError,
    LogLevel,
    LogRecord,
)
from app.v2.desktop.backend.schemas import (
    DesktopRunRequest,
    RunMessage,
    RunMessageContent,
)
from app.v2.desktop.backend.run_composition import DesktopRunCompositionMixin
from app.v2.desktop.backend.studio import STUDIO_TOOLS
from app.v2.desktop.backend.openui import OpenUiProjector
from app.v2.desktop.backend.runtime_config import (
    _SKILL_NAME,
    _TOOL_NAME,
)
from app.v2.desktop.backend.usage_analytics import (
    _usage_percentile as _usage_percentile,
)

LOGGER = logging.getLogger(__name__)


class DesktopRunServiceMixin(DesktopRunCompositionMixin):
    """Run commands, recovery, and per-Run composition for Desktop v2."""

    async def run_events(
        self, request: DesktopRunRequest, user_id: str
    ) -> AsyncIterator[str]:
        request = request.model_copy(deep=True)
        await self.start()
        action_surface = None
        if request.openui_action is not None:
            action_surface, request, replay_run = await self._prepare_openui_action(
                request, user_id
            )
            if replay_run:
                run = await self.session_access.get_run(
                    replay_run, self._context(user_id)
                )
                yield (
                    json.dumps(
                        {
                            "kind": "stream.opened",
                            "handle": {
                                "run_id": run.run_id,
                                "session_id": run.session_id,
                            },
                        }
                    )
                    + "\n"
                )
                async for line in self.subscribe_events(replay_run, 0, user_id):
                    yield line
                return
        accepted_handle = None
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
            environment = await self._capture_run_environment(request, user_id)
            agent = environment.agents[request.agent_id]
            provider = environment.provider(agent)
            workspace = environment.workspace
            mcp_definitions = await environment.mcp.list_tools(
                run_id="desktop-admission"
            )
            configured_tools = agent.config.get("availableTools")
            valid_tools = tuple(
                value
                for value in (
                    configured_tools
                    if configured_tools is not None
                    else tuple(
                        value.name
                        for value in (
                            *self._native_tool_definitions(),
                            *mcp_definitions,
                        )
                    )
                )
                if isinstance(value, str)
                and _TOOL_NAME.fullmatch(value)
                and value not in STUDIO_TOOLS
            )
            valid_skills = tuple(
                value
                for value in (agent.config.get("availableSkills") or ())
                if isinstance(value, str) and _SKILL_NAME.fullmatch(value)
            )
            if valid_skills and "load_skill" not in valid_tools:
                valid_tools = (*valid_tools, "load_skill")
            resolved = CompositionResolver().resolve(
                self._manifest(agent, provider, valid_tools, valid_skills),
                models=self._model_catalog(agent, provider),
            )
            command = self._command(
                request,
                resolved,
                agent=agent,
                provider=provider,
                workspace=workspace,
                environment=environment,
            )
            command = command.model_copy(
                update={
                    "config": command.config.model_copy(
                        update={
                            "metadata": {
                                **command.config.metadata,
                                "desktop_environment": environment.snapshot,
                            }
                        }
                    )
                },
                deep=True,
            )
            context = self._context(
                user_id,
                language=str(command.config.metadata.get("response_language") or "en"),
            )
            from sagents.v2.contracts.principals import MemoryIdentity
            memory_workspace = request.workspace_id
            if not memory_workspace or memory_workspace.startswith("agent:"):
                memory_workspace = "default"
            context = context.model_copy(update={"memory_identity": MemoryIdentity(
                user_id=user_id,
                workspace_id=f"desktop:{memory_workspace}:{agent.agent_id}",
            )})
            loaded = await self._load_run_agent(
                agent, self._manifest(agent, provider, valid_tools, valid_skills), command,
                models=self._model_catalog(agent, provider), environment=environment,
            )
            command = command.model_copy(update={
                "agent_id": loaded.id, "resolved_spec_hash": loaded.composition_hash,
            })
            stream = await self.application.entrypoint().run_stream(command, context, agent=loaded)
            accepted_handle = stream.handle
            if action_surface is not None:
                self.openui_store.accepted(action_surface, accepted_handle.run_id)
            self._run_environments.setdefault(accepted_handle.run_id, environment)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            run_logger.exception(
                "agent.run.start_failed",
                "Agent run failed before execution started",
                exc,
                attributes={"agent_id": request.agent_id},
            )
            from sagents.v2.i18n import localize_error

            error = exc.info if isinstance(exc, SageV2Error) else RuntimeErrorInfo(
                code="desktop.run_start_failed",
                category=ErrorCategory.VALIDATION if isinstance(exc, (ValueError, FileNotFoundError, PermissionError)) else ErrorCategory.INTERNAL,
                message=str(exc), safe_to_resume=False,
            )
            raise SageV2Error(localize_error(error, request.response_language or (await self.get_settings()).language)) from exc
        await self._index_session(stream.handle.session_id)
        self._ensure_run_observer(stream.handle.run_id)
        self.logger.info(
            "agent.run.opened",
            "Agent run stream opened",
            session_id=stream.handle.session_id,
            run_id=stream.handle.run_id,
            attributes={"agent_id": request.agent_id},
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
        projector = OpenUiProjector(self, user_id)
        observed_boundary = False
        try:
            async for event in stream.events:
                yield event.model_dump_json() + "\n"
                for frame in await projector.project(event):
                    yield json.dumps(frame, ensure_ascii=False) + "\n"
            observed_boundary = True
        finally:
            if observed_boundary:
                await stream.wait()
            await self._index_session(stream.handle.session_id)

    async def _prepare_openui_action(self, request, user_id):
        action = request.openui_action
        if (
            not request.session_id
            or request.session_concurrency_mode != SessionConcurrencyMode.SERIAL
            or request.studio_id
        ):
            raise ValueError(
                "UI submission requires its original, serial Desktop Session"
            )
        context = self._context(user_id)
        runs = await self.session_access.list_session_runs(request.session_id, context)
        surface = self.openui_store.get(user_id, request.session_id, action.surface_id)
        if (
            surface is None
            or surface["revision"] != action.revision
            or surface["agent_id"] != request.agent_id
        ):
            raise ValueError(
                "UI does not belong to this Agent and Session, or has been replaced"
            )
        source = next((run for run in runs if run.run_id == surface["run_id"]), None)
        if source is None or source.state != RunState.COMPLETED:
            raise ValueError("Wait for the UI's Run to complete before submitting")
        if (
            not surface.get("submitted")
            and max(runs, key=lambda run: run.created_at).run_id != source.run_id
        ):
            raise ValueError(
                "This UI belongs to an earlier turn; use the latest result"
            )
        values, replay = self.openui_store.claim(surface, action.action, action.values)
        from app.v2.desktop.backend.openui import validate_tree

        fields, actions = validate_tree(surface["tree"])
        text = actions[action.action]
        if values:
            text += "\n" + "\n".join(
                f"{fields[key]['label']}: {json.dumps(value, ensure_ascii=False)}"
                for key, value in values.items()
            )
        normalized = request.model_copy(
            update={
                "messages": [RunMessage(role="user", text=text)],
                "attachment_paths": [],
                "preferred_skills": [],
                "idempotency_key": "openui:" + self.openui_store.submission_id(surface),
            }
        )
        return surface, normalized, replay

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
        self,
        run_id: str,
        after_sequence: int,
        user_id: str,
        *,
        preview_sequence: int = 0,
        preview_epoch: str | None = None,
    ) -> AsyncIterator[str]:
        await self.start()
        context = self._context(user_id)
        projector = OpenUiProjector(self, user_id)
        cursor = 0
        while cursor < after_sequence:
            previous = await self.session_access.read_events(
                run_id, context, after_sequence=cursor, limit=500
            )
            previous = tuple(
                event for event in previous if event.run_sequence <= after_sequence
            )
            if not previous:
                break
            for event in previous:
                projector.remember(event)
            cursor = previous[-1].run_sequence
        # The projector needs the already-delivered prefix as well as the
        # suffix sent over the wire, since text previews are not in the ledger.
        if preview_epoch is not None and preview_sequence:
            previews = await self.session_access.read_stream_previews(run_id, context)
            for event in previews:
                if (
                    event.preview_epoch == preview_epoch
                    and (event.preview_sequence or 0) <= preview_sequence
                ):
                    projector.remember(event)
        async for event in self.session_access.subscribe_events(
            EventCursor(
                run_id=run_id,
                run_sequence=after_sequence,
                preview_sequence=preview_sequence,
                preview_epoch=preview_epoch,
            ),
            context,
        ):
            yield event.model_dump_json() + "\n"
            for frame in await projector.project(event):
                yield json.dumps(frame, ensure_ascii=False) + "\n"
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
        # Restore the admitted revision before accepting a durable transition.
        # Missing/corrupt archives must leave the suspension answerable.
        await self.application.agent_for_run(run_id, context)
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
        await self.application.agent_for_run(run_id, context)
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
        agent = await self._agent(start_command.config.metadata.get("agent_runtime", {}).get("agent_id", start_command.agent_id), user_id)
        config = dict(agent.config or {})
        remembered = {
            normalized
            for value in config.get("approvedShellCommands") or ()
            if (normalized := normalize_shell_command(value))
        }
        remembered.add(command)
        config["approvedShellCommands"] = sorted(remembered)
        async with self._agent_update_lock:
            current = await self._agent(agent.agent_id, user_id)
            merged = dict(current.config)
            merged["approvedShellCommands"] = sorted(
                set(merged.get("approvedShellCommands") or ()) | {command}
            )
            updated = current.model_copy(
                update={"config": merged, "updated_at": utc_now()}
            )
            await self._record_agent_version(current)
            await self._record_agent_version(updated)
            await self.catalog.save_agent(updated)

        return command

    async def _continue(self, run_id: str, user_id: str) -> None:
        await self.start()
        self._ensure_run_observer(run_id)
        command = await self.session_store.get_start_command(run_id)
        context = self._context(user_id, language=str(command.config.metadata.get("response_language") or "en"))
        loaded = await self.application.agent_for_run(run_id, context)
        task = await self.application.entrypoint().continue_run(run_id, context, agent=loaded)
        task.add_done_callback(lambda _completed: asyncio.create_task(self._index_run(run_id)))

    async def _load_run_agent(self, agent, manifest, command, *, models, environment):
        """Freeze product configuration; Sage owns all execution assembly."""
        from .sdk_plugins import desktop_run_selections
        from sagents.v2.package.manifest.runtime import CapabilitySelection
        from sagents.v2.runtime.execution.configuration import LocalExecutionPolicy
        from sagents.v2.runtime.execution.sandbox import FileOperation
        from .runtime_config import _resolved_sandbox_config
        if not hasattr(self, "_loaded_agent_lock"):
            self._loaded_agent_lock = asyncio.Lock()
        async with self._loaded_agent_lock:
            selections = desktop_run_selections()
            runtime = self.application.runtime_configuration
            snapshot = command.config.metadata["runtime_components"]
            # The settings translator only produces serializable plugin parameters.
            from .package import desktop_v2_manifest
            configured = desktop_v2_manifest(
                session_root=self.runtime_root, component_selections=snapshot["selections"],
                component_configs=snapshot["configs"],
                language=command.config.metadata.get("response_language") or "en",
            ).runtime
            identity_caps = {"session.store", "derived-state.store", "execution.scheduler", "execution.job-runtime",
                             "observability.provider"}
            capabilities = {**runtime.capabilities, **{
                key: value for key, value in configured.capabilities.items() if key not in identity_caps
            }, **selections}
            official = CapabilitySelection(plugin="sage.tool.official")
            external = CapabilitySelection(plugin="com.sage.desktop.run.tool-provider", scope="run", grant_tools=True)
            capabilities["tool.provider"] = (official, external)
            from sagents.v2.package.manifest.runtime import RuntimeConfig
            supplied = RuntimeConfig.model_validate(self._host_runtime) if self._host_runtime is not None else None
            raw = snapshot["configs"].get("execution.sandbox", {})
            from .schemas import DesktopV2Settings
            sandbox_plugin, sandbox = _resolved_sandbox_config(DesktopV2Settings(
                component_selections=snapshot["selections"], component_configs=snapshot["configs"],
            ))
            if sandbox_plugin not in {"sage.sandbox.local-workspace", "sage.sandbox.ephemeral"} and not (supplied and "execution.binding" in supplied.capabilities):
                raise ValueError("Select a registered execution.binding implementation for this sandbox provider")
            policy = LocalExecutionPolicy.model_validate({
                **({"filesystem": raw["filesystem"]} if "filesystem" in raw else {}),
                **({"process": raw["process"]} if "process" in raw else {}),
                "resources": sandbox["resources"], "network": sandbox.get("network", {}),
            })
            if command.invocation_mode == "plan":
                policy = policy.narrow({"filesystem": {"allowed_operations": [FileOperation.READ, FileOperation.LIST]},
                                        "process": {"read_only": True}})
            capabilities["execution.binding"] = CapabilitySelection(
                plugin="sage.execution.binding.local-workspace", config={
                    "workspace": str(environment.workspace),
                    "private_workspace_root": str(self.runtime_root / "private-workspaces"),
                    "policy": policy.model_dump(mode="json"),
                    **{key: raw[key] for key in ("command_path", "read_paths", "isolation_python", "child_workspace_policy",
                                                "linux_cgroup_root", "linux_quota_mount", "linux_execution_uid", "linux_execution_gid") if key in raw},
                },
            )
            if sandbox_plugin == "sage.sandbox.ephemeral":
                capabilities["execution.binding"] = CapabilitySelection(
                    plugin="sage.execution.binding.ephemeral", config={
                        "workspace_root": sandbox["workspace_root"],
                        "policy": policy.model_copy(update={"process": policy.process.model_copy(update={"enabled": False})}).model_dump(mode="json"),
                    },
                )
            if supplied is not None:
                capabilities.update(supplied.capabilities)
            runtime = runtime.model_copy(update={"capabilities": capabilities})
            await self.application.update_runtime(runtime)
            # Every declared member receives its own frozen route in the App model catalog.
            from sagents.v2.model.catalog import ModelCatalogConfig
            routes, credentials = dict(models.models), dict(models.credentials)
            definitions = dict(manifest.agents)
            pending = [agent.agent_id]
            visited = set()
            while pending:
                source_id = pending.pop()
                if source_id in visited:
                    continue
                visited.add(source_id)
                source = environment.agents[source_id]
                provider = environment.provider(source)
                candidate = self._manifest(source, provider,
                    tuple(source.config.get("availableTools") or ()), tuple(source.config.get("availableSkills") or ()))
                definition = candidate.agents[source_id]
                from .runtime_config import _continuation_agent_instructions
                completion = runtime.capabilities["agent.continuation-policy"].plugin
                instructions = definition.instructions.model_copy(update={
                    "inline": (definition.instructions.inline or "") + _continuation_agent_instructions(completion),
                })
                definition = definition.model_copy(update={
                    "instructions": instructions,
                    "tools": tuple(name for name in definition.tools
                                   if name != "turn_status" or completion != "sage.agent.continuation.llm-judge"),
                })
                mode = str(source.config.get("agentMode") or "simple").lower()
                manual = source.config.get("subAgentSelectionMode") == "manual"
                members = tuple(str(value) for value in source.config.get("availableSubAgentIds") or ()) if manual else tuple(
                    key for key in environment.agents if key != source_id)
                # Automatic members are delegation leaves. Nested Teams must declare their direct roster.
                if source_id != agent.agent_id and not manual:
                    mode, members = "simple", ()
                if mode == "simple":
                    members = ()
                missing = set(members) - set(environment.agents)
                if missing:
                    raise ValueError(f"Desktop roster contains unavailable Agents: {sorted(missing)}")
                if source_id == agent.agent_id and command.config.metadata.get("ui_preference") == "interactive":
                    if "sage-openui" not in definition.skills:
                        raise ValueError("Interactive presentation requires the enabled sage-openui Skill")
                    definition = definition.model_copy(update={"preload_skills": ("sage-openui",)})
                definition = definition.model_copy(update={"mode": mode, "subagents": members})
                if source_id != agent.agent_id:
                    definitions[source_id] = definition
                else:
                    definitions[source_id] = definition.model_copy(update={"mode": mode, "subagents": members})
                pending.extend(members)
                catalog = self._model_catalog(source, provider)
                routes.update(catalog.models)
                credentials.update(catalog.credentials)
            await self.application.update_models(ModelCatalogConfig(models=routes, credentials=credentials))
            async def load(source_id, ancestors=()):
                if source_id in ancestors:
                    raise ValueError("Desktop Team declarations contain a cycle")
                source = environment.agents[source_id]
                provider = environment.provider(source)
                package = manifest if source_id == agent.agent_id else self._manifest(
                    source, provider, definitions[source_id].tools, definitions[source_id].skills)
                package = package.model_copy(update={"agents": {source_id: definitions[source_id]}})
                children = {name: await load(name, (*ancestors, source_id)) for name in definitions[source_id].subagents}
                current = next((value for value in self.application.loaded_agents if value.package_id == package.metadata.id), None)
                if current is None:
                    return await self.application.load_agent(package, subagents=children)
                return await self.application.update_agent(agent=current, package=package, subagents=children)
            return await load(agent.agent_id)

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
                if event.type == "run.completed":
                    await self.publish_studio_run_result(run_id)
                if event.type in {
                    "run.completed",
                    "run.failed",
                    "run.cancelled",
                }:
                    self._run_environments.pop(run_id, None)
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
