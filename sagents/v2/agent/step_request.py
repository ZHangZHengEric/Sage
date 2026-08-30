"""Provider-request construction for one Agent loop step.

The loop controls durable ordering and side-effect barriers. This module owns
the replaceable projection from canonical loop state to one model request.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Protocol

from sagents.v2.context import ContextAssembler
from sagents.v2.contracts.commands import StartRun
from sagents.v2.contracts.items import TextBlock
from sagents.v2.i18n import tr
from sagents.v2.model.contracts import (
    ModelMessage,
    ModelRequest,
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
    ) -> PreparedAgentStep: ...


class DefaultAgentStepRequestBuilder:
    """Default context assembly, Tool projection, and request construction."""

    def __init__(
        self,
        *,
        context_assembler: ContextAssembler,
        tool_catalog: ToolCatalog,
        tool_selection_policy: ToolSelectionPolicy,
    ) -> None:
        self.context_assembler = context_assembler
        self.tool_catalog = tool_catalog
        self.tool_selection_policy = tool_selection_policy

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
    ) -> PreparedAgentStep:
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
        prepared_messages = await self.context_assembler.prepare_messages(
            command,
            messages,
            run_id=run_id,
        )
        if selection.hidden_tool_index:
            prepared_messages = (
                *prepared_messages,
                self._tool_index_message(selection.hidden_tool_index, language),
            )
        if pending_continuation_reason:
            prepared_messages = (
                *prepared_messages,
                self._continuation_message(pending_continuation_reason),
            )

        response_language = str(
            command.config.metadata.get("response_language") or language or "en"
        )
        request = ModelRequest(
            request_id=new_id("model_request"),
            run_id=run_id,
            model_binding=command.config.model_bindings.get("primary", "primary"),
            messages=prepared_messages,
            tools=tuple(
                ModelToolDefinition(
                    name=localized.name,
                    description=localized.description,
                    input_schema=localized.input_schema,
                    strict=localized.strict,
                    output_schema=localized.output_schema,
                )
                for tool in selection.tools
                for localized in (
                    localize_tool_definition(tool, response_language),
                )
            ),
            max_output_tokens=(
                command.config.max_output_tokens
                or command.config.metadata.get("max_output_tokens")
            ),
            tool_choice="auto" if selection.tools else None,
            metadata={
                "turn_id": turn_id,
                "step_id": step_id,
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
