"""Resource-free metadata for Sage-owned tools, independent of Run assembly."""

from __future__ import annotations

import inspect
from typing import Literal

from sagents.v2.agent.multi_agent.contracts import AgentMode
from sagents.v2.tool.plugins.skill.operations import SkillLoadTool
from sagents.v2.tool.contracts import ToolDefinition
from sagents.v2.tool.decorators import decorated_tool_definition
from sagents.v2.tool.localization import localize_tool_definition
from sagents.v2.tool.plugins.delegation import _FibreToolMethods, _TeamToolMethods
from sagents.v2.tool.plugins.official import official_tool_definitions


def builtin_tool_definitions(
    *,
    agent_mode: AgentMode | Literal["simple", "fibre", "team", "flow", "all"] = "all",
    language: str | None = None,
) -> tuple[ToolDefinition, ...]:
    """Return detached, name-sorted metadata without creating execution objects.

    Every mode includes official base tools and ``load_skill``. Team adds its
    declared-member delegation tool; Fibre adds spawn and delegation tools.
    ``all`` returns their union for a host's settings catalog. Simple and Flow
    do not add delegation tools. Unknown modes raise ``ValueError``.

    Definitions describe the built-in inventory, not the grants or available
    tools of any particular Run. Agent, invocation, plugin and authorization
    policies still determine actual availability during standard execution.
    External and custom provider metadata belongs to those providers.
    """
    owners = {
        "simple": (SkillLoadTool,),
        "flow": (SkillLoadTool,),
        "team": (SkillLoadTool, _TeamToolMethods),
        "fibre": (SkillLoadTool, _FibreToolMethods),
        "all": (SkillLoadTool, _TeamToolMethods, _FibreToolMethods),
    }
    if not isinstance(agent_mode, str) or agent_mode not in owners:
        raise ValueError("agent_mode must be simple, fibre, team, flow, or all")
    definitions = {value.name: value for value in official_tool_definitions()}
    for owner in owners[agent_mode]:
        for _, method in inspect.getmembers(owner, callable):
            definition = decorated_tool_definition(method)
            if definition is not None:
                if definition.name in definitions:
                    raise ValueError(f"duplicate built-in Tool {definition.name!r}")
                definitions[definition.name] = definition
    result = tuple(
        definitions[name].model_copy(deep=True) for name in sorted(definitions)
    )
    return (
        tuple(localize_tool_definition(value, language) for value in result)
        if language is not None
        else result
    )


__all__ = ["builtin_tool_definitions"]
