# For licensing see accompanying LICENSE file.
# Copyright (C) 2024 Apple Inc. All Rights Reserved.
"""Utilities for working with tools in the Anthropic API.

Adapted from langchain_anthropic>=0.1.15 , see
https://github.com/langchain-ai/langchain/blob/v0.1.15/libs/partners/anthropic/langchain_anthropic/chat_models.py

The reason for copying instead of depending on it is that we are currently pinned to
langchain version 0.1.3, which does not have the necessary helper functions for working
with tools in the Anthropic API format.
"""

from typing import Any, Callable

from anthropic.types.beta.tools import ToolParam

from tool_sandbox.common.tool_conversion import convert_to_openai_tool


def convert_to_anthropic_tool(name: str, tool: Callable[..., Any]) -> ToolParam:
    formatted = convert_to_openai_tool(tool, name=name)["function"]
    return ToolParam(
        name=formatted["name"],
        description=formatted["description"],
        input_schema=formatted["parameters"],
    )
