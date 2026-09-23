"""Remote A2A agents projected into the v2 Tool provider contracts.

Delegating to another agent is a Tool call like any other, so a configured A2A
peer is bridged into the same Tool Catalog/Executor contracts a local plugin
uses. The peer's Agent Card is the authoritative declaration of what it can do,
exactly as an MCP server's ``list_tools`` response is — one card skill becomes
one Tool.

Transport is deliberately small: one Agent Card fetch for discovery and one
blocking ``SendMessage`` per call. A host that wants streaming or push delivery
can replace ``transport`` without changing AgentLoopEngine.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from typing import Any, Protocol
from urllib.parse import urlsplit

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError
from pydantic import Field, SecretStr, model_validator

from sagents.v2.contracts.common import StrictModel, new_id
from sagents.v2.contracts.errors import (
    ErrorCategory,
    RuntimeErrorInfo,
    SageV2Error,
)
from sagents.v2.contracts.items import JsonBlock, TextBlock
from sagents.v2.contracts.principals import RequestContext
from sagents.v2.tool._idempotency import call_fingerprint
from sagents.v2.tool.contracts import (
    IdempotencyStrategy,
    ReconcileResult,
    ReconcileState,
    ResumeStrategy,
    SideEffectLevel,
    ToolCall,
    ToolDefinition,
    ToolExecutionResult,
)

# The protocol revision this client speaks, and where a peer publishes its card.
PROTOCOL_VERSION = "1.0"
JSONRPC_BINDING = "JSONRPC"
CARD_PATH = "/.well-known/agent-card.json"

# How deep a chain of agents calling agents may go. A2A gives a peer no way to
# know it is already inside a delegation, so without a hop budget two agents
# that each delegate to the other recurse until something else runs out.
#
# The budget travels as a depth count rather than a chain of Run ids: ids would
# identify the cycle precisely, but they also make every inbound call a
# different Tool catalog, which costs a card fetch per call for a diagnostic
# nobody reads. The limit is about depth, so depth is what is carried.
MAX_CALL_DEPTH = 4
CALL_DEPTH_KEY = "sage.callDepth"


class A2AAgentConfig(StrictModel):
    """Persistable A2A peer configuration without runtime objects."""

    name: str = Field(min_length=1, max_length=255)
    url: str
    api_key: SecretStr | None = None
    timeout_seconds: float = Field(default=120, gt=0)
    required: bool = False
    max_skills: int = Field(default=64, gt=0, le=1_024)
    max_result_bytes: int = Field(default=1_048_576, gt=0, le=67_108_864)

    @model_validator(mode="after")
    def validate_endpoint(self) -> A2AAgentConfig:
        parsed = urlsplit(self.url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("A2A agent URL must be an absolute http(s) URL")
        return self

    @property
    def card_url(self) -> str:
        return f"{self.url.rstrip('/')}{CARD_PATH}"


class A2ATransport(Protocol):
    """The two requests this client makes, so a host can supply its own."""

    async def card(self, config: A2AAgentConfig) -> dict[str, Any]: ...

    async def send(
        self, config: A2AAgentConfig, endpoint: str, payload: dict[str, Any]
    ) -> dict[str, Any]: ...


class A2AToolPlugin:
    """Tool plugin backed by explicitly configured remote A2A agents.

    One card skill becomes one Tool. A peer is addressed by a text message and
    answers with a Task, so the Tool's contract is narrow on purpose: the model
    writes prose for the peer and reads prose back, and the ids it needs to
    continue the conversation come back in the result rather than being held in
    this plugin. That matters because the plugin is shared by every Run of a
    tenant and may be evicted at any time — conversation state kept here would
    either leak across Runs or silently vanish between two calls.
    """

    plugin_id = "sage.tool.a2a"
    name = "A2A Agent provider"
    description = "Bridges configured A2A agents into the Sage Tool catalog."

    @property
    def capabilities(self) -> dict[str, bool]:
        return {
            "durable_operation_ledger": False,
            "supports_restart_reconciliation": False,
            "protocol_exactly_once": False,
        }

    def __init__(
        self,
        agents: tuple[A2AAgentConfig, ...],
        *,
        transport: A2ATransport | None = None,
        call_depth: int = 0,
    ) -> None:
        self.agents = tuple(sorted(agents, key=lambda value: value.name))
        self.transport = transport or HttpxA2ATransport()
        # How many agents deep this Run already is. Outbound calls announce
        # ``call_depth + 1`` so the peer inherits the budget rather than
        # restarting it.
        self.call_depth = max(0, int(call_depth))
        self._routes: dict[str, tuple[A2AAgentConfig, str]] = {}
        self._definitions: dict[str, ToolDefinition] = {}
        self._endpoints: dict[str, str] = {}
        self._results: dict[str, ToolExecutionResult] = {}
        self._failures: dict[str, RuntimeErrorInfo] = {}
        self._inflight: dict[str, asyncio.Future[ToolExecutionResult]] = {}
        self._operation_keys: dict[str, str] = {}
        self._call_fingerprints: dict[str, str] = {}
        self._call_run_ids: dict[str, str] = {}
        self._discovery_errors: dict[str, RuntimeErrorInfo] = {}
        self._lock = asyncio.Lock()
        self._discovery_fingerprint = self.servers_fingerprint(self.agents)
        self._discovery_complete = False
        self._discovery_task: asyncio.Task[tuple[ToolDefinition, ...]] | None = None
        self._discovery_generation = 0

    @staticmethod
    def servers_fingerprint(agents: tuple[A2AAgentConfig, ...]) -> str:
        payload = []
        for value in sorted(agents, key=lambda item: item.name):
            entry = value.model_dump(mode="json")
            # Persisted configuration stays redacted; cache identity must still
            # change on credential rotation. Never expose the credential itself.
            entry["api_key"] = (
                hashlib.sha256(value.api_key.get_secret_value().encode()).hexdigest()
                if value.api_key is not None
                else None
            )
            payload.append(entry)
        encoded = json.dumps(
            payload, sort_keys=True, separators=(",", ":"), default=str
        ).encode()
        return hashlib.sha256(encoded).hexdigest()

    def discovery_errors(self) -> dict[str, RuntimeErrorInfo]:
        return dict(self._discovery_errors)

    def invalidate_discovery(self) -> None:
        self._discovery_generation += 1
        self._discovery_complete = False
        self._definitions = {}
        self._routes = {}
        self._endpoints = {}
        self._discovery_errors = {}
        self._discovery_task = None
        self._discovery_fingerprint = self.servers_fingerprint(self.agents)

    async def list_tools(self, *, run_id: str) -> tuple[ToolDefinition, ...]:
        del run_id
        while True:
            fingerprint = self.servers_fingerprint(self.agents)
            async with self._lock:
                if (
                    self._discovery_complete
                    and self._discovery_fingerprint == fingerprint
                ):
                    return tuple(
                        self._definitions[name] for name in sorted(self._definitions)
                    )
                if self._discovery_fingerprint != fingerprint:
                    self.invalidate_discovery()
                generation = self._discovery_generation
                if self._discovery_task is None:
                    self._discovery_task = asyncio.create_task(
                        self._discover(self.agents, generation)
                    )
                    self._discovery_task.add_done_callback(self._discovery_finished)
                task = self._discovery_task
            # Observers do not own this shared read-only discovery task.
            result = await asyncio.shield(task)
            if (
                generation == self._discovery_generation
                and fingerprint == self.servers_fingerprint(self.agents)
            ):
                return result

    def _discovery_finished(self, task) -> None:
        if self._discovery_task is task:
            self._discovery_task = None
        if not task.cancelled():
            task.exception()  # Retrieve failures even when all observers detached.

    async def _discover(
        self, agents: tuple[A2AAgentConfig, ...], generation: int
    ) -> tuple[ToolDefinition, ...]:
        results = await asyncio.gather(*(self._discover_agent(item) for item in agents))
        discovered: dict[str, ToolDefinition] = {}
        routes: dict[str, tuple[A2AAgentConfig, str]] = {}
        endpoints: dict[str, str] = {}
        discovery_errors: dict[str, RuntimeErrorInfo] = {}
        for config, card, error in results:
            if error is not None:
                discovery_errors[config.name] = error
                continue
            try:
                definitions, agent_routes = self._project_skills(
                    config, card or {}, existing_names=frozenset(discovered)
                )
                endpoints[config.name] = self._endpoint(config, card or {})
            except SageV2Error as exc:
                if config.required:
                    raise
                discovery_errors[config.name] = exc.info
                continue
            discovered.update(definitions)
            routes.update(agent_routes)
        async with self._lock:
            if generation == self._discovery_generation and self.servers_fingerprint(
                agents
            ) == self.servers_fingerprint(self.agents):
                self._definitions = discovered
                self._routes = routes
                self._endpoints = endpoints
                self._discovery_errors = discovery_errors
                # A peer that was temporarily unreachable must be discoverable
                # on a later request without requiring a settings change.
                self._discovery_complete = not discovery_errors
        return tuple(discovered[name] for name in sorted(discovered))

    async def _discover_agent(
        self, config: A2AAgentConfig
    ) -> tuple[A2AAgentConfig, dict[str, Any] | None, RuntimeErrorInfo | None]:
        try:
            card = await asyncio.wait_for(
                self.transport.card(config), timeout=config.timeout_seconds
            )
        except SageV2Error as error:
            if config.required:
                raise
            return config, None, error.info
        except Exception as exc:
            # Reading a card is a GET that happens before any call is
            # dispatched, so its failure cannot leave a side effect behind.
            error = self._peer_error(
                "a2a.discovery_failed",
                config,
                exc,
                category=ErrorCategory.PROVIDER_TRANSIENT,
            )
            if config.required:
                raise error from exc
            return config, None, error.info
        return config, card, None

    @classmethod
    def _project_skills(
        cls,
        config: A2AAgentConfig,
        card: dict[str, Any],
        *,
        existing_names: frozenset[str],
    ) -> tuple[dict[str, ToolDefinition], dict[str, tuple[A2AAgentConfig, str]]]:
        skills = card.get("skills") or ()
        if not isinstance(skills, Sequence) or isinstance(skills, str | bytes):
            raise cls._error(
                "a2a.card_invalid",
                f"A2A agent {config.name!r} published a card without a skill list",
                ErrorCategory.PROVIDER_PERMANENT,
                metadata={"agent": config.name},
            )
        if len(skills) > config.max_skills:
            raise cls._error(
                "a2a.card_too_large",
                f"A2A agent {config.name!r} published more than the configured "
                f"{config.max_skills}-skill limit",
                ErrorCategory.PROVIDER_PERMANENT,
                metadata={"agent": config.name, "limit": config.max_skills},
            )
        definitions: dict[str, ToolDefinition] = {}
        routes: dict[str, tuple[A2AAgentConfig, str]] = {}
        for raw in skills:
            if not isinstance(raw, dict):
                continue
            skill_id = str(raw.get("id") or "").strip()
            if not skill_id:
                continue
            public_name = cls._public_name(config.name, skill_id)
            if public_name in existing_names or public_name in definitions:
                raise cls._error(
                    "a2a.skill_name_collision",
                    f"multiple A2A skills map to {public_name!r}",
                    ErrorCategory.CONFLICT,
                    metadata={"agent": config.name},
                )
            definitions[public_name] = ToolDefinition(
                name=public_name,
                description=cls._describe(config, raw)[:4096],
                input_schema=_INPUT_SCHEMA,
                # A peer agent is an autonomous system with its own tools. It
                # may write, and A2A offers no exactly-once guarantee, so a
                # lost response can hide work the peer already did.
                side_effect_level=SideEffectLevel.WRITE,
                idempotency_strategy=IdempotencyStrategy.RECONCILE_ONLY,
                resume_strategy=ResumeStrategy.MANUAL_RESOLUTION,
                requires_approval=True,
                required_scopes=("tool.external_side_effect",),
            )
            routes[public_name] = (config, skill_id)
        return definitions, routes

    @classmethod
    def _describe(cls, config: A2AAgentConfig, skill: dict[str, Any]) -> str:
        """Name the peer in every Tool description, not just the skill.

        The model chooses between Tools by reading these, and a remote skill
        called "search" says nothing about who is being asked. Sending a
        question to the wrong organisation is not recoverable by retrying.
        """

        label = str(skill.get("name") or skill.get("id") or "").strip()
        detail = str(skill.get("description") or "").strip()
        head = f"Ask the remote agent {config.name!r}"
        if label:
            head = f"{head} to do {label!r}"
        return f"{head}. {detail}".strip()

    @classmethod
    def _endpoint(cls, config: A2AAgentConfig, card: dict[str, Any]) -> str:
        """Pick the JSON-RPC endpoint the card advertises, within one host.

        A card names its own endpoint, which is how a peer moves without every
        caller being reconfigured. It is honoured only while it stays on the
        host the tenant configured: this request carries the tenant's
        credential, and a card that could redirect it to another host would be
        able to harvest that credential just by being edited.
        """

        candidates = [
            str(item.get("url") or "")
            for item in (card.get("supportedInterfaces") or ())
            if isinstance(item, dict)
            and str(item.get("protocolBinding") or "") == JSONRPC_BINDING
        ]
        candidates.append(str(card.get("url") or ""))
        configured = urlsplit(config.url)
        for candidate in candidates:
            parsed = urlsplit(candidate)
            if parsed.scheme in {"http", "https"} and parsed.netloc == configured.netloc:
                return candidate
        return config.url

    async def get_tool(self, name: str, *, run_id: str) -> ToolDefinition:
        if name not in self._definitions:
            await self.list_tools(run_id=run_id)
        try:
            return self._definitions[name]
        except KeyError as exc:
            raise self._error(
                "tool.not_found", f"A2A tool {name!r} is not registered"
            ) from exc

    async def execute(
        self, call: ToolCall, context: RequestContext
    ) -> ToolExecutionResult:
        del context
        fingerprint = call_fingerprint(call)
        async with self._lock:
            bound = self._call_fingerprints.get(call.idempotency_key)
            if bound is not None and bound != fingerprint:
                raise self._error(
                    "tool.idempotency_conflict",
                    "idempotency key was already bound to a different Tool call",
                    ErrorCategory.CONFLICT,
                    metadata={"side_effect_state": "not_applied"},
                )
            previous = self._results.get(call.idempotency_key)
            failure = self._failures.get(call.idempotency_key)
            route = self._routes.get(call.tool_name)
            definition = self._definitions.get(call.tool_name)
            endpoint = self._endpoints.get(route[0].name) if route else None
            if previous is not None:
                return previous
            if failure is not None:
                raise SageV2Error(failure)
            if route is None or definition is None or endpoint is None:
                raise self._error(
                    "tool.not_found", f"A2A tool {call.tool_name!r} is not registered"
                )
            try:
                Draft202012Validator(definition.input_schema).validate(call.arguments)
            except ValidationError as exc:
                raise self._error(
                    "tool.arguments_invalid",
                    exc.message,
                    ErrorCategory.VALIDATION,
                    metadata={"side_effect_state": "not_applied"},
                ) from exc
            future = self._inflight.get(call.idempotency_key)
            if future is None:
                future = asyncio.get_running_loop().create_future()
                self._inflight[call.idempotency_key] = future
                self._operation_keys[call.operation_id] = call.idempotency_key
                self._call_fingerprints[call.idempotency_key] = fingerprint
                self._call_run_ids[call.idempotency_key] = call.owner_run_id
                owner = True
            else:
                owner = False
        if not owner:
            return await asyncio.shield(future)
        config, skill_id = route
        payload = self._request(call, skill_id)
        try:
            response = await asyncio.wait_for(
                self.transport.send(config, endpoint, payload),
                timeout=config.timeout_seconds,
            )
        except asyncio.CancelledError as exc:
            error = self._peer_error(
                "a2a.result_cancelled",
                config,
                RuntimeError("the call was cancelled before a result arrived"),
                metadata={
                    "a2a_result_received": False,
                    "transport_failure": "cancelled",
                },
            )
            await self._remember_failure(call, future, error, exception=exc)
            raise
        except TimeoutError as exc:
            error = self._peer_error(
                "a2a.result_timeout",
                config,
                RuntimeError(
                    f"the agent did not answer within {config.timeout_seconds:g} seconds"
                ),
                metadata={"a2a_result_received": False, "transport_failure": "timeout"},
            )
            await self._remember_failure(call, future, error)
            raise error from exc
        except Exception as exc:
            # The message may have reached the peer and been acted on even
            # though its answer was lost. Never replay a delegation from here.
            error = self._peer_error(
                "a2a.result_not_received",
                config,
                exc,
                metadata={
                    "a2a_result_received": False,
                    "transport_failure": "connection",
                },
            )
            await self._remember_failure(call, future, error)
            raise error from exc
        else:
            try:
                result = self._project_result(call, config, skill_id, response)
            except Exception as exc:
                error = self._peer_error(
                    "a2a.result_invalid",
                    config,
                    exc,
                    category=ErrorCategory.PROVIDER_PERMANENT,
                    metadata={"a2a_result_received": True},
                )
                await self._remember_failure(call, future, error)
                raise error from exc
            async with self._lock:
                self._results[call.idempotency_key] = result
                if not future.done():
                    future.set_result(result)
            return result
        finally:
            async with self._lock:
                self._inflight.pop(call.idempotency_key, None)
                self._operation_keys.pop(call.operation_id, None)

    def _request(self, call: ToolCall, skill_id: str) -> dict[str, Any]:
        """Build the JSON-RPC ``SendMessage`` this Tool call sends.

        ``messageId`` is the call's own idempotency key because that is exactly
        what A2A uses it for at the other end: a peer that receives the same
        message twice must answer with the same Task rather than doing the work
        again. Minting a fresh id per attempt would give away the one
        end-to-end dedupe the protocol offers.
        """

        arguments = call.arguments
        message: dict[str, Any] = {
            "messageId": call.idempotency_key,
            "role": "ROLE_USER",
            "parts": [{"text": str(arguments.get("message") or "")}],
            "metadata": {
                CALL_DEPTH_KEY: self.call_depth + 1,
                "sage.skill": skill_id,
            },
        }
        context = str(arguments.get("context_id") or "").strip()
        if context:
            message["contextId"] = context
        return {
            "jsonrpc": "2.0",
            "id": new_id("a2a-rpc"),
            "method": "SendMessage",
            "params": {"message": message},
        }

    def _project_result(
        self,
        call: ToolCall,
        config: A2AAgentConfig,
        skill_id: str,
        response: dict[str, Any],
    ) -> ToolExecutionResult:
        if not isinstance(response, dict):
            raise TypeError("A2A response must be a JSON object")
        metadata: dict[str, Any] = {
            "a2a_agent": config.name,
            "a2a_skill": skill_id,
            "a2a_result_received": True,
            "tool_result_received": True,
        }
        error = response.get("error")
        if isinstance(error, dict):
            # A JSON-RPC error is an answer, not a lost response: the peer
            # decided. It is reported as a Tool error the model can read and
            # react to rather than as an exception that fails the Run.
            return ToolExecutionResult(
                tool_call_id=call.tool_call_id,
                operation_id=call.operation_id,
                content=(
                    TextBlock(
                        text=f"{config.name} refused the request: "
                        f"{str(error.get('message') or 'unknown error')[:2048]}"
                    ),
                ),
                error=RuntimeErrorInfo(
                    code="a2a.peer_error",
                    category=ErrorCategory.PROVIDER_PERMANENT,
                    message=str(error.get("message") or "A2A call failed")[:4096],
                    safe_to_resume=True,
                    metadata={**metadata, "a2a_code": error.get("code")},
                ),
                metadata=metadata,
            )
        result = response.get("result")
        if not isinstance(result, dict):
            raise TypeError("A2A response carried neither a result nor an error")
        task = result.get("task") if isinstance(result.get("task"), dict) else None
        reply = result.get("message") if isinstance(result.get("message"), dict) else None
        if task is None and reply is None:
            raise TypeError("A2A result carried neither a task nor a message")
        state = (
            str((task.get("status") or {}).get("state") or "") if task is not None else ""
        )
        text = self._reply_text(task, reply)
        identity = {
            "contextId": str((task or reply or {}).get("contextId") or ""),
            "taskId": str(task.get("id") or "") if task is not None else "",
            "state": state,
        }
        size = len(text.encode("utf-8"))
        if size > config.max_result_bytes:
            text = (
                f"The answer from {config.name} was omitted because it exceeded the "
                f"configured {config.max_result_bytes}-byte limit."
            )
        if state == "TASK_STATE_INPUT_REQUIRED":
            # The peer stopped to ask something. Saying so in the content is
            # what lets the model send the follow-up instead of reporting the
            # half-finished answer as the result.
            text = (
                f"{config.name} needs more information before it can finish. "
                f"Reply by calling this tool again with the same context_id.\n\n{text}"
            )
        return ToolExecutionResult(
            tool_call_id=call.tool_call_id,
            operation_id=call.operation_id,
            content=(TextBlock(text=text), JsonBlock(value=identity)),
            error=(
                RuntimeErrorInfo(
                    code="a2a.task_failed",
                    category=ErrorCategory.PROVIDER_PERMANENT,
                    message=text[:4096] or f"{config.name} could not complete the task",
                    safe_to_resume=True,
                    metadata=metadata,
                )
                if state in {"TASK_STATE_FAILED", "TASK_STATE_REJECTED"}
                else None
            ),
            metadata={
                **metadata,
                "a2a_task_id": identity["taskId"],
                "a2a_context_id": identity["contextId"],
                "a2a_task_state": state,
                "a2a_result_size_bytes": size,
                "a2a_result_truncated": size > config.max_result_bytes,
            },
        )

    @staticmethod
    def _reply_text(task: dict[str, Any] | None, reply: dict[str, Any] | None) -> str:
        """Read what the peer actually said, newest answer first.

        A Task carries the whole conversation, including the message this call
        just sent. Only the peer's own turns are its answer, and the last one
        is the conclusion — earlier agent turns are working notes that would
        bury it.
        """

        def parts_text(message: dict[str, Any]) -> str:
            return "".join(
                str(part.get("text") or "")
                for part in (message.get("parts") or ())
                if isinstance(part, dict)
            ).strip()

        if task is not None:
            agent_turns = [
                parts_text(item)
                for item in (task.get("history") or ())
                if isinstance(item, dict) and str(item.get("role") or "") == "ROLE_AGENT"
            ]
            answers = [value for value in agent_turns if value]
            if answers:
                return answers[-1]
            status_message = (task.get("status") or {}).get("update")
            if isinstance(status_message, dict):
                text = parts_text(status_message)
                if text:
                    return text
        if reply is not None:
            text = parts_text(reply)
            if text:
                return text
        return "The agent returned no content."

    async def _remember_failure(
        self,
        call: ToolCall,
        future: asyncio.Future,
        error: SageV2Error,
        *,
        exception: BaseException | None = None,
    ) -> None:
        """Pin a failed call to its idempotency key, so a retry cannot repeat it."""

        async with self._lock:
            self._failures[call.idempotency_key] = error.info
            if not future.done():
                future.set_exception(exception or error)
                future.exception()

    async def reconcile(
        self, operation_id: str, context: RequestContext
    ) -> ReconcileResult:
        del context
        async with self._lock:
            result = next(
                (
                    value
                    for value in self._results.values()
                    if value.operation_id == operation_id
                ),
                None,
            )
            key = self._operation_keys.get(operation_id)
            pending = key in self._inflight if key is not None else False
        return ReconcileResult(
            operation_id=operation_id,
            state=(
                ReconcileState.FAILED
                if result is not None and result.error is not None
                else ReconcileState.SUCCEEDED
                if result is not None
                else ReconcileState.PENDING
                if pending
                else ReconcileState.UNKNOWN
            ),
            result=result,
        )

    async def release_run(self, run_id: str) -> None:
        """Release terminal Run state without disturbing in-flight calls."""

        async with self._lock:
            keys = {
                key
                for key, owner_run_id in self._call_run_ids.items()
                if owner_run_id == run_id and key not in self._inflight
            }
            for key in keys:
                self._results.pop(key, None)
                self._failures.pop(key, None)
                self._call_fingerprints.pop(key, None)
                self._call_run_ids.pop(key, None)

    @classmethod
    def _public_name(cls, agent: str, skill: str) -> str:
        # ToolName deliberately forbids dots. Prefixing the configured peer
        # keeps routes deterministic while remaining provider-compatible.
        return f"a2a_{cls._identifier(agent)}_{cls._identifier(skill)}"[:192]

    @staticmethod
    def _identifier(value: str) -> str:
        normalized = re.sub(r"[^A-Za-z0-9_]+", "_", value).strip("_")
        return normalized or "unnamed"

    @staticmethod
    def _peer_error(
        code: str,
        config: A2AAgentConfig,
        exc: Exception,
        *,
        category: ErrorCategory = ErrorCategory.UNCERTAIN_SIDE_EFFECT,
        metadata: dict[str, Any] | None = None,
    ) -> SageV2Error:
        return A2AToolPlugin._error(
            code,
            f"A2A agent {config.name!r} failed: {exc}",
            category,
            metadata={"agent": config.name, **dict(metadata or {})},
        )

    @staticmethod
    def _error(
        code: str,
        message: str,
        category: ErrorCategory = ErrorCategory.VALIDATION,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> SageV2Error:
        return SageV2Error(
            RuntimeErrorInfo(
                code=code,
                category=category,
                message=message,
                retryable=category == ErrorCategory.PROVIDER_TRANSIENT,
                safe_to_resume=category != ErrorCategory.UNCERTAIN_SIDE_EFFECT,
                metadata=dict(metadata or {}),
            )
        )


_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "message": {
            "type": "string",
            "minLength": 1,
            "description": (
                "What to ask the remote agent, written for someone with no "
                "access to this conversation: state the task and include every "
                "fact it needs."
            ),
        },
        "context_id": {
            "type": "string",
            "description": (
                "The contextId returned by an earlier call to this agent. Pass "
                "it to continue that conversation; omit it to start a new one."
            ),
        },
    },
    "required": ["message"],
    "additionalProperties": False,
}


class HttpxA2ATransport:
    """The default transport: one GET for the card, one POST per call.

    A client is opened per request rather than pooled. It is the same trade the
    MCP bridge makes — slower than a pool, but lifecycle and cancellation stay
    owned by the calling task, and a host that cares can supply its own
    transport.
    """

    async def card(self, config: A2AAgentConfig) -> dict[str, Any]:
        async with self._client(config) as client:
            response = await client.get(config.card_url)
            response.raise_for_status()
            return response.json()

    async def send(
        self, config: A2AAgentConfig, endpoint: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        async with self._client(config) as client:
            response = await client.post(endpoint, json=payload)
            response.raise_for_status()
            return response.json()

    @asynccontextmanager
    async def _client(self, config: A2AAgentConfig) -> AsyncIterator[Any]:
        try:
            import httpx
        except ImportError as exc:  # pragma: no cover - depends on host packaging
            raise RuntimeError("the optional 'httpx' package is not installed") from exc

        headers = {"A2A-Version": PROTOCOL_VERSION}
        if config.api_key is not None:
            headers["Authorization"] = f"Bearer {config.api_key.get_secret_value()}"
        async with httpx.AsyncClient(
            timeout=config.timeout_seconds,
            headers=headers,
            # A peer that redirects is a peer that moved; following it would
            # forward the tenant's credential to a host they never named.
            follow_redirects=False,
        ) as client:
            yield client
