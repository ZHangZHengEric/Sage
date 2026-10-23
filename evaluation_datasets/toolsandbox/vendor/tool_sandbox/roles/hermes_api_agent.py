# For licensing see accompanying LICENSE file.
# Copyright (C) 2024 Apple Inc. All Rights Reserved.
"""Agent role for Hermes model.

Ref: https://github.com/NousResearch/Hermes-Function-Calling
"""

import copy
import json
import os
from typing import Any, Literal, Optional, Union, cast

import yaml
from openai import NOT_GIVEN, NotGiven, OpenAI
from openai.types.chat import ChatCompletionToolParam
from openai.types.chat.chat_completion import ChatCompletion, Choice
from openai.types.chat.chat_completion_message import ChatCompletionMessage
from openai.types.chat.chat_completion_message_tool_call import (
    ChatCompletionMessageToolCall,
    Function,
)
from openai.types.completion import Completion
from openai.types.completion_choice import CompletionChoice
from requests.exceptions import HTTPError
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_random_exponential,
)

from tool_sandbox.common.execution_context import RoleType, get_current_context
from tool_sandbox.common.message_conversion import (
    Message,
    openai_tool_call_to_python_code,
    to_openai_messages,
)
from tool_sandbox.common.tool_conversion import convert_to_openai_tools
from tool_sandbox.roles.base_role import BaseRole

ims_token = "<|im_start|>"
ime_token = "<|im_end|>"
tcs_token = "<tool_call>"
tce_token = "</tool_call>"
trs_token = "<tool_response>"
tre_token = "</tool_response>"
ts_token = "<tools>"
te_token = "</tools>"
system_role_token = "system"
user_role_token = "user"
assistent_role_token = "assistant"
tool_role_token = "tool"
role_tokens = [
    system_role_token,
    user_role_token,
    assistent_role_token,
    tool_role_token,
]


def _extract_tools_string(tools: list[ChatCompletionToolParam]) -> str:
    return json.dumps(tools[0] if len(tools) == 1 else tools)


def _create_system_message(prompt_templates: dict[str, str], tools: str) -> str:
    system_prompt = ""
    system_prompt += (
        prompt_templates["system"].format(**{"tools": tools}).strip().replace("\n", " ")
        + "\n"
    )
    system_prompt += prompt_templates["system_tool_call_example"].strip()

    return system_prompt


def _create_instruct_message(content: str, role: str) -> str:
    assert role in role_tokens, f"Unexpected role: {role}"
    return ims_token + role + "\n" + content + ime_token + "\n"


def _create_tool_result_message(
    message: dict[
        Literal["role", "content", "tool_call_id", "name", "tool_calls"],
        Any,
    ],
) -> str:
    content = message.get("content")
    if content is None:
        result_content = ""
    else:
        try:
            result_content = json.loads(content)
        except json.decoder.JSONDecodeError:
            # Still return the content even if it is not a json string.
            result_content = content
    result_dict = {"name": message["name"], "content": result_content}
    content = trs_token + "\n" + json.dumps(result_dict) + "\n" + tre_token
    return _create_instruct_message(content, "tool")


def _create_assistant_message(
    message: dict[
        Literal["role", "content", "tool_call_id", "name", "tool_calls"],
        Any,
    ],
) -> str:
    if "tool_calls" in message:
        content = ""
        for idx, tc in enumerate(message["tool_calls"]):
            ff = copy.deepcopy(tc["function"])
            if "arguments" in ff and isinstance(ff["arguments"], str):
                ff["arguments"] = json.loads(ff["arguments"])
            content += tcs_token + "\n" + json.dumps(ff) + "\n" + tce_token
            if idx + 1 < len(message["tool_calls"]):
                content += "\n"
        return _create_instruct_message(content, "assistant")
    return _create_instruct_message(message["content"], "assistant")


def _convert_request_message(
    message: dict[
        Literal["role", "content", "tool_call_id", "name", "tool_calls"],
        Any,
    ],
) -> str:
    if message["role"] == "tool":
        return _create_tool_result_message(message)
    if message["role"] == "assistant":
        return _create_assistant_message(message)
    return _create_instruct_message(message["content"], message["role"])


def _create_prompt(
    prompt_templates: dict[str, str],
    openai_messages: list[
        dict[
            Literal["role", "content", "tool_call_id", "name", "tool_calls"],
            Any,
        ]
    ],
    openai_tools: list[ChatCompletionToolParam],
    add_generation_token: bool,
) -> str:
    """Creates completion prompt for hermes from a given request

    Args:
        prompt_templates: The predefined prompt templates
        request: The request
        add_generation_token: A flag to denote if the generation triggering token should be
                              added.

    Returns:
        The prompt to query the hermes model.
    """
    prompt = ""

    tools = _extract_tools_string(openai_tools)
    system_msg = _create_system_message(prompt_templates, tools)
    prompt += _create_instruct_message(system_msg, system_role_token)

    for m in openai_messages:
        prompt += _convert_request_message(m)

    if add_generation_token:
        prompt += ims_token + assistent_role_token + "\n"

    return prompt


def to_chat_completion_message(choice: CompletionChoice) -> ChatCompletionMessage:
    """Parses the response text and construct a chat completion message including the tool calls
    from the response.

    Args:
        text:

    Returns:
        A chat completion message containing the tool calls."""

    def _convert_tool(tool: dict[str, Any], idx: int) -> ChatCompletionMessageToolCall:
        function = Function(name=tool["name"], arguments=json.dumps(tool["arguments"]))
        return ChatCompletionMessageToolCall(
            id=f"call_{idx}", function=function, type="function"
        )

    text = choice.text

    cur = 0
    tool_calls = []
    while True:
        i1 = text.find(tcs_token, cur)
        if i1 == -1:
            break
        start = i1 + len(tcs_token)
        i2 = text.find(tce_token, start)
        if i2 == -1:
            raise ValueError(f"No end token {tce_token} found.")
        assert i2 != -1
        cur = i2 + len(tce_token)
        try:
            tool_calls.append(json.loads(text[start:i2]))
        except json.JSONDecodeError as e:
            raise RuntimeError(f"'{text[start:i2]}' is not valid JSON") from e
    content = ""
    if not tool_calls and text:
        content = text

    tool_calls = [_convert_tool(t, idx) for idx, t in enumerate(tool_calls, start=1)]
    return ChatCompletionMessage(
        role="assistant", content=content, tool_calls=tool_calls
    )


def completion_to_chat_completion(response: Completion) -> ChatCompletion:
    """Convert the `Completion` to a `ChatCompletion` object with tool calls."""
    assert (
        len(response.choices) > 0
    ), f"The `choices` list of the response must not be empty:\n{response}"
    assert len(response.choices) == 1, (
        f"Only a single choice is currently supported but got {len(response.choices)}:"
        f"\n{response}"
    )
    choices = [
        Choice(
            finish_reason=response.choices[0].finish_reason,
            index=response.choices[0].index,
            message=to_chat_completion_message(choice),
        )
        for choice in response.choices
    ]
    completion_response = ChatCompletion(
        id=response.id,
        choices=choices,
        created=response.created,
        model=response.model,
        object="chat.completion",
    )
    return completion_response


class HermesAPIAgent(BaseRole):
    """Agent role for Hermes."""

    role_type: RoleType = RoleType.AGENT
    model_name: str

    def __init__(self, model_name: str) -> None:
        super().__init__()

        self.model_name = model_name
        assert (
            "OPENAI_BASE_URL" in os.environ
        ), "The `OPENAI_BASE_URL` environment variable must be set."
        self.client = OpenAI(api_key="EMPTY")

        prompts_file = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "hermes_prompts.yaml",
        )
        with open(prompts_file, "r", encoding="utf-8") as file:
            self.prompt_templates = yaml.safe_load(file)

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
        response_messages: list[Message] = []
        self.messages_validation(messages=messages)
        # Keeps only relevant messages
        messages = self.filter_messages(messages=messages)
        # Does not respond to System
        if messages[-1].sender == RoleType.SYSTEM:
            return
        # Get OpenAI tools if most recent message is from user
        available_tools = self.get_available_tools()
        available_tool_names = set(available_tools.keys())
        openai_tools = (
            convert_to_openai_tools(available_tools)
            if messages[-1].sender == RoleType.USER
            or messages[-1].sender == RoleType.EXECUTION_ENVIRONMENT
            else NOT_GIVEN
        )
        # We need a cast here since `convert_to_openai_tool` returns a plain dict, but
        # `ChatCompletionToolParam` is a `TypedDict`.
        openai_tools = cast(
            Union[list[ChatCompletionToolParam], NotGiven],
            openai_tools,
        )
        # Convert to OpenAI messages.
        current_context = get_current_context()
        openai_messages, _ = to_openai_messages(messages)
        # Call model
        hermes_response = self.model_inference(
            openai_messages=openai_messages, openai_tools=openai_tools
        )

        # Parse response
        openai_response = completion_to_chat_completion(hermes_response)
        openai_response_message = openai_response.choices[0].message

        # Message contains no tool call, aka addressed to user
        if not openai_response_message.tool_calls:
            assert openai_response_message.content is not None
            response_messages = [
                Message(
                    sender=self.role_type,
                    recipient=RoleType.USER,
                    content=openai_response_message.content,
                )
            ]
        else:
            assert openai_tools is not NOT_GIVEN
            for tool_call in openai_response_message.tool_calls:
                # The response contains the agent facing tool name so we need to get
                # the execution facing tool name when creating the Python code.
                execution_facing_tool_name = (
                    current_context.get_execution_facing_tool_name(
                        tool_call.function.name
                    )
                )
                response_messages.append(
                    Message(
                        sender=self.role_type,
                        recipient=RoleType.EXECUTION_ENVIRONMENT,
                        content=openai_tool_call_to_python_code(
                            tool_call,
                            available_tool_names,
                            execution_facing_tool_name=execution_facing_tool_name,
                        ),
                        openai_tool_call_id=tool_call.id,
                        openai_function_name=tool_call.function.name,
                    )
                )
        self.add_messages(response_messages)

    @retry(
        wait=wait_random_exponential(multiplier=1, max=40),
        stop=stop_after_attempt(3),
        retry=retry_if_exception_type(HTTPError),
    )
    def model_inference(
        self,
        openai_messages: list[
            dict[
                Literal["role", "content", "tool_call_id", "name", "tool_calls"],
                Any,
            ]
        ],
        openai_tools: Union[list[ChatCompletionToolParam], NotGiven],
    ) -> Completion:
        """Run Hermes model inference

        Args:
            openai_messages:    List of OpenAI API format messages
            openai_tools:       List of OpenAI API format tools definition

        Returns:
            OpenAI API chat completion object
        """
        prompt = _create_prompt(
            self.prompt_templates,
            openai_messages=openai_messages,
            openai_tools=openai_tools if openai_tools else [],
            add_generation_token=True,
        )
        hermes_response = self.client.completions.create(
            prompt=prompt,
            model=self.model_name,
            max_tokens=2048,
            temperature=0.0,
        )
        return hermes_response
