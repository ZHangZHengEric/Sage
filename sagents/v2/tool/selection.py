"""Standard plugin interface and built-ins for Run-scoped Tool selection.

Tool providers answer what exists.  A Tool-selection plugin decides which
policy-allowed definitions enter a model request.  Built-ins expose at most one
user setting; third-party plugins may declare their own extension config schema.
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from dataclasses import dataclass
from typing import Any, Protocol

from pydantic import Field, model_validator

from sagents.v2.contracts.common import StrictModel, new_id
from sagents.v2.contracts.items import TextBlock
from sagents.v2.i18n import tr
from sagents.v2.model.contracts import ModelMessage, ModelRequest
from sagents.v2.model.provider import ModelProvider
from sagents.v2.tool.contracts import ToolDefinition


DEFAULT_ALWAYS_VISIBLE_TOOLS = (
    "tool_expand_tools",
    "questionnaire_async",
    "turn_status",
    "load_skill",
    "plan_submit",
    "goal_submit",
    "goal_create",
    "goal_complete",
    "sys_spawn_agent",
    "sys_delegate_task",
    "sys_team_delegate_task",
)

# Internal safety constants, intentionally not user-facing configuration.
_CONTEXT_TURNS = 5
_INDEX_ENTRY_LIMIT = 128
_INDEX_TOKEN_LIMIT = 2_000
_INDEX_DESCRIPTION_CHARS = 96
_EXPANSION_BATCH_LIMIT = 8


class ToolSelectionConfig(StrictModel):
    """Shared configuration used by the bounded official plugins."""

    max_visible_tools: int = Field(default=24, ge=1, le=10_000)

    @model_validator(mode="before")
    @classmethod
    def migrate_legacy_limits(cls, value: Any) -> Any:
        """Keep the former visible limit and discard retired expert knobs."""

        if isinstance(value, cls):
            return value
        if isinstance(value, dict):
            return {"max_visible_tools": value.get("max_visible_tools", 24)}
        return value


@dataclass(frozen=True)
class ToolSelectionPrepareContext:
    """Side-effect-free inputs available during the parallel prepare stage."""

    run_id: str
    tools: tuple[ToolDefinition, ...]
    messages: tuple[ModelMessage, ...] = ()
    language: str = "en"
    model: ModelProvider | None = None


@dataclass(frozen=True)
class ToolSelectionRequest:
    """Inputs available for every model-step projection."""

    run_id: str
    tools: tuple[ToolDefinition, ...]
    messages: tuple[ModelMessage, ...] = ()


@dataclass(frozen=True)
class ToolSelectionResult:
    tools: tuple[ToolDefinition, ...]
    strategy: str
    catalog_count: int
    selected_count: int
    estimated_schema_tokens: int
    expanded_tools: tuple[str, ...] = ()
    hidden_tool_index: tuple[tuple[str, str], ...] = ()
    estimated_index_tokens: int = 0


class ToolSelectionPolicy(Protocol):
    """Stable interface implemented by built-in and third-party plugins."""

    plugin_id: str
    config: Any

    async def prepare(self, context: ToolSelectionPrepareContext) -> None: ...
    def select(self, request: ToolSelectionRequest) -> ToolSelectionResult: ...

    def expand_tools(
        self,
        *,
        run_id: str,
        names: tuple[str, ...],
        available_names: tuple[str, ...] | None = None,
    ) -> dict[str, object]: ...

    def expanded_tools(self, run_id: str) -> tuple[str, ...]: ...
    def restore_expanded_tools(self, run_id: str, names: tuple[str, ...]) -> None: ...
    def release_run(self, run_id: str) -> None: ...


class BaseToolSelectionPolicy:
    plugin_id = "sage.tool-selection.base"

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
        unknown = sorted(set(requested) - available) if available else []
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
            self._expanded_by_run[run_id] = set(
                names[: self.config.max_visible_tools]
            )

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
        return tuple(
            by_name[name] for name in ordered[: self.config.max_visible_tools]
        )

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
            description = " ".join(tool.description.split())[
                :_INDEX_DESCRIPTION_CHARS
            ]
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


class DirectToolSelectionPolicy(BaseToolSelectionPolicy):
    """Expose every policy-allowed Tool; the count limit is not applicable."""

    plugin_id = "sage.tool-selection.direct"

    def __init__(self, config: dict | None = None) -> None:
        super().__init__({})

    def select(self, request: ToolSelectionRequest) -> ToolSelectionResult:
        self._remember_catalog(request.run_id, request.tools)
        return self._result(request, request.tools, "direct")


class LexicalToolSelectionPolicy(BaseToolSelectionPolicy):
    """Local BM25-style ranking over Tool names, descriptions, and schemas."""

    plugin_id = "sage.tool-selection.lexical"

    def select(self, request: ToolSelectionRequest) -> ToolSelectionResult:
        self._remember_catalog(request.run_id, request.tools)
        selected = self._bounded(
            request, _bm25_ranked_names(request.tools, _recent_text(request.messages))
        )
        return self._result(request, selected, "lexical.bm25")


class RecentToolSelectionPolicy(BaseToolSelectionPolicy):
    """Put recently called Tools first, then fill the remaining count."""

    plugin_id = "sage.tool-selection.recent"

    def select(self, request: ToolSelectionRequest) -> ToolSelectionResult:
        self._remember_catalog(request.run_id, request.tools)
        selected = self._bounded(
            request,
            _recent_tool_names(request.messages),
            preferred_first=True,
        )
        return self._result(request, selected, "recent")


class LLMToolSelectionPolicy(BaseToolSelectionPolicy):
    """Use the host-provided fast model once per Run with bounded fallback."""

    plugin_id = "sage.tool-selection.llm"

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
            max_output_tokens=1_000,
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
            names = _parse_llm_tool_names(response.text if response else "", context.tools)
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


class HybridToolSelectionPolicy(LexicalToolSelectionPolicy):
    """Deprecated source-compatible alias; no longer registered or shown."""

    plugin_id = "sage.tool-selection.hybrid"


def _recent_text(messages: tuple[ModelMessage, ...]) -> str:
    user_messages = [message for message in messages if message.role == "user"][
        -_CONTEXT_TURNS:
    ]
    return "\n".join(
        block.text
        for message in user_messages
        for block in message.content
        if isinstance(block, TextBlock)
    )


def _recent_tool_names(messages: tuple[ModelMessage, ...]) -> tuple[str, ...]:
    names: list[str] = []
    for message in reversed(messages):
        for call in reversed(message.tool_calls):
            if call.name not in names:
                names.append(call.name)
    return tuple(names)


def _compact_history(messages: tuple[ModelMessage, ...]) -> str:
    selected: list[ModelMessage] = []
    user_turns = 0
    for message in reversed(messages):
        selected.append(message)
        if message.role == "user":
            user_turns += 1
            if user_turns >= _CONTEXT_TURNS:
                break
    lines: list[str] = []
    for message in reversed(selected):
        text = " ".join(
            block.text for block in message.content if isinstance(block, TextBlock)
        ).strip()
        if text:
            lines.append(f"{message.role}: {text[:1_000]}")
        if message.tool_calls:
            lines.append(
                "assistant: [tools used: "
                + ", ".join(call.name for call in message.tool_calls)
                + "]"
            )
    return "\n".join(lines)


def _terms(value: str) -> Counter[str]:
    return Counter(re.findall(r"[a-z0-9_]+|[\u3400-\u9fff]", value.casefold()))


def _bm25_ranked_names(
    tools: tuple[ToolDefinition, ...], query: str
) -> tuple[str, ...]:
    if not tools:
        return ()
    query_terms = _terms(query)
    documents: list[Counter[str]] = []
    name_terms: list[Counter[str]] = []
    for tool in tools:
        names = _terms(tool.name.replace("_", " "))
        description = _terms(tool.description)
        schema = _terms(
            json.dumps(tool.input_schema, ensure_ascii=False, sort_keys=True)
        )
        documents.append(names + description + schema)
        name_terms.append(names)
    if not query_terms:
        return tuple(tool.name for tool in tools)
    document_frequency = Counter(
        term for document in documents for term in document.keys()
    )
    average_length = sum(sum(document.values()) for document in documents) / max(
        1, len(documents)
    )
    scored: list[tuple[float, str]] = []
    for tool, document, names in zip(tools, documents, name_terms, strict=True):
        length = max(1, sum(document.values()))
        score = 0.0
        for term, query_count in query_terms.items():
            frequency = document.get(term, 0)
            if frequency == 0:
                continue
            df = document_frequency[term]
            inverse_frequency = math.log(
                1 + (len(documents) - df + 0.5) / (df + 0.5)
            )
            denominator = frequency + 1.2 * (
                1 - 0.75 + 0.75 * length / max(1.0, average_length)
            )
            score += (
                query_count
                * inverse_frequency
                * frequency
                * 2.2
                / denominator
            )
            if names.get(term, 0):
                score += 2.5 * query_count
        scored.append((score, tool.name))
    scored.sort(key=lambda value: (-value[0], value[1]))
    return tuple(name for _, name in scored)


def _parse_llm_tool_names(
    text: str, tools: tuple[ToolDefinition, ...]
) -> tuple[str, ...]:
    value = text.strip()
    if value.startswith("```"):
        lines = value.splitlines()
        value = "\n".join(lines[1:-1]).strip() if len(lines) > 2 else value
    parsed = json.loads(value)
    raw_names = parsed.get("tools") if isinstance(parsed, dict) else None
    if not isinstance(raw_names, list):
        return ()
    available = {tool.name for tool in tools}
    return tuple(
        dict.fromkeys(
            str(name).strip()
            for name in raw_names
            if str(name).strip() in available
        )
    )


def _schema_tokens(tool: ToolDefinition) -> int:
    payload = {
        "name": tool.name,
        "description": tool.description,
        "input_schema": tool.input_schema,
        "output_schema": tool.output_schema,
    }
    return max(1, (len(json.dumps(payload, ensure_ascii=False)) + 2) // 3)
