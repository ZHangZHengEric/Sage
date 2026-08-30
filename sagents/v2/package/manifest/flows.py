"""Declarative flow graph contracts."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from sagents.v2.contracts.common import Identifier, StrictModel, ToolName


class FlowNode(StrictModel):
    id: Identifier
    type: Literal["agent", "tool", "interaction", "parallel", "join", "subflow", "end"]
    agent: Identifier | None = None
    tool: ToolName | None = None
    interaction: Identifier | None = None
    flow: Identifier | None = None
    blocking_scope: str | None = None
    config: dict[str, Any] = Field(default_factory=dict)


class FlowEdge(StrictModel):
    source: Identifier = Field(alias="from")
    target: Identifier = Field(alias="to")
    when: str | None = None
    priority: int = 0


class FlowDefinition(StrictModel):
    version: str
    start: Identifier
    nodes: tuple[FlowNode, ...]
    edges: tuple[FlowEdge, ...] = ()
