"""Audit all built-ins and their actual OpenAI wire schemas, without API calls."""

from copy import deepcopy

import pytest

from tests.sagents.v2.tool_fixture import builtin_tool_methods
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


STRICT_TOOL_NAMES = {"load_skill", "goal_submit", "goal_complete"}


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
    definitions = tuple(definition for definition, _ in builtin_tool_methods())
    strict = [
        definition for definition in definitions if definition.strict is True
    ]
    assert {definition.name for definition in strict} == STRICT_TOOL_NAMES
    for definition in strict:
        assert_strict_schema(definition.input_schema, definition.name)


@pytest.mark.parametrize("protocol", ["chat", "responses"])
def test_every_strict_builtin_is_valid_in_actual_openai_request(protocol):
    definitions = tuple(definition for definition, _ in builtin_tool_methods())
    tools = tuple(
        ModelToolDefinition(
            name=value.name,
            description=value.description,
            input_schema=deepcopy(value.input_schema),
            strict=value.strict,
        )
        for value in definitions
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
    assert len(payload["tools"]) == len(definitions)
    projected_names = set()
    strict_names = set()
    for tool in payload["tools"]:
        function = tool["function"] if protocol == "chat" else tool
        projected_names.add(function["name"])
        if function.get("strict") is True:
            strict_names.add(function["name"])
            assert_strict_schema(function["parameters"], function["name"])
    assert projected_names == {definition.name for definition in definitions}
    assert strict_names == STRICT_TOOL_NAMES
