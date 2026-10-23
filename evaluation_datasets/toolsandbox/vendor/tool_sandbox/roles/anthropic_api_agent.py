# For licensing see accompanying LICENSE file.
# Copyright (C) 2024 Apple Inc. All Rights Reserved.
"""Agent role for any model that conforms to Anthropic tool use API."""

import ast
import dataclasses
import logging
import re
from typing import Iterable, Optional, Union, cast

import anthropic
import anthropic.types.beta.tools
from requests.exceptions import HTTPError
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_random_exponential,
)

from tool_sandbox.common.execution_context import RoleType, get_current_context
from tool_sandbox.common.message_conversion import Message
from tool_sandbox.roles.anthropic_tool_utils import convert_to_anthropic_tool
from tool_sandbox.roles.base_role import BaseRole

LOGGER = logging.getLogger(__name__)


def tool_use_block_to_python_code(
    execution_facing_tool_name: str,
    tool_use_block: anthropic.types.beta.tools.ToolUseBlock,
    available_tool_names: set[str],
) -> str:
    """Converts Anthropic tool use block to Python code for calling the function.

    Args:
        execution_facing_tool_name:  The execution facing name of the function. In the
                                     case of tool name scrambling the OpenAI API in- and
                                     outputs are filled with scrambled tool names. When
                                     executing the code we need to use the actual tool
                                     name. If `None` the tool name stored in `tool_call`
                                     will be used.
        tool_use_block:              The tool use block describing the function name and
                                     arguments.
        available_tool_names:        Set of available tools.

    Returns:
        The Python code for making the tool call.

    Raises:
        KeyError: If the selected tool is not a known tool.
    """
    # Check if the function name is known allowed tool.
    agent_facing_tool_name = tool_use_block.name
    if agent_facing_tool_name not in available_tool_names:
        raise KeyError(
            f"Agent tool call {agent_facing_tool_name=} is not a known allowed tool. Options "
            f"are {available_tool_names=}."
        )

    # Note that `tool_use_block.input` is a Python dictionary.
    tool_id = tool_use_block.id
    function_call_code = (
        f"{tool_id}_parameters = {tool_use_block.input}\n"
        f"{tool_id}_response = {execution_facing_tool_name}(**{tool_id}_parameters)\n"
        f"print(repr({tool_id}_response))"
    )
    return function_call_code


def to_tool_call_message(
    tool_use_block: anthropic.types.beta.tools.ToolUseBlock,
    sender: RoleType,
    execution_facing_tool_name: str,
    available_tool_names: set[str],
) -> Message:
    """Convert a tool use block to the tool sandbox message format.

    Args:
        tool_use_block:              The tool use block describing the function name and
                                     arguments.
        sender:                      The value of the sender in the tool sandbox
                                     message being created.
        execution_facing_tool_name:  The execution facing name of the function. In the
                                     case of tool name scrambling the OpenAI API in- and
                                     outputs are filled with scrambled tool names. When
                                     executing the code we need to use the actual tool
                                     name. If `None` the tool name stored in `tool_call`
                                     will be used.
        available_tool_names:        Set of available tools.

    Returns:
        A message in the tool sandbox format.
    """
    # The code below would fail when e.g. called with a `TextBlock` object, but the
    # assertion will give a clear error message.
    assert tool_use_block.type == "tool_use", (
        "This function must only be called with content blocks of type 'tool_use', but "
        f"got '{tool_use_block.type}'."
    )
    return Message(
        sender=sender,
        recipient=RoleType.EXECUTION_ENVIRONMENT,
        content=tool_use_block_to_python_code(
            execution_facing_tool_name, tool_use_block, available_tool_names
        ),
        openai_tool_call_id=tool_use_block.id,
        openai_function_name=tool_use_block.name,
    )


def response_to_messages(
    response: anthropic.types.beta.tools.ToolsBetaMessage,
    sender: RoleType,
    available_tool_names: set[str],
    agent_to_execution_facing_tool_name: dict[str, str],
) -> list[Message]:
    """Convert an Anthropic API response to messages in the tool sandbox format.

    Args:
        response:             The response from the Anthropic API.
        sender:               The value of the sender in the tool sandbox message being
                              created.
        available_tool_names: Set of available tools.

    Returns:
        Messages in the tool sandbox format.
    """
    # In non-streaming mode, which is the only supported mode here, the `stop_reason`
    # must not be `None`, see
    # https://github.com/anthropics/anthropic-sdk-python/blob/main/src/anthropic/types/beta/tools/tools_beta_message.py#L74
    # We rely on the stop reason to determine if a tool call is needed.
    assert response.stop_reason is not None

    if response.stop_reason == "tool_use":
        assert len(response.content) > 0 and any(
            isinstance(content_block, anthropic.types.beta.tools.ToolUseBlock)
            for content_block in response.content
        ), "At least 1 ToolUseBlock content element is needed for tool use, but got 0."
        # The content can have mixed blocks like text and tool use blocks.
        return [
            to_tool_call_message(
                content_block,
                sender,
                execution_facing_tool_name=agent_to_execution_facing_tool_name[
                    content_block.name
                ],
                available_tool_names=available_tool_names,
            )
            for content_block in response.content
            if isinstance(content_block, anthropic.types.beta.tools.ToolUseBlock)
        ]

    # No tool use needed. Simply return the text response.
    assert (
        len(response.content) == 1
    ), f"Only a single content element is supported, but got {len(response.content)}."
    text_block = response.content[0]
    assert isinstance(
        text_block, anthropic.types.text_block.TextBlock
    ), f"Expected content element to be a `TextBlock`, but got {type(text_block)}."
    return [
        Message(
            sender=sender,
            recipient=RoleType.USER,
            content=text_block.text,
        )
    ]


@dataclasses.dataclass(frozen=True)
class AnthropicMessageCollection:
    """Collection of messages and system prompt in the Anthropic API format.

    Attributes:
        messages: The list of messages in the Anthropic API format.
        system_prompt: Optional string to use as system prompt. Note that unlike the
                       OpenAI and Gemini APIs the Anthropic API handles system prompts
                       explicitly instead of just using `role: "system"` for this, see
                       https://docs.anthropic.com/claude/docs/system-prompts#how-to-use-system-prompts
    """

    messages: list[anthropic.types.beta.tools.ToolsBetaMessageParam]
    system_prompt: Union[str, anthropic.NotGiven]


def has_tool_result_block(
    anthropic_message: anthropic.types.beta.tools.ToolsBetaMessageParam,
) -> bool:
    """Check if the given Anthropic API message has a tool result block.

    Args:
        anthropic_message: The Anthropic API message.

    Returns:
        True if the message contains at least one tool result, false otherwise.
    """
    return isinstance(anthropic_message, dict) and any(
        isinstance(block, dict) and block.get("type", "") == "tool_result"
        for block in anthropic_message["content"]
    )


def to_anthropic_tool_result_block(
    message: Message,
) -> anthropic.types.beta.tools.ToolResultBlockParam:
    """Convert a tool sandbox message to an Anthropic tool result block.

    Args:
        message: The tool sandbox message.

    Returns:
        The Anthropic tool result block.
    """
    assert message.openai_tool_call_id is not None
    assert message.openai_function_name is not None
    return anthropic.types.beta.tools.ToolResultBlockParam(
        tool_use_id=message.openai_tool_call_id,
        type="tool_result",
        content=[anthropic.types.TextBlockParam(text=message.content, type="text")],
        is_error=message.tool_call_exception is not None,
    )


def has_tool_use_block(
    anthropic_message: anthropic.types.beta.tools.ToolsBetaMessageParam,
) -> bool:
    """Check if the given Anthropic API message has a tool use block.

    Args:
        anthropic_message: The Anthropic API message.

    Returns:
        True if the message contains at least one tool use, false otherwise.
    """
    return isinstance(anthropic_message, dict) and any(
        isinstance(block, anthropic.types.beta.tools.ToolUseBlock)
        for block in anthropic_message["content"]
    )


def to_anthropic_tool_use_block(
    message: Message,
) -> anthropic.types.beta.tools.ToolUseBlock:
    """Convert a tool sandbox message to an Anthropic tool use block.

    Args:
        message: The tool sandbox message.

    Returns:
        The Anthropic tool use block.
    """
    pattern = r"^(?P<tool_id>.+)_parameters = (?P<arguments>[^\n]+)\n(?P=tool_id)_response = (?P<name>[^\(]+)"
    match = re.match(pattern=pattern, string=message.content)
    assert match is not None
    assert message.openai_tool_call_id is not None
    assert message.openai_function_name is not None
    return anthropic.types.beta.tools.ToolUseBlock(
        id=message.openai_tool_call_id,
        input=ast.literal_eval(match.group("arguments")),
        name=message.openai_function_name,
        type="tool_use",
    )


def to_anthropic_message_collection(
    messages: list[Message],
) -> AnthropicMessageCollection:
    """Converts a list of Tool Sandbox messages to Anthropic API messages.

    Args:
        messages:   A list of Tool Sandbox messages
        tools:      tools associated to this function call

    Returns:
        A list of Anthropic API messages and a system prompt.
    """
    anthropic_messages: list[anthropic.types.beta.tools.ToolsBetaMessageParam] = []
    # The Anthropic API expects system prompts as a separate argument instead of just
    # providing them via a "system" role like in the OpenAI API. Note that multiple
    # system prompts are not supported.
    system_prompt: Union[str, anthropic.NotGiven] = anthropic.NOT_GIVEN

    for message in messages:
        if message.sender == RoleType.SYSTEM and message.recipient == RoleType.AGENT:
            assert (
                system_prompt is anthropic.NOT_GIVEN
            ), f"System prompt is already set to '{system_prompt}'."
            system_prompt = message.content
        elif message.sender == RoleType.USER and message.recipient == RoleType.AGENT:
            anthropic_messages.append(
                anthropic.types.beta.tools.ToolsBetaMessageParam(
                    content=message.content, role="user"
                )
            )
        elif (
            message.sender == RoleType.EXECUTION_ENVIRONMENT
            and message.recipient == RoleType.AGENT
        ):
            # The API requires one to group multiple tool results into a single message.
            # Otherwise one gets a failure complaining about a tool result for an
            # unknown tool use.
            tool_result_block = to_anthropic_tool_result_block(message)
            if len(anthropic_messages) > 0 and has_tool_result_block(
                anthropic_messages[-1]
            ):
                # The content is of type `Union[str, Iterable[...]]`, but in this case
                # it is guaranteed to be a list.
                assert isinstance(anthropic_messages[-1]["content"], list)  # < mypy
                anthropic_messages[-1]["content"].append(tool_result_block)
            else:
                anthropic_messages.append(
                    anthropic.types.beta.tools.ToolsBetaMessageParam(
                        content=[tool_result_block], role="user"
                    )
                )
        elif (
            message.sender == RoleType.AGENT
            and message.recipient == RoleType.EXECUTION_ENVIRONMENT
        ):
            # Add tool call. Note that the API requires one to group multiple tool
            # results into a single message.
            tool_use_block = to_anthropic_tool_use_block(message)
            if len(anthropic_messages) > 0 and has_tool_use_block(
                anthropic_messages[-1]
            ):
                # The content is of type `Union[str, Iterable[...]]`, but in this case
                # it is guaranteed to be a list.
                assert isinstance(anthropic_messages[-1]["content"], list)  # < mypy
                anthropic_messages[-1]["content"].append(tool_use_block)
            else:
                anthropic_messages.append(
                    anthropic.types.beta.tools.ToolsBetaMessageParam(
                        content=[tool_use_block], role="assistant"
                    )
                )
        elif message.sender == RoleType.AGENT and message.recipient == RoleType.USER:
            anthropic_messages.append(
                anthropic.types.beta.tools.ToolsBetaMessageParam(
                    content=message.content, role="assistant"
                )
            )
        else:
            raise ValueError(
                "Unrecognized sender recipient pair "
                f"{(message.sender, message.recipient)}"
            )

    return AnthropicMessageCollection(
        messages=anthropic_messages, system_prompt=system_prompt
    )


class AnthropicAPIAgent(BaseRole):
    """Agent role for any model that conforms to Anthropic tool use API."""

    role_type: RoleType = RoleType.AGENT
    model_name: str

    def __init__(self) -> None:
        # By default, the API looks for the `ANTHROPIC_API_KEY` environment variable.
        self.client = anthropic.Anthropic()

        # By default, the HTTP request client used by the Anthropic API is logging every
        # HTTP request, e.g.:
        # PM INFO HTTP Request: POST https://api.anthropic.com/v1/messages?beta=tools "HTTP/1.1 200 OK"
        # To silence these we set the log level to warning and higher, see
        # https://github.com/langchain-ai/langchain/issues/14065#issuecomment-1834571761
        httpx_logger = logging.getLogger("httpx")
        httpx_logger.setLevel(logging.WARNING)

    def respond(self, ending_index: Optional[int] = None) -> None:
        """Reads a List of messages and attempt to respond with a Message

        Specifically, interprets system, user, execution environment messages and sends out NL response to user, or
        code snippet to execution environment.

        Message comes from current context, the last k messages should be directed to this role type
        Response are written to current context as well. n new messages, addressed to appropriate recipient
        k != n when dealing with parallel function call and responses. Parallel function call are expanded into
        individual messages, parallel function call responses are combined as 1 OpenAI API request

        Args:
            ending_index:   Optional index. Will respond to message located at ending_index instead of most recent one
                            if provided. Utility for processing system message, which could contain multiple entries
                            before each was responded to

        Raises:
            KeyError:   When the last message is not directed to this role
        """
        messages: list[Message] = self.get_messages(ending_index=ending_index)
        self.messages_validation(messages=messages)
        # Keeps only relevant messages
        messages = self.filter_messages(messages=messages)
        # Does not respond to System
        if messages[-1].sender == RoleType.SYSTEM:
            return

        # Get tools if most recent message is from user
        available_tools = self.get_available_tools()
        anthropic_tools = (
            [
                convert_to_anthropic_tool(name, tool)
                for name, tool in available_tools.items()
            ]
            if messages[-1].sender == RoleType.USER
            or messages[-1].sender == RoleType.EXECUTION_ENVIRONMENT
            else anthropic.NOT_GIVEN
        )
        # Not sure why Mypy infers the type of `anthropic_tools` to be `object`. The
        # pylance tooltip in VSCode correctly says `list[ToolParam] | NotGiven` (even
        # without the cast).
        anthropic_tools = cast(
            Union[Iterable[anthropic.types.beta.tools.ToolParam], anthropic.NotGiven],
            anthropic_tools,
        )
        # Convert from tool sandbox message to Anthropic message format.
        message_collection = to_anthropic_message_collection(messages=messages)
        # Call model
        response = self.model_inference(
            anthropic_messages=message_collection.messages,
            system=message_collection.system_prompt,
            anthropic_tools=anthropic_tools,
        )

        # Convert the response to internal data types.
        available_tool_names = set(available_tools.keys())
        agent_to_execution_tool_name = (
            get_current_context().get_agent_to_execution_facing_tool_name()
        )
        response_messages = response_to_messages(
            response,
            sender=self.role_type,
            available_tool_names=available_tool_names,
            agent_to_execution_facing_tool_name=agent_to_execution_tool_name,
        )
        self.add_messages(response_messages)

    @retry(
        wait=wait_random_exponential(multiplier=1, max=40),
        stop=stop_after_attempt(3),
        retry=retry_if_exception_type(HTTPError),
    )
    def model_inference(
        self,
        anthropic_messages: list[anthropic.types.beta.tools.ToolsBetaMessageParam],
        system: Union[str, anthropic.NotGiven],
        anthropic_tools: Union[
            Iterable[anthropic.types.beta.tools.ToolParam], anthropic.NotGiven
        ],
    ) -> anthropic.types.beta.tools.ToolsBetaMessage:
        """Run OpenAI model inference

        Args:
            anthropic_messages:  Messages in Anthropic format to send to the LLM.
            system:              Optional system prompt. These are handled separately
                                 from messages as opposed to the OpenAI API format where
                                 one just uses the "system" role.
            anthropic_tools:     List of tools in the Anthropic format.

        Returns:
            Anthropic's `ToolsBetaMessage` object.
        """
        LOGGER.debug("Anthropic agent processes these messages: %s", anthropic_messages)
        response = self.client.beta.tools.messages.create(
            model=self.model_name,
            system=system,
            messages=anthropic_messages,
            tools=anthropic_tools,
            max_tokens=1024,
            # We set the temperature to 0 for more deterministic results, but according
            # to https://docs.anthropic.com/claude/reference/complete_post still not
            # fully deterministic.
            temperature=0,
        )
        # The `messages.create` return type hint is a union of the tools message and a
        # stream, but this code expects and can only handle the non-streamed response.
        assert isinstance(response, anthropic.types.beta.tools.ToolsBetaMessage)
        return response


# A high-level summary of the Claude 3 model family from
# https://docs.anthropic.com/claude/docs/models-overview#claude-3-a-new-generation-of-ai :
# - Opus:   Our most powerful model, delivering state-of-the-art performance on highly
#           complex tasks and demonstrating fluency and human-like understanding
# - Sonnet: Our most balanced model between intelligence and speed, a great choice for
#           enterprise workloads and scaled AI deployments
# - Haiku:  Our fastest and most compact model, designed for near-instant responsiveness
#           and seamless AI experiences that mimic human interactions


class ClaudeOpusAgent(AnthropicAPIAgent):
    model_name = "claude-3-opus-20240229"


class ClaudeSonnetAgent(AnthropicAPIAgent):
    model_name = "claude-3-sonnet-20240229"


class ClaudeHaikuAgent(AnthropicAPIAgent):
    model_name = "claude-3-haiku-20240307"
