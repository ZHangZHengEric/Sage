"""Project standard SAgents v2 Run events into the local voice pipeline."""

import asyncio
import os
from pathlib import Path
from uuid import uuid4

from sagents.v2 import ActorRef, RequestContext, SAgentBuilder, StartRun
from sagents.v2.contracts.commands import CancelRun, InputItem, RunConfig
from sagents.v2.contracts.errors import SageV2Error
from sagents.v2.contracts.events import ToolEventData
from sagents.v2.contracts.items import (
    JsonBlock,
    MessageItemData,
    TextBlock,
    ToolResultItemData,
)
from sagents.v2.contracts.principals import PrincipalType
from sagents.v2.contracts.run_state import TERMINAL_RUN_STATES
from sagents.v2.package.manifest import SageManifest
from sagents.v2.runtime.execution.configuration import LocalExecutionPolicy

from .voice_pipeline.agent import ToolActivity
from .voice_pipeline.tool_speech import tool_speech_target


VOICE_INSTRUCTIONS = (
    "You are Sage Voice, a conversational assistant. Reply in the user's language. "
    "Speak naturally, usually in one to three short sentences. Use plain text suitable "
    "for speech. Avoid markdown, long URLs, and filler. If the user changes direction "
    "or interrupts, respond to their latest request. The voice interface can "
    "announce long waits. Avoid filler before calling a tool."
)


class SageVoiceAgent:
    """One lightweight, text-only SAgents host for the current conversation."""

    def __init__(self, settings, root: Path):
        self.settings = settings
        self.root = root
        self.context = RequestContext(
            actor=ActorRef(
                principal_id="sage-voice-user", principal_type=PrincipalType.USER
            )
        )
        self.app = None
        self.agent = None
        self.session_id = None

    async def start(self):
        if self.app is not None:
            return
        os.environ["SAGE_VOICE_MODEL_API_KEY"] = (
            self.settings.model_api_key.get_secret_value()
        )
        builder = SAgentBuilder()
        tool_capabilities = {}
        tool_names = self.settings.enabled_tools
        if tool_names:
            tool_capabilities["tool.provider"] = {"plugin": "sage.tool.official"}
            workspace = self.root / "workspace"
            workspace.mkdir(parents=True, mode=0o700, exist_ok=True)
            policy = (
                LocalExecutionPolicy()
                .narrow(
                    {"process": {"enabled": False}}
                    if not {"execute_shell_command", "read_lints"}.intersection(
                        tool_names
                    )
                    else None
                )
                .model_dump(mode="json")
            )
            if "fetch_webpages" in tool_names:
                policy["network"].update(
                    mode="http_requests", allowed_schemes=["http", "https"]
                )
            tool_capabilities["execution.binding"] = {
                "plugin": "sage.execution.binding.local-workspace",
                "config": {
                    "workspace": str(workspace),
                    "policy": policy,
                },
            }
            if "search_memory" in tool_names:
                tool_capabilities["session-memory.provider"] = {
                    "plugin": "sage.session-memory.sqlite-bm25",
                }
            tool_capabilities["agent.tool-policy"] = {
                "plugin": "sage.agent.tool-policy.default",
                "config": {"approval_strategy": "auto_approve"},
            }
            tool_capabilities["tool.selection-policy"] = {
                "plugin": "sage.tool-selection.direct",
            }
        app = await builder.build(
            runtime={
                "state_root": str(self.root),
                "capabilities": {
                    **tool_capabilities,
                    "session.store": {
                        "plugin": "sage.session.ephemeral",
                    },
                    "context.reducer": {
                        "plugin": "sage.context.reducer.window",
                    },
                    "context.summarizer": {
                        "plugin": "sage.context.summarizer.extractive",
                    },
                    "agent.continuation-policy": {
                        "plugin": "sage.agent.continuation.deterministic",
                    },
                },
            },
            models={
                "credentials": {
                    "voice-key": {"source": "env", "key": "SAGE_VOICE_MODEL_API_KEY"}
                },
                "models": {
                    "primary": {
                        "provider": "openai-chat-completions",
                        "base_url": self.settings.model_base_url,
                        "model": self.settings.model,
                        "credential": "voice-key",
                        "request": self.settings.model_request(),
                        "capabilities": {
                            "tool_calling": bool(tool_names),
                            "multimodal": "analyze_image" in tool_names,
                            "reasoning": self.settings.reasoning_effort
                            not in (None, "none"),
                        },
                    }
                },
            },
        )
        try:
            self.agent = await app.load_agent(
                SageManifest.model_validate(
                    {
                        "schema_version": "sage/v2",
                        "kind": "agent-package",
                        "metadata": {
                            "id": "sage.voice",
                            "version": "1.0.0",
                            "name": "Sage Voice",
                        },
                        "agents": {
                            "main": {
                                "name": "Sage Voice",
                                "mode": "simple",
                                "models": {"primary": "primary"},
                                "instructions": {
                                    "inline": self.settings.system_prompt
                                    or VOICE_INSTRUCTIONS
                                },
                                "tools": tool_names,
                                "skills": [],
                                "memory": {"recall": False, "auto_write": False},
                            }
                        },
                        "entrypoint": {"agent": "main"},
                    }
                )
            )
        except BaseException:
            await app.close()
            raise
        self.app = app

    async def close(self):
        # The bridge owns the warm host across microphone on/off cycles.
        pass

    async def shutdown(self):
        if self.app is not None:
            await self.app.close()
            self.app = None

    def stream(self, prompt):
        assert self.app is not None and self.agent is not None
        return SageVoiceTurn(self, prompt)


class SageVoiceTurn:
    """Cancel the native Run when the voice pipeline interrupts or stops a turn."""

    def __init__(self, host: SageVoiceAgent, prompt: str):
        self.host = host
        self.failure = None
        self.completed = False
        # Goal runs require both Sage control tools to be explicitly enabled.
        goal_tools = {"goal_submit", "goal_complete"}
        command, _, goal = prompt.partition(" ")
        goal_mode = (
            command == "/goal"
            and bool(goal.strip())
            and goal_tools.issubset(host.settings.enabled_tools)
        )
        if goal_mode:
            prompt = goal.strip()
        self.admission = asyncio.create_task(
            host.app.entrypoint().run_stream(
                StartRun(
                    agent_id=host.agent.id,
                    resolved_spec_hash=host.agent.composition_hash,
                    session_id=host.session_id,
                    input=(InputItem(role="user", content=(TextBlock(text=prompt),)),),
                    idempotency_key=uuid4().hex,
                    invocation_mode="goal" if goal_mode else None,
                    config=RunConfig(
                        automatic_stage_continuation=False,
                        enabled_tools=host.settings.enabled_tools,
                    ),
                ),
                host.context,
                agent=host.agent,
            )
        )

    async def __aiter__(self):
        # Admission survives cancellation of the voice observer so aclose can
        # discover and cancel the Run even if barge-in precedes the first delta.
        stream = await asyncio.shield(self.admission)
        self.host.session_id = stream.handle.session_id
        streamed_items = set()
        tool_targets: dict[str, str | None] = {}
        questionnaire_items: set[str] = set()
        async for event in stream.events:
            delta = None
            if event.type == "message.delta" and isinstance(event.data.delta, str):
                streamed_items.add(event.item_id)
                delta = event.data.delta
            elif (
                event.type == "message.completed"
                and event.item_id not in streamed_items
            ):
                item = event.data.item
                if item is not None and isinstance(item.data, MessageItemData):
                    if item.data.role == "assistant":
                        delta = "".join(
                            block.text
                            for block in item.data.content
                            if isinstance(block, TextBlock)
                        )
            elif (
                event.type == "item.completed" and event.item_id in questionnaire_items
            ):
                item = event.data.item
                if item is not None and isinstance(item.data, ToolResultItemData):
                    for block in item.data.content:
                        if isinstance(block, JsonBlock) and isinstance(
                            block.value, dict
                        ):
                            if block.value.get("status") == "awaiting_user_input":
                                lines = [block.value["title"]]
                                for question in block.value["questions"]:
                                    lines.append(
                                        question.get("title") or question["question"]
                                    )
                                    lines.extend(
                                        option["label"]
                                        if isinstance(option, dict)
                                        else option
                                        for option in question.get("options", [])
                                    )
                                delta = "\n".join(lines)
            elif event.type == "run.failed":
                self.failure = event.data.error
            elif isinstance(event.data, ToolEventData):
                if (
                    event.type == "tool.call.succeeded"
                    and event.data.tool_name == "questionnaire_async"
                    and event.data.result_item_id is not None
                ):
                    questionnaire_items.add(event.data.result_item_id)
                if event.type == "tool.call.proposed":
                    tool_targets[event.data.tool_call_id] = tool_speech_target(
                        event.data.tool_name, event.data.arguments or {}
                    )
                elif event.type in {
                    "tool.call.started",
                    "tool.call.received",
                    "tool.call.succeeded",
                    "tool.call.failed",
                    "tool.call.unknown",
                    "tool.call.cancelled",
                }:
                    yield ToolActivity(
                        event.data.tool_call_id,
                        event.data.tool_name,
                        event.type == "tool.call.started",
                        tool_targets.pop(event.data.tool_call_id, None),
                    )
            if delta:
                yield delta
        snapshot = await stream.wait()
        if snapshot.state.value != "completed":
            raise RuntimeError(
                self.failure.message
                if self.failure
                else f"Sage Run {snapshot.state.value}"
            )
        self.completed = True

    async def aclose(self):
        try:
            stream = await asyncio.shield(self.admission)
        except Exception:
            # The iterator reports the admission error. There is no Run to cancel.
            return
        self.host.session_id = stream.handle.session_id
        if self.completed:
            await stream.detach()
            return
        app = self.host.app
        context = self.host.context
        run_id = stream.handle.run_id
        try:
            for attempt in range(5):
                snapshot = await app.service("session.access").get_run(run_id, context)
                if snapshot.state in TERMINAL_RUN_STATES:
                    break
                try:
                    await app.runtime.cancel_run(
                        CancelRun(
                            run_id=run_id,
                            expected_revision=snapshot.revision,
                            idempotency_key=uuid4().hex,
                            reason="voice_turn_interrupted",
                        ),
                        context,
                    )
                except SageV2Error as error:
                    if error.info.code != "run.revision_conflict" or attempt == 4:
                        raise
                else:
                    break
            await stream.wait()
        finally:
            await stream.detach()
