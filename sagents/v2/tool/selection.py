"""Tool-selection interface, configuration and request/result contracts.

Implementations live one-per-file under ``tool/plugins/selection_*.py``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from pydantic import Field, model_validator

from sagents.v2.contracts.common import StrictModel
from sagents.v2.model.contracts import ModelMessage
from sagents.v2.model.provider import ModelProvider
from sagents.v2.model.provider import DEFAULT_AUXILIARY_MODEL_TIMEOUT_SECONDS
from sagents.v2.tool.contracts import ToolDefinition


# Internal safety constants, intentionally not user-facing configuration.


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
    schema_characters: int
    expanded_tools: tuple[str, ...] = ()
    hidden_tool_index: tuple[tuple[str, str], ...] = ()
    index_characters: int = 0


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
