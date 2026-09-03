"""Official Tool-selection plugin: expose every policy-allowed Tool."""

from __future__ import annotations

from sagents.v2.tool.contracts import ToolDefinition
from sagents.v2.tool.selection import (
    DEFAULT_ALWAYS_VISIBLE_TOOLS,
    ToolSelectionConfig,
    ToolSelectionPrepareContext,
    ToolSelectionRequest,
    ToolSelectionResult,
    _EXPANSION_BATCH_LIMIT,
    _INDEX_DESCRIPTION_CHARS,
    _INDEX_ENTRY_LIMIT,
    _INDEX_TOKEN_LIMIT,
    _schema_tokens,
)


class _DirectSelectionState:
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


class DirectToolSelectionPolicy(_DirectSelectionState):
    """Expose every policy-allowed Tool; the count limit is not applicable."""

    plugin_id = "sage.tool-selection.direct"
    name = "Show all Tools"
    description = (
        "Sends every policy-allowed Tool to the model. Best for small catalogs."
    )

    def __init__(self, config: dict | None = None) -> None:
        super().__init__({})

    def select(self, request: ToolSelectionRequest) -> ToolSelectionResult:
        self._remember_catalog(request.run_id, request.tools)
        return self._result(request, request.tools, "direct")
