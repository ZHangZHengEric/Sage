"""Official Tool-selection plugin: one fast-model pass per Run."""

from __future__ import annotations

import json

from sagents.v2.contracts.common import new_id
from sagents.v2.contracts.items import TextBlock
from sagents.v2.i18n import tr
from sagents.v2.model.contracts import ModelMessage, ModelRequest
from sagents.v2.tool.selection import (
    BaseToolSelectionPolicy,
    ToolSelectionConfig,
    ToolSelectionPrepareContext,
    ToolSelectionRequest,
    ToolSelectionResult,
    _bm25_ranked_names,
    _compact_history,
    _parse_llm_tool_names,
    _recent_text,
    _recent_tool_names,
)


class LLMToolSelectionPolicy(BaseToolSelectionPolicy):
    """Use the host-provided fast model once per Run with bounded fallback."""

    plugin_id = "sage.tool-selection.llm"
    name = "LLM Tool selection"
    description = (
        "Uses a fast model and recent context to select relevant Tools; "
        "falls back locally on failure."
    )

    def __init__(self, config: ToolSelectionConfig | dict | None = None) -> None:
        super().__init__(config)
        self._selected_by_run: dict[str, tuple[str, ...]] = {}
        self._prepared_strategy_by_run: dict[str, str] = {}

    async def prepare(self, context: ToolSelectionPrepareContext) -> None:
        self._remember_catalog(context.run_id, context.tools)
        fallback = _bm25_ranked_names(
            context.tools, _recent_text(context.messages)
        )
        if context.model is None or not context.tools:
            self._selected_by_run[context.run_id] = fallback
            self._prepared_strategy_by_run[context.run_id] = "llm.fallback.bm25"
            return
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
        try:
            response = None
            stream = context.model.stream(request)
            try:
                async for event in stream:
                    if event.response is not None:
                        response = event.response
            finally:
                closer = getattr(stream, "aclose", None)
                if closer is not None:
                    await closer()
            names = _parse_llm_tool_names(
                response.text if response else "", context.tools
            )
            if not names:
                raise ValueError("model returned no valid Tool names")
            self._selected_by_run[context.run_id] = names
            self._prepared_strategy_by_run[context.run_id] = "llm"
        except Exception:
            self._selected_by_run[context.run_id] = fallback
            self._prepared_strategy_by_run[context.run_id] = "llm.fallback.bm25"

    def select(self, request: ToolSelectionRequest) -> ToolSelectionResult:
        self._remember_catalog(request.run_id, request.tools)
        prepared = self._selected_by_run.get(request.run_id)
        strategy = self._prepared_strategy_by_run.get(request.run_id)
        if prepared is None:
            prepared = _bm25_ranked_names(
                request.tools, _recent_text(request.messages)
            )
            strategy = "llm.fallback.bm25"
        preferred = tuple(
            dict.fromkeys((*_recent_tool_names(request.messages), *prepared))
        )
        selected = self._bounded(request, preferred)
        return self._result(request, selected, strategy or "llm")

    def release_run(self, run_id: str) -> None:
        super().release_run(run_id)
        self._selected_by_run.pop(run_id, None)
        self._prepared_strategy_by_run.pop(run_id, None)
