# For licensing see accompanying LICENSE file.
# Copyright (C) 2024 Apple Inc. All Rights Reserved.
"""Simulated user role for any model that conforms to OpenAI tool use API"""

from logging import getLogger
from typing import Dict, Iterable, List, Literal, Optional, Union, cast

from openai import NOT_GIVEN, NotGiven, OpenAI
from openai.types.chat import (
    ChatCompletion,
    ChatCompletionMessageParam,
    ChatCompletionToolParam,
)
from tenacity import retry, stop_after_attempt, wait_random_exponential

from tool_sandbox.common.execution_context import RoleType
from tool_sandbox.common.message_conversion import (
    Message,
    openai_tool_call_to_python_code,
)
from tool_sandbox.common.tool_conversion import convert_to_openai_tool
from tool_sandbox.common.utils import all_logging_disabled
from tool_sandbox.roles.base_role import BaseRole

LOGGER = getLogger(__name__)


class OpenAIAPIUser(BaseRole):
    """Simulated user role for any model that conforms to OpenAI tool use API"""

    role_type: RoleType = RoleType.USER
    model_name: str

    def __init__(self) -> None:
        # We set the `base_url` explicitly here to avoid picking up the
        # `OPENAI_BASE_URL` environment variable that may be set for serving models as
        # OpenAI API compatible servers.
        self.openai_client: OpenAI = OpenAI(base_url="https://api.openai.com/v1")

    def respond(self, ending_index: Optional[int] = None) -> None:
        """Reads a List of messages and attempt to respond with a Message

        Specifically, interprets system & agent messages, sends out valid followup responses back to agent

        Comparing to agents and execution environments. Users and user simulators have a unique challenge. Agents and
        execution environments passively accept messages from other roles, execute them and respond. However, a user
        has the autonomy to decide when to stop the conversation. It must be able to, otherwise the conversation is
        never going to stop.

        The current idea is to instruct the user simulator to issue structured responses indicating end of conversation,
        1 such approach could be, we offer a tool to user simulator. The simulator could issue
        tool call to in order to terminate the conversation. This will be interpreted, and sent to execution env to
        execute.

        Args:
            ending_index:   Optional index. Will respond to message located at ending_index instead of most recent one
                            if provided. Utility for processing system message, which could contain multiple entries
                            before each was responded to

        Raises:
            KeyError:   When the last message is not directed to this role
        """
        messages: List[Message] = self.get_messages(ending_index=ending_index)
        response_messages: List[Message] = []
        self.messages_validation(messages=messages)
        # Keeps only relevant messages
        messages = self.filter_messages(messages=messages)
        # Does not respond to System
        if messages[-1].sender == RoleType.SYSTEM:
            return
        # Get OpenAI tools if most recent turn is from Agent (again, to terminate the conversation if needed)
        available_tools = self.get_available_tools()
        available_tool_names = set(available_tools.keys())
        openai_tools = (
            [convert_to_openai_tool(tool) for tool in available_tools.values()]
            if messages[-1].sender == RoleType.AGENT
            else NOT_GIVEN
        )
        # We need a cast here since `convert_to_openai_tool` returns a plain dict, but
        # `ChatCompletionToolParam` is a `TypedDict`.
        openai_tools = cast(
            Union[Iterable[ChatCompletionToolParam], NotGiven],
            openai_tools,
        )
        # Convert to OpenAI messages
        openai_messages = self.to_openai_messages(messages=messages)
        # Call model
        response = self.model_inference(
            openai_messages=openai_messages, openai_tools=openai_tools
        )
        # Parse response
        openai_response_message = response.choices[0].message

        # Message contains no tool call, aka addressed to agent
        if openai_response_message.tool_calls is None:
            # Not sure why the content field `ChatCompletionMessage` has a type of
            # `str | None`.
            assert openai_response_message.content is not None
            response_messages = [
                Message(
                    sender=self.role_type,
                    recipient=RoleType.AGENT,
                    content=openai_response_message.content,
                )
            ]
        else:
            assert openai_tools is not NOT_GIVEN
            for tool_call in openai_response_message.tool_calls:
                response_messages.append(
                    Message(
                        sender=self.role_type,
                        recipient=RoleType.EXECUTION_ENVIRONMENT,
                        content=openai_tool_call_to_python_code(
                            tool_call,
                            available_tool_names,
                            execution_facing_tool_name=None,
                        ),
                    )
                )
        self.add_messages(response_messages)

    @retry(
        wait=wait_random_exponential(multiplier=1, max=40), stop=stop_after_attempt(3)
    )
    def model_inference(
        self,
        openai_messages: list[dict[Literal["role", "content"], str]],
        openai_tools: Union[Iterable[ChatCompletionToolParam], NotGiven],
    ) -> ChatCompletion:
        """Run OpenAI model inference

        Args:
            openai_messages:    List of OpenAI API format messages
            openai_tools:       List of OpenAI API format tools definition

        Returns:
            OpenAI API chat completion object
        """
        with all_logging_disabled():
            return self.openai_client.chat.completions.create(
                model=self.model_name,
                messages=cast(list[ChatCompletionMessageParam], openai_messages),
                tools=openai_tools,
            )

    @staticmethod
    def to_openai_messages(
        messages: List[Message],
    ) -> List[Dict[Literal["role", "content"], str]]:
        """Converts a list of Tool Sandbox messages to OpenAI API messages, from the perspective of a simulated user

        Args:
            messages:   A list of Tool Sandbox messages

        Returns:
            A list of OpenAI API messages
        """
        openai_messages: List[Dict[Literal["role", "content"], str]] = []
        for message in messages:
            if message.sender == RoleType.SYSTEM and message.recipient == RoleType.USER:
                openai_messages.append({"role": "system", "content": message.content})
            elif (
                message.sender == RoleType.AGENT and message.recipient == RoleType.USER
            ):
                # The roles are in reverse
                # We are the user simulator, simulated response from OpenAI assistant role is the simulated user message
                # which means agent dialog is OpenAI user role
                openai_messages.append({"role": "user", "content": message.content})
            elif (
                message.sender == RoleType.USER and message.recipient == RoleType.AGENT
            ):
                openai_messages.append(
                    {"role": "assistant", "content": message.content}
                )
            elif (
                message.sender == RoleType.USER
                and message.recipient == RoleType.EXECUTION_ENVIRONMENT
            ) or (
                message.sender == RoleType.EXECUTION_ENVIRONMENT
                and message.recipient == RoleType.USER
            ):
                # These pairs are ignored.
                pass
            else:
                raise ValueError(
                    f"Unrecognized sender recipient pair {(message.sender, message.recipient)}"
                )
        return openai_messages


class GPT_3_5_0125_User(OpenAIAPIUser):
    model_name = "gpt-3.5-turbo-0125"


class GPT_4_0125_User(OpenAIAPIUser):
    model_name = "gpt-4-0125-preview"


class GPT_4_o_2024_05_13_User(OpenAIAPIUser):
    model_name = "gpt-4o-2024-05-13"
