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
from sagents.v2.tool.contracts import ToolDefinition
from sagents.v2.tool.selection import (
    DEFAULT_ALWAYS_VISIBLE_TOOLS,
    ToolSelectionConfig,
    ToolSelectionPrepareContext,
    ToolSelectionRequest,
    ToolSelectionResult,
    _compact_history,
    _parse_llm_tool_names,
    _recent_tool_names,
    _EXPANSION_BATCH_LIMIT,
    _INDEX_DESCRIPTION_CHARS,
    _INDEX_ENTRY_LIMIT,
    _INDEX_TOKEN_LIMIT,
    _schema_tokens,
)


class _LLMSelectionState:
    def __init__(self, config: ToolSelectionConfig | dict | None = None) -> None:
        self.config = (
            config
            if isinstance(config, ToolSelectionConfig)
            else ToolSelectionConfig.model_validate(config or {})
        )
        self._expanded_by_run: dict[str, set[str]] = {}
        self._available_by_run: dict[str, frozenset[str]] = {}

    async def prepare(self, context: ToolSelectionPrepareContext) -> None:
        self._remember_catalog(context.run_id, context.tools)

    def expand_tools(
        self,
        *,
        run_id: str,
        names: tuple[str, ...],
        available_names: tuple[str, ...] | None = None,
    ) -> dict[str, object]:
        requested = tuple(dict.fromkeys(str(name).strip() for name in names if name))
        batch_limit = min(_EXPANSION_BATCH_LIMIT, self.config.max_visible_tools)
        if len(requested) > batch_limit:
            return {
                "status": "error",
                "code": "tool_selection.expansion_batch_limit",
                "limit": batch_limit,
            }
        available = (
            frozenset(available_names)
            if available_names is not None
            else self._available_by_run.get(run_id, frozenset())
        )
        unknown = sorted(set(requested) - available)
        if unknown:
            return {
                "status": "error",
                "code": "tool_selection.unknown_tools",
                "unknown_tools": unknown,
            }
        active = self._expanded_by_run.setdefault(run_id, set())
        if len(active | set(requested)) > self.config.max_visible_tools:
            return {
                "status": "error",
                "code": "tool_selection.expanded_tools_limit",
                "limit": self.config.max_visible_tools,
            }
        active.update(requested)
        return {"status": "success", "expanded_tools": sorted(active)}

    def expanded_tools(self, run_id: str) -> tuple[str, ...]:
        return tuple(sorted(self._expanded_by_run.get(run_id, ())))

    def restore_expanded_tools(self, run_id: str, names: tuple[str, ...]) -> None:
        if names:
            self._expanded_by_run[run_id] = set(names[: self.config.max_visible_tools])

    def release_run(self, run_id: str) -> None:
        self._expanded_by_run.pop(run_id, None)
        self._available_by_run.pop(run_id, None)

    def _remember_catalog(self, run_id: str, tools: tuple[ToolDefinition, ...]) -> None:
        self._available_by_run[run_id] = frozenset(tool.name for tool in tools)

    def _required_names(self, run_id: str) -> tuple[str, ...]:
        return tuple(
            dict.fromkeys(
                (
                    *DEFAULT_ALWAYS_VISIBLE_TOOLS,
                    *sorted(self._expanded_by_run.get(run_id, ())),
                )
            )
        )

    def _bounded(
        self,
        request: ToolSelectionRequest,
        preferred_names: tuple[str, ...],
        *,
        preferred_first: bool = False,
    ) -> tuple[ToolDefinition, ...]:
        by_name = {tool.name: tool for tool in request.tools}
        required = tuple(
            name for name in self._required_names(request.run_id) if name in by_name
        )
        preferred = tuple(
            name
            for name in dict.fromkeys(preferred_names)
            if name in by_name and name not in required
        )
        fallback = tuple(
            tool.name
            for tool in request.tools
            if tool.name not in required and tool.name not in preferred
        )
        ordered = (
            (*preferred, *required, *fallback)
            if preferred_first
            else (*required, *preferred, *fallback)
        )
        return tuple(by_name[name] for name in ordered[: self.config.max_visible_tools])

    def _result(
        self,
        request: ToolSelectionRequest,
        selected: tuple[ToolDefinition, ...],
        strategy: str,
    ) -> ToolSelectionResult:
        selected_names = {tool.name for tool in selected}
        hidden_index: list[tuple[str, str]] = []
        index_tokens = 0
        for tool in request.tools:
            if tool.name in selected_names:
                continue
            description = " ".join(tool.description.split())[:_INDEX_DESCRIPTION_CHARS]
            cost = max(1, (len(tool.name) + len(description) + 5) // 3)
            if len(hidden_index) >= _INDEX_ENTRY_LIMIT:
                break
            if hidden_index and index_tokens + cost > _INDEX_TOKEN_LIMIT:
                break
            hidden_index.append((tool.name, description))
            index_tokens += cost
        return ToolSelectionResult(
            tools=selected,
            strategy=strategy,
            catalog_count=len(request.tools),
            selected_count=len(selected),
            estimated_schema_tokens=sum(_schema_tokens(tool) for tool in selected),
            expanded_tools=self.expanded_tools(request.run_id),
            hidden_tool_index=tuple(hidden_index),
            estimated_index_tokens=index_tokens,
        )


class LLMToolSelectionPolicy(_LLMSelectionState):
    """Use the host-provided fast model once per Run."""

    plugin_id = "sage.tool-selection.llm"
    name = "LLM Tool selection"
    description = "Uses a fast model and recent context to select relevant Tools."

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
        if len(context.tools) <= self.config.max_visible_tools:
            self._selected_by_run[context.run_id] = tuple(
                tool.name for tool in context.tools
            )
            self._prepared_strategy_by_run[context.run_id] = (
                "direct.catalog_within_limit"
            )
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
        stream = context.model.stream(request)
        try:
            async with asyncio.timeout(self.config.model_timeout_seconds):
                iterator = stream.__aiter__()
                try:
                    first_event = await anext(iterator)
                except StopAsyncIteration:
                    first_event = None
                if first_event is not None and first_event.response is not None:
                    response = first_event.response
                async for event in iterator:
                    if event.response is not None:
                        response = event.response
        except TimeoutError as exc:
            raise auxiliary_model_timeout_error(
                code="tool_selection.model_timeout",
                operation="LLM Tool selection",
                timeout_seconds=self.config.model_timeout_seconds,
                plugin_id=self.plugin_id,
            ) from exc
        finally:
            closer = getattr(stream, "aclose", None)
            if closer is not None:
                await closer()
        try:
            names = _parse_llm_tool_names(
                response.text if response else "", context.tools
            )
        except (TypeError, ValueError):
            names = None
        if names is None:
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
