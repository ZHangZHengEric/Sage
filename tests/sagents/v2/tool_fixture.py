"""Discover decorated built-ins, including management-only tool groups."""

import inspect

from sagents.v2.agent.self_configuration.service import _Tools
from sagents.v2.skill.tool import SkillLoadTool
from sagents.v2.tool.decorators import decorated_tool_definition
from sagents.v2.tool.plugins.agent_management import AgentManagementTools
from sagents.v2.tool.plugins.delegation import _FibreToolMethods, _TeamToolMethods
from sagents.v2.tool.plugins.official import _OFFICIAL_TOOL_CLASSES


def builtin_tool_methods():
    for owner in (
        *_OFFICIAL_TOOL_CLASSES,
        SkillLoadTool,
        AgentManagementTools,
        _Tools,
        _FibreToolMethods,
        _TeamToolMethods,
    ):
        for _, method in inspect.getmembers(owner, callable):
            definition = decorated_tool_definition(method)
            if definition is not None:
                yield definition, method
