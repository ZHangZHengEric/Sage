# For licensing see accompanying LICENSE file.
# Copyright (C) 2024 Apple Inc. All Rights Reserved.
"""Agent role for the Cohere models hosted as OpenAI compatible servers using vLLM."""

import json
import os
from typing import Any, Iterable, Literal, Optional, Union, cast

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
from transformers import AutoTokenizer  # type: ignore

from tool_sandbox.common.execution_context import RoleType, get_current_context
from tool_sandbox.common.message_conversion import (
    Message,
    openai_tool_call_to_python_code,
    to_openai_messages,
)
from tool_sandbox.common.tool_conversion import convert_to_openai_tools
from tool_sandbox.roles.base_role import BaseRole


def _get_cohere_tokenizer_name(model_name: str) -> str:
    if model_name == "c4ai-command-r-plus":
        return "CohereForAI/c4ai-command-r-plus"
    if model_name == "c4ai-command-r-v01":
        return "CohereForAI/c4ai-command-r-v01"

    raise RuntimeError(
        f"Update the code to select a tokenizer for model '{model_name}'."
    )


def to_cohere_tool(openai_tool: ChatCompletionToolParam) -> dict[str, Any]:
    """Convert OpenAI to Cohere tool format."""
    assert openai_tool["type"] == "function", (
        "Object to convert to Cohere tool format is not a valid OpenAI tool:"
        f"\n{openai_tool}"
    )

    # Cohere uses its own tool format, see https://docs.cohere.com/docs/tool-use#step-1
    # The main differences compared to the OpenAI format are:
    #  - The `parameters` key is called `parameter_definitions`
    #  - Whether or not an argument is required is stored within each entry in the
    #    `parameter_definitions` whereas OpenAI stores this separately from the argument
    #    name, type and documentation.

    openai_function = openai_tool["function"]
    cohere_tool: dict[str, Any] = {
        "name": openai_function["name"],
        "description": openai_function.get("description", "No description available."),
        "parameter_definitions": {},
    }
    openai_properties = cast(
        dict[str, Any], openai_function["parameters"]["properties"]
    )
    for arg_name, arg_properties in openai_properties.items():
        # There are tool augmentations where the argument type and/or description
        # information is being removed.
        is_required = arg_name in cast(
            list[str], openai_function["parameters"]["required"]
        )
        cohere_tool["parameter_definitions"][arg_name] = {
            "description": arg_properties.get(
                "description", "No description available."
            ),
            "type": arg_properties.get("type", "object"),
            "required": is_required,
        }
    return cohere_tool


def create_prompt(
    tokenizer: AutoTokenizer,
    openai_messages: list[
        dict[
            Literal["role", "content", "tool_call_id", "name", "tool_calls"],
            Any,
        ]
    ],
    openai_tools: Union[Iterable[ChatCompletionToolParam], NotGiven],
) -> str:
    """Process request and fill the prompt for Cohere.

    Args:
        request: A OpenAI style request.
    """
    cohere_tools = (
        [to_cohere_tool(tool) for tool in openai_tools] if openai_tools else []
    )

    prompt = tokenizer.apply_tool_use_template(
        conversation=openai_messages,
        tools=cohere_tools,
        tokenize=False,
        add_generation_prompt=True,
    )
    # Since `tokenize==False` the prompt should be of type string.
    assert isinstance(prompt, str), type(prompt)
    # Remove the BOS token since it will be applied by the inference engine.
    assert prompt.startswith(tokenizer.bos_token)
    prompt = prompt[len(tokenizer.bos_token) :]
    return prompt


def to_chat_completion_message(choice: CompletionChoice) -> ChatCompletionMessage:
    def _parse_tools(text: str) -> list[dict[str, Any]]:
        prefix = "Action: ```json"
        suffix = "```"
        is_tool = text.startswith(prefix) and text.endswith(suffix)
        if not is_tool:
            return []

        tool_call_str = text[len(prefix) : len(text) - len(suffix)]
        try:
            return cast(
                list[dict[str, Any]],
                json.loads(tool_call_str),
            )
        except Exception as e:
            raise RuntimeError(
                f"Error parsing tool call string '{tool_call_str}'."
            ) from e

    def _convert_tool(tool: dict[str, Any], idx: int) -> ChatCompletionMessageToolCall:
        function = Function(
            name=tool["tool_name"], arguments=json.dumps(tool["parameters"])
        )
        return ChatCompletionMessageToolCall(
            id=f"call_{idx}", function=function, type="function"
        )

    tool_call_dicts = _parse_tools(choice.text)
    tool_calls = [_convert_tool(t, idx) for idx, t in enumerate(tool_call_dicts)]
    content = choice.text if len(tool_calls) == 0 else ""
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


class CohereAgent(BaseRole):
    """Cohere agent using models hosted as an OpenAI compatible server using vLLM."""

    role_type: RoleType = RoleType.AGENT
    model_name: str

    def __init__(self, model_name: str) -> None:
        super().__init__()

        self.model_name = model_name
        assert (
            "OPENAI_BASE_URL" in os.environ
        ), "The `OPENAI_BASE_URL` environment variable must be set."
        self.client = OpenAI(api_key="EMPTY")

        model_id = _get_cohere_tokenizer_name(self.model_name)
        self.tokenizer = AutoTokenizer.from_pretrained(model_id)

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
            Union[Iterable[ChatCompletionToolParam], NotGiven],
            openai_tools,
        )
        # Convert to OpenAI messages.
        current_context = get_current_context()
        openai_messages, _ = to_openai_messages(messages)
        # Call model
        cohere_response = self.model_inference(
            openai_messages=openai_messages, openai_tools=openai_tools
        )

        # Parse response
        openai_response = completion_to_chat_completion(cohere_response)
        openai_response_message = openai_response.choices[0].message

        # Message contains no tool call, aka addressed to user
        if openai_response_message.tool_calls is None:
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
        openai_tools: Union[Iterable[ChatCompletionToolParam], NotGiven],
    ) -> Completion:
        """Run Cohere model inference.
        Args:
            openai_messages:    List of OpenAI API format messages
            openai_tools:       List of OpenAI API format tools definition
        Returns:
            OpenAI API chat completion object
        """
        prompt = create_prompt(self.tokenizer, openai_messages, openai_tools)
        cohere_response = self.client.completions.create(
            prompt=prompt,
            model=self.model_name,
            max_tokens=1024,
            temperature=0.0,
        )
        return cohere_response
