"""Provider-request construction for one Agent loop step.

The loop controls durable ordering and side-effect barriers. This module owns
the replaceable projection from canonical loop state to one model request.
"""

from __future__ import annotations

from sagents.v2.context.token_estimator import estimate_tokens_async

import json
from collections import OrderedDict
from sagents.v2.context.calibration import (
    InputUsageBaseline,
    fingerprint,
    input_usage_scope,
    message_fingerprints,
)
from dataclasses import dataclass
from typing import Protocol

from sagents.v2.context import ContextAssembler
from sagents.v2.context.contracts import ContextBudget, ContextRequestReservation
from sagents.v2.context.plugins.estimator_json import JsonHeuristicTokenEstimator
from sagents.v2.context.token_estimator import TokenEstimator
from sagents.v2.contracts.commands import StartRun
from sagents.v2.contracts.errors import (
    ErrorCategory,
    RuntimeErrorInfo,
    SageV2Error,
)
from sagents.v2.contracts.items import TextBlock
from sagents.v2.i18n import tr
from sagents.v2.model.contracts import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ModelToolDefinition,
)
from sagents.v2.tool.contracts import ToolDefinition
from sagents.v2.tool.localization import localize_tool_definition
from sagents.v2.tool.provider import ToolCatalog
from sagents.v2.tool.selection import ToolSelectionPolicy, ToolSelectionRequest
from sagents.v2.contracts.common import new_id


@dataclass(frozen=True)
class PreparedAgentStep:
    """Model request and the exact Tool definitions visible to its policy."""

    request: ModelRequest
    tools: tuple[ToolDefinition, ...]


class AgentStepRequestBuilder(Protocol):
    """Port for constructing one provider-facing Agent step request."""

    async def prepare(
        self,
        *,
        command: StartRun,
        run_id: str,
        turn_id: str,
        step_id: str,
        messages: tuple[ModelMessage, ...],
        pending_continuation_reason: str | None,
        language: str | None,
        additional_input_reserve_tokens: int = 0,
    ) -> PreparedAgentStep: ...


class DefaultAgentStepRequestBuilder:
    """Default context assembly, Tool projection, and request construction."""

    _PROVIDER_REQUEST_OVERHEAD_TOKENS = 32

    def __init__(
        self,
        *,
        context_assembler: ContextAssembler,
        tool_catalog: ToolCatalog,
        tool_selection_policy: ToolSelectionPolicy,
        token_estimator: TokenEstimator | None = None,
        context_budget: ContextBudget | None = None,
    ) -> None:
        self.context_assembler = context_assembler
        self.tool_catalog = tool_catalog
        self.tool_selection_policy = tool_selection_policy
        self.token_estimator = token_estimator or JsonHeuristicTokenEstimator()
        self.context_budget = context_budget
        self._input_baselines: OrderedDict[str, InputUsageBaseline] = OrderedDict()

    async def prepare(
        self,
        *,
        command: StartRun,
        run_id: str,
        turn_id: str,
        step_id: str,
        messages: tuple[ModelMessage, ...],
        pending_continuation_reason: str | None,
        language: str | None,
        additional_input_reserve_tokens: int = 0,
    ) -> PreparedAgentStep:
        if additional_input_reserve_tokens < 0:
            raise ValueError("additional_input_reserve_tokens cannot be negative")
        catalog_tools = await self.tool_catalog.list_tools(run_id=run_id)
        catalog_tools = tools_for_invocation_mode(
            catalog_tools, command.invocation_mode
        )
        selection = self.tool_selection_policy.select(
            ToolSelectionRequest(
                run_id=run_id,
                tools=catalog_tools,
                messages=messages,
            )
        )
        response_language = str(
            command.config.metadata.get("response_language") or language or "en"
        )
        request_tools = tuple(
            ModelToolDefinition(
                name=localized.name,
                description=localized.description,
                input_schema=localized.input_schema,
                strict=localized.strict,
                output_schema=localized.output_schema,
            )
            for tool in selection.tools
            for localized in (localize_tool_definition(tool, response_language),)
        )
        hidden_index_messages = (
            (self._tool_index_message(selection.hidden_tool_index, language),)
            if selection.hidden_tool_index
            else ()
        )
        continuation_messages = (
            (self._continuation_message(pending_continuation_reason),)
            if pending_continuation_reason
            else ()
        )
        suffix_messages = (*hidden_index_messages, *continuation_messages)
        tool_tokens = await self._estimate_tool_tokens(request_tools)
        reservation = ContextRequestReservation(
            tool_schema_tokens=tool_tokens,
            hidden_tool_index_tokens=await estimate_tokens_async(
                self.token_estimator, hidden_index_messages
            ),
            continuation_guidance_tokens=await estimate_tokens_async(
                self.token_estimator, continuation_messages
            ),
            protocol_overhead_tokens=(
                self._PROVIDER_REQUEST_OVERHEAD_TOKENS + additional_input_reserve_tokens
            ),
            message_count=len(suffix_messages),
        )
        calibration_scope = fingerprint(
            {
                "spec": command.resolved_spec_hash,
                "config": command.config.model_dump(mode="json"),
                "tools": [
                    t.model_dump(mode="json")
                    for t in sorted(request_tools, key=lambda t: t.name)
                ],
                "invocation_mode": command.invocation_mode,
                "language": language,
            }
        )
        baseline = self._input_baselines.get(run_id)
        if baseline is not None and (
            baseline.scope != calibration_scope
            or additional_input_reserve_tokens
            or not getattr(self.token_estimator, "additive", False)
        ):
            baseline = None
        with input_usage_scope(baseline):
            prepared_messages = await self.context_assembler.prepare_messages(
                command,
                messages,
                run_id=run_id,
                reservation=reservation,
            )
            prepared_messages = (*prepared_messages, *suffix_messages)
            estimated_input_tokens = (
                await estimate_tokens_async(self.token_estimator, prepared_messages)
                + tool_tokens
                + self._PROVIDER_REQUEST_OVERHEAD_TOKENS
            )
        calibrated = baseline is not None and baseline.matches(prepared_messages)
        self._validate_final_budget(
            estimated_input_tokens=estimated_input_tokens,
            message_count=len(prepared_messages),
        )
        request = ModelRequest(
            request_id=new_id("model_request"),
            run_id=run_id,
            model_binding=command.config.model_bindings.get("primary", "primary"),
            messages=prepared_messages,
            tools=request_tools,
            max_output_tokens=(
                command.config.max_output_tokens
                or command.config.metadata.get("max_output_tokens")
            ),
            tool_choice="auto" if selection.tools else None,
            metadata={
                "input_calibration_scope": calibration_scope,
                "turn_id": turn_id,
                "step_id": step_id,
                "request_budget": {
                    "estimated_input_tokens": estimated_input_tokens,
                    "accounting_method": "reported_prefix_plus_estimated_delta"
                    if calibrated
                    else "estimated",
                    "baseline_request_id": baseline.request_id if calibrated else None,
                    "baseline_input_tokens": baseline.input_tokens
                    if calibrated
                    else None,
                    "estimated_new_message_count": len(prepared_messages)
                    - len(baseline.messages)
                    if calibrated
                    else len(prepared_messages),
                    "estimated_delta_tokens": estimated_input_tokens
                    - baseline.input_tokens
                    - baseline.margin
                    if calibrated
                    else None,
                    "calibration_margin_tokens": baseline.margin if calibrated else 0,
                    "reserved_non_history_tokens": reservation.input_tokens,
                    "tool_schema_tokens": reservation.tool_schema_tokens,
                    "hidden_tool_index_tokens": (reservation.hidden_tool_index_tokens),
                    "continuation_guidance_tokens": (
                        reservation.continuation_guidance_tokens
                    ),
                    "protocol_overhead_tokens": (reservation.protocol_overhead_tokens),
                },
                "tool_selection": {
                    "plugin": self.tool_selection_policy.plugin_id,
                    "strategy": selection.strategy,
                    "catalog_count": selection.catalog_count,
                    "selected_count": selection.selected_count,
                    "estimated_schema_tokens": selection.estimated_schema_tokens,
                    "hidden_index_count": len(selection.hidden_tool_index),
                    "estimated_index_tokens": selection.estimated_index_tokens,
                    "expanded_tools": selection.expanded_tools,
                },
            },
        )
        return PreparedAgentStep(request=request, tools=selection.tools)

    def observe_response(self, request: ModelRequest, response: ModelResponse) -> None:
        """Accept only complete, reported usage from this builder's requests."""
        usage = response.usage
        scope = request.metadata.get("input_calibration_scope")
        budget = request.metadata.get("request_budget", {})
        overhead = (
            budget.get("tool_schema_tokens", 0) + self._PROVIDER_REQUEST_OVERHEAD_TOKENS
        )
        if (
            not usage.reported
            or usage.input_tokens <= overhead
            or not scope
            or usage.cached_input_tokens > usage.input_tokens
            or response.provider_metadata.get("compatibility_fallback")
            or request.tool_choice not in (None, "auto")
        ):
            self._input_baselines.pop(request.run_id, None)
            return
        self._input_baselines[request.run_id] = InputUsageBaseline(
            scope=scope,
            request_id=request.request_id,
            messages=message_fingerprints(request.messages),
            input_tokens=usage.input_tokens,
            non_message_tokens=overhead,
        )
        self._input_baselines.move_to_end(request.run_id)
        while len(self._input_baselines) > 128:
            self._input_baselines.popitem(last=False)

    async def _estimate_tool_tokens(
        self, tools: tuple[ModelToolDefinition, ...]
    ) -> int:
        if not tools:
            return 0
        # Reuse the selected Context estimator while representing non-message
        # Tool schemas as one deterministic budget-only message. The wrapper
        # overhead is intentionally conservative across provider protocols.
        payload = json.dumps(
            [tool.model_dump(mode="json", exclude_none=True) for tool in tools],
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return await estimate_tokens_async(
            self.token_estimator,
            (
                ModelMessage(
                    role="developer",
                    content=(TextBlock(text=payload),),
                    metadata={"request_budget_tools": True},
                ),
            ),
        )

    def _validate_final_budget(
        self, *, estimated_input_tokens: int, message_count: int
    ) -> None:
        budget = self.context_budget
        if budget is None:
            return
        maximum = (
            budget.max_input_tokens
            - budget.reserve_output_tokens
            - budget.reserve_input_tokens
        )
        if maximum <= 0:
            raise self._budget_error(
                "context.invalid_budget",
                "output and configured input reserves consume the model budget",
            )
        if estimated_input_tokens > maximum:
            raise self._budget_error(
                "context.budget_exhausted",
                "final messages, Tool schemas, and provider overhead exceed the model budget",
            )
        if budget.max_messages is not None and message_count > budget.max_messages:
            raise self._budget_error(
                "context.budget_exhausted",
                "final runtime suffix exceeds the model message budget",
            )

    @staticmethod
    def _budget_error(code: str, message: str) -> SageV2Error:
        return SageV2Error(
            RuntimeErrorInfo(
                code=code,
                category=ErrorCategory.VALIDATION,
                message=message,
                safe_to_resume=True,
            )
        )

    @staticmethod
    def _tool_index_message(
        hidden_tool_index: tuple[tuple[str, str], ...], language: str | None
    ) -> ModelMessage:
        tool_index = json.dumps(
            [
                {"name": name, "description": description}
                for name, description in hidden_tool_index
            ],
            ensure_ascii=False,
            separators=(",", ":"),
        )
        return ModelMessage(
            role="developer",
            content=(
                TextBlock(
                    text=(
                        "<available_tool_index>\n"
                        f"{tr('tool_selection.index_instruction', language)}\n"
                        f"{tool_index}\n"
                        "</available_tool_index>"
                    )
                ),
            ),
            metadata={
                "inference_view_only": True,
                "runtime_tool_index": True,
                "context_protected": True,
            },
        )

    @staticmethod
    def _continuation_message(reason: str) -> ModelMessage:
        return ModelMessage(
            role="user",
            content=(
                TextBlock(
                    text=(
                        "<runtime_continuation_guidance>\n"
                        "Internal runtime note, not a user request. Do not mention it.\n"
                        f"Continue because: {reason}\n"
                        "Perform the next unfinished action. Do not repeat the last "
                        "visible update or already reported artifacts.\n"
                        "</runtime_continuation_guidance>"
                    )
                ),
            ),
            metadata={
                "inference_view_only": True,
                "runtime_continuation_guidance": True,
                "context_protected": True,
            },
        )


def tools_for_invocation_mode(
    tools: tuple[ToolDefinition, ...], invocation_mode: str
) -> tuple[ToolDefinition, ...]:
    """Apply the same mode gate during Run preparation and every model step."""

    visible_mode_tools = {
        "plan": {"goal_submit"},
        "goal": {"goal_submit", "goal_complete"},
    }.get(invocation_mode, set())
    mode_tools = {"goal_submit", "goal_complete"}
    return tuple(
        tool
        for tool in tools
        if tool.name not in mode_tools or tool.name in visible_mode_tools
    )


__all__ = [
    "AgentStepRequestBuilder",
    "DefaultAgentStepRequestBuilder",
    "PreparedAgentStep",
    "tools_for_invocation_mode",
]
