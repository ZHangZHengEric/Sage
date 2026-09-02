"""Official Tool-selection plugin: one fast-model pass per Run."""

from __future__ import annotations

import asyncio
import json

from sagents.v2.contracts.common import new_id
from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo, SageV2Error
from sagents.v2.contracts.items import TextBlock
from sagents.v2.i18n import tr
from sagents.v2.model.contracts import ModelMessage, ModelRequest
from sagents.v2.model.provider import auxiliary_model_timeout_error
from sagents.v2.tool.selection import (
    BaseToolSelectionPolicy,
    ToolSelectionConfig,
    ToolSelectionPrepareContext,
    ToolSelectionRequest,
    ToolSelectionResult,
    _compact_history,
    _parse_llm_tool_names,
    _recent_tool_names,
)


class LLMToolSelectionPolicy(BaseToolSelectionPolicy):
    """Use the host-provided fast model once per Run."""

    plugin_id = "sage.tool-selection.llm"
    name = "LLM Tool selection"
    description = (
        "Uses a fast model and recent context to select relevant Tools."
    )

    def __init__(self, config: ToolSelectionConfig | dict | None = None) -> None:
        super().__init__(config)
        self._selected_by_run: dict[str, tuple[str, ...]] = {}
        self._prepared_strategy_by_run: dict[str, str] = {}

    async def prepare(self, context: ToolSelectionPrepareContext) -> None:
        self._remember_catalog(context.run_id, context.tools)
        if not context.tools:
            self._selected_by_run[context.run_id] = ()
            self._prepared_strategy_by_run[context.run_id] = "llm"
            return
        if context.model is None:
            raise SageV2Error(
                RuntimeErrorInfo(
                    code="tool_selection.model_missing",
                    category=ErrorCategory.VALIDATION,
                    message="LLM Tool selection requires a configured model",
                    safe_to_resume=True,
                    metadata={"plugin_id": self.plugin_id},
                )
            )
        request = ModelRequest(
            request_id=new_id("tool_selection"),
            run_id=context.run_id,
            model_binding="fast",
            messages=(
                ModelMessage(
                    role="system",
                    content=(
                        TextBlock(
                            text=tr("tool_selection.llm_system", context.language)
                        ),
                    ),
                ),
                ModelMessage(
                    role="user",
                    content=(
                        TextBlock(
                            text=tr(
                                "tool_selection.llm_request",
                                context.language,
                                max_tools=self.config.max_visible_tools,
                                history=_compact_history(context.messages),
                                tools=json.dumps(
                                    [
                                        {
                                            "name": tool.name,
                                            "description": tool.description[:240],
                                            "parameters": sorted(
                                                (
                                                    tool.input_schema.get(
                                                        "properties", {}
                                                    )
                                                    or {}
                                                ).keys()
                                            ),
                                        }
                                        for tool in context.tools
                                    ],
                                    ensure_ascii=False,
                                    separators=(",", ":"),
                                ),
                            )
                        ),
                    ),
                ),
            ),
            max_output_tokens=None,
            response_format="json_object",
            tool_choice="none",
            metadata={"purpose": "tool_selection"},
        )
        response = None
        try:
            async with asyncio.timeout(self.config.model_timeout_seconds):
                stream = context.model.stream(request)
                try:
                    async for event in stream:
                        if event.response is not None:
                            response = event.response
                finally:
                    closer = getattr(stream, "aclose", None)
                    if closer is not None:
                        await closer()
        except TimeoutError as exc:
            raise auxiliary_model_timeout_error(
                code="tool_selection.model_timeout",
                operation="LLM Tool selection",
                timeout_seconds=self.config.model_timeout_seconds,
                plugin_id=self.plugin_id,
            ) from exc
        try:
            names = _parse_llm_tool_names(
                response.text if response else "", context.tools
            )
        except (TypeError, ValueError):
            names = ()
        if not names:
            raise SageV2Error(
                RuntimeErrorInfo(
                    code="tool_selection.model_output_invalid",
                    category=ErrorCategory.PROVIDER_PERMANENT,
                    message="LLM Tool selection returned no valid Tool names",
                    safe_to_resume=True,
                    metadata={"plugin_id": self.plugin_id},
                )
            )
        self._selected_by_run[context.run_id] = names
        self._prepared_strategy_by_run[context.run_id] = "llm"

    def select(self, request: ToolSelectionRequest) -> ToolSelectionResult:
        self._remember_catalog(request.run_id, request.tools)
        prepared = self._selected_by_run.get(request.run_id)
        strategy = self._prepared_strategy_by_run.get(request.run_id)
        if prepared is None:
            raise SageV2Error(
                RuntimeErrorInfo(
                    code="tool_selection.not_prepared",
                    category=ErrorCategory.INTERNAL,
                    message="LLM Tool selection was used before prepare completed",
                    safe_to_resume=True,
                    metadata={"plugin_id": self.plugin_id},
                )
            )
        preferred = tuple(
            dict.fromkeys((*_recent_tool_names(request.messages), *prepared))
        )
        selected = self._bounded(request, preferred)
        return self._result(request, selected, strategy or "llm")

    def release_run(self, run_id: str) -> None:
        super().release_run(run_id)
        self._selected_by_run.pop(run_id, None)
        self._prepared_strategy_by_run.pop(run_id, None)
