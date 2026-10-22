"""Optional τ-bench v1.0.1 transport adapter for the real SAgents runtime.

The official orchestrator executes every domain call. The native Sage tool
executor waits for that result, so both ledgers record the same operation;
the adapter never executes a domain mutation twice. Import requires tau2.
"""

from __future__ import annotations

import asyncio
from contextlib import suppress

from tau2.agent.base_agent import HalfDuplexAgent
from tau2.data_model.message import (
    AssistantMessage, MultiToolMessage, ToolCall as TauToolCall, ToolMessage,
    UserMessage,
)

from sagents.v2.contracts.items import TextBlock
from sagents.v2.tool.contracts import ToolDefinition, ToolExecutionResult


class TauToolBridge:
    def __init__(self, tools, on_progress=None):
        self.definitions = tuple(
            ToolDefinition(
                name=t.name,
                description=t.openai_schema["function"]["description"],
                input_schema=t.openai_schema["function"]["parameters"],
                strict=False,
            )
            for t in tools
        )
        self.outbound = asyncio.Queue()
        self.pending = {}
        self.turn_task = None
        self.observations = []
        self.on_progress = on_progress or (lambda value: None)
        self.closed = False

    async def list_tools(self, *, run_id):
        return self.definitions

    async def get_tool(self, name, *, run_id):
        return next(t for t in self.definitions if t.name == name)

    async def execute(self, call, context):
        self.on_progress({"kind": "domain_tool", "name": call.tool_name})
        future = asyncio.get_running_loop().create_future()
        if call.tool_call_id in self.pending:
            raise RuntimeError("duplicate domain call identity")
        self.pending[call.tool_call_id] = future
        await self.outbound.put(AssistantMessage(
            role="assistant", tool_calls=[TauToolCall(
                id=call.tool_call_id, name=call.tool_name,
                arguments=call.arguments, requestor="assistant",
            )],
        ))
        try:
            message = await future
            # Domain argument errors are model-visible tool responses, matching
            # the official scaffold; no real external side effect is involved.
            return ToolExecutionResult(
                tool_call_id=call.tool_call_id, operation_id=call.operation_id,
                content=(TextBlock(text=message.content),),
                metadata={"tau_error": message.error, "tau_domain_call": True},
            )
        finally:
            self.pending.pop(call.tool_call_id, None)

    async def _send(self, session, content):
        try:
            observation = await session.send(content)
            self.observations.append(observation)
            self.on_progress({"kind": "sage_turn", "state": observation.state,
                              "turn": len(self.observations)})
            waiting_for_user = (observation.state == "suspended"
                                and observation.evidence.get("awaiting_user_input") is True
                                and bool(observation.output.strip()))
            if observation.state != "completed" and not waiting_for_user:
                raise RuntimeError(f"Sage turn ended {observation.state}")
            await self.outbound.put(AssistantMessage(
                role="assistant", content=observation.output,
                usage={"prompt_tokens": observation.input_tokens,
                       "completion_tokens": observation.output_tokens},
            ))
        except Exception as exc:
            await self.outbound.put(exc)

    async def advance(self, session, message, initial_history):
        if self.closed:
            raise RuntimeError("benchmark transport closed")
        if isinstance(message, UserMessage):
            if self.turn_task and not self.turn_task.done():
                raise RuntimeError("previous Sage turn is still active")
            content = message.content or ""
            if initial_history:
                # Only public conversation history, never task metadata/rubrics.
                import json
                content = "Prior conversation:\n" + json.dumps([
                    m.model_dump(mode="json", exclude_none=True)
                    for m in initial_history
                ]) + "\nCurrent user message:\n" + content
            self.turn_task = asyncio.create_task(self._send(session, content))
        else:
            messages = message.tool_messages if isinstance(message, MultiToolMessage) else [message]
            for item in messages:
                if not isinstance(item, ToolMessage) or item.id not in self.pending:
                    raise RuntimeError("unexpected official domain result")
                future = self.pending[item.id]
                if future.done():
                    raise RuntimeError("duplicate official domain result")
                future.set_result(item)
        result = await self.outbound.get()
        if isinstance(result, Exception):
            raise result
        return result

    async def close(self):
        if self.closed:
            return
        self.closed = True
        # Release a synchronous official agent blocked on the next message.
        await self.outbound.put(RuntimeError("benchmark transport closed"))
        if self.turn_task and not self.turn_task.done():
            self.turn_task.cancel()
            with suppress(asyncio.CancelledError):
                await self.turn_task
        for future in self.pending.values():
            future.cancel()


class SageTauAgent(HalfDuplexAgent):
    """Sync official agent interface backed by a live async Sage conversation."""

    def __init__(self, *, bridge, session, loop, domain_policy, tools):
        super().__init__(tools=tools, domain_policy=domain_policy)
        self.bridge, self.session, self.loop = bridge, session, loop

    def set_seed(self, seed):
        # Target provider sampling is configured explicitly by the host.
        self.seed = seed

    def get_init_state(self, message_history=None):
        return {"initial_history": list(message_history or [])}

    def generate_next_message(self, message, state):
        future = asyncio.run_coroutine_threadsafe(
            self.bridge.advance(self.session, message, state["initial_history"]), self.loop,
        )
        state["initial_history"] = []
        result = future.result()
        # Sage may enqueue parallel calls before the official environment has
        # replied to the first. τ sorts its trajectory by timestamp, so stamp
        # delivery (not enqueue) to preserve call/result adjacency on replay.
        from tau2.utils.utils import get_now
        result.timestamp = get_now()
        return result, state
