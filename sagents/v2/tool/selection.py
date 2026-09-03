"""Tool-selection port, shared config, and ranking helpers.

Implementations live one-per-file under ``tool/plugins/selection_*.py``.
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from dataclasses import dataclass
from typing import Any, Protocol

from pydantic import Field, model_validator

from sagents.v2.contracts.common import StrictModel
from sagents.v2.contracts.items import TextBlock
from sagents.v2.model.contracts import ModelMessage
from sagents.v2.model.provider import ModelProvider
from sagents.v2.model.provider import DEFAULT_AUXILIARY_MODEL_TIMEOUT_SECONDS
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
    model_timeout_seconds: float = Field(
        default=DEFAULT_AUXILIARY_MODEL_TIMEOUT_SECONDS,
        gt=0,
        le=120,
    )

    @model_validator(mode="before")
    @classmethod
    def migrate_legacy_limits(cls, value: Any) -> Any:
        """Keep the former visible limit and discard retired expert knobs."""

        if isinstance(value, cls):
            return value
        if isinstance(value, dict):
            return {
                "max_visible_tools": value.get("max_visible_tools", 24),
                "model_timeout_seconds": value.get(
                    "model_timeout_seconds",
                    DEFAULT_AUXILIARY_MODEL_TIMEOUT_SECONDS,
                ),
            }
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
            inverse_frequency = math.log(1 + (len(documents) - df + 0.5) / (df + 0.5))
            denominator = frequency + 1.2 * (
                1 - 0.75 + 0.75 * length / max(1.0, average_length)
            )
            score += query_count * inverse_frequency * frequency * 2.2 / denominator
            if names.get(term, 0):
                score += 2.5 * query_count
        scored.append((score, tool.name))
    scored.sort(key=lambda value: (-value[0], value[1]))
    return tuple(name for _, name in scored)


def _parse_llm_tool_names(
    text: str, tools: tuple[ToolDefinition, ...]
) -> tuple[str, ...] | None:
    value = text.strip()
    if value.startswith("```"):
        lines = value.splitlines()
        value = "\n".join(lines[1:-1]).strip() if len(lines) > 2 else value
    parsed = json.loads(value)
    raw_names = parsed.get("tools") if isinstance(parsed, dict) else None
    if not isinstance(raw_names, list):
        return None
    available = {tool.name for tool in tools}
    names = tuple(
        dict.fromkeys(
            str(name).strip() for name in raw_names if str(name).strip() in available
        )
    )
    # An explicit empty list is a valid decision: this run does not need any
    # task-specific Tool. A non-empty list containing no known names is still
    # invalid provider output and must not be confused with that decision.
    return names if names or not raw_names else None


def _schema_tokens(tool: ToolDefinition) -> int:
    payload = {
        "name": tool.name,
        "description": tool.description,
        "input_schema": tool.input_schema,
        "output_schema": tool.output_schema,
    }
    return max(1, (len(json.dumps(payload, ensure_ascii=False)) + 2) // 3)
