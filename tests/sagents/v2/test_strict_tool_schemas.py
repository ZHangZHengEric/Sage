"""Audit all built-ins and their actual OpenAI wire schemas, without API calls."""

from copy import deepcopy
import inspect

import pytest

from sagents.v2.agent.self_configuration.service import _Tools
from sagents.v2.skill.tool import SkillLoadTool
from sagents.v2.tool.plugins.agent_management import AgentManagementTools
from sagents.v2.tool.plugins.delegation import _FibreToolMethods, _TeamToolMethods
from sagents.v2.tool.plugins.official import _OFFICIAL_TOOL_CLASSES
from sagents.v2.tool.decorators import decorated_tool_definition
from sagents.v2.model.contracts import (
    ModelCapabilities,
    ModelMessage,
    ModelRequest,
    ModelToolDefinition,
)
from sagents.v2.model.plugins.openai_compatible import (
    OpenAIChatCompletionsModelProvider,
    OpenAICompatibleConfig,
)
from sagents.v2.model.plugins.openai_responses import (
    OpenAIResponsesModelProvider,
    OpenAIResponsesConfig,
)
from sagents.v2.contracts.items import TextBlock


def builtin_definitions():
    definitions = {}
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
                definitions[definition.name] = definition
    return definitions


def assert_strict_schema(node, path="parameters"):
    if not isinstance(node, dict):
        return
    assert "default" not in node, path
    if node.get("type") == "object" or "properties" in node:
        assert node.get("additionalProperties") is False, path
        assert set(node.get("required", [])) == set(node.get("properties", {})), path
    for key in ("properties", "$defs", "definitions"):
        for name, value in node.get(key, {}).items():
            assert_strict_schema(value, f"{path}.{key}.{name}")
    if isinstance(node.get("items"), dict):
        assert_strict_schema(node["items"], f"{path}.items")
    for key in ("anyOf", "oneOf", "allOf", "prefixItems"):
        for index, value in enumerate(node.get(key, [])):
            assert_strict_schema(value, f"{path}.{key}[{index}]")


def test_audit_every_builtin_strict_tool_schema():
    definitions = builtin_definitions()
    assert len(definitions) == 39
    strict = [
        definition for definition in definitions.values() if definition.strict is True
    ]
    assert {definition.name for definition in strict} == {
        "load_skill",
        "goal_submit",
        "goal_complete",
    }
    for definition in strict:
        assert_strict_schema(definition.input_schema, definition.name)


@pytest.mark.parametrize("protocol", ["chat", "responses"])
def test_every_strict_builtin_is_valid_in_actual_openai_request(protocol):
    definitions = builtin_definitions()
    tools = tuple(
        ModelToolDefinition(
            name=value.name,
            description=value.description,
            input_schema=deepcopy(value.input_schema),
            strict=value.strict,
        )
        for value in definitions.values()
    )
    request = ModelRequest(
        request_id="request",
        run_id="run",
        model_binding="primary",
        messages=(ModelMessage(role="user", content=(TextBlock(text="hello"),)),),
        tools=tools,
    )
    provider = (
        OpenAIChatCompletionsModelProvider(
            OpenAICompatibleConfig(
                model="test",
                base_url="https://unused.invalid/v1",
                capabilities=ModelCapabilities(
                    supports_streaming=True,
                    supports_tools=True,
                    supports_parallel_tool_calls=True,
                    supports_reasoning=False,
                    supports_multimodal_input=False,
                    supports_structured_output=False,
                ),
            ),
            client=object(),
        )
        if protocol == "chat"
        else OpenAIResponsesModelProvider(
            OpenAIResponsesConfig(
                model="test",
                capabilities=ModelCapabilities(
                    supports_streaming=True,
                    supports_tools=True,
                    supports_parallel_tool_calls=True,
                    supports_reasoning=False,
                    supports_multimodal_input=False,
                    supports_structured_output=False,
                ),
            ),
            client=object(),
        )
    )
    payload = provider.diagnostic_request(request)
    assert len(payload["tools"]) == 39
    strict_count = 0
    for tool in payload["tools"]:
        function = tool["function"] if protocol == "chat" else tool
        if function.get("strict") is True:
            strict_count += 1
            assert_strict_schema(function["parameters"], function["name"])
    assert strict_count == 3
