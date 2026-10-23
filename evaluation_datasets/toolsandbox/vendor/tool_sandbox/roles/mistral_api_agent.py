# For licensing see accompanying LICENSE file.
# Copyright (C) 2024 Apple Inc. All Rights Reserved.
"""Implementation for Mistral Agent Role with OpenAI API"""

import json
import logging
import os
import uuid
from pathlib import Path
from typing import Any, Iterable, Literal, Optional, Union, cast

from huggingface_hub import snapshot_download  # type: ignore
from openai import NOT_GIVEN, NotGiven, OpenAI
from openai.types.chat import ChatCompletion, ChatCompletionToolParam
from openai.types.chat.chat_completion import Choice
from openai.types.chat.chat_completion_message import ChatCompletionMessage
from openai.types.chat.chat_completion_message_tool_call import (
    ChatCompletionMessageToolCall,
    Function,
)
from openai.types.completion import Completion
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
from tool_sandbox.common.utils import all_logging_disabled
from tool_sandbox.roles.base_role import BaseRole
from tool_sandbox.roles.mistral_tool_utils import (
    AssistantMessage,
    AssistantMessageType,
    ChatCompletionRequest,
    MistralTokenizer,
    SystemMessage,
    SystemMessageType,
    TokenizedType,
    Tool,
    ToolMessage,
    ToolMessageType,
    UserMessage,
    UserMessageType,
)
from tool_sandbox.roles.mistral_tool_utils import Function as MistralFunction

PROMPT_TEMPLATE_MISTRAL_TOOL_CALL = "[TOOL_CALLS]"
MISTRAL_PATH = Path.home().joinpath("mistral_models", "7B-Instruct-v0.3")
MISTRAL_TOKENIZER_PATH = MISTRAL_PATH.joinpath("tokenizer.model.v3")


def generate_valid_tool_call_id() -> str:
    """Generate valid tool call id of length 9 by uuid"""
    return str(uuid.uuid4())[-9:]


def parse_assistant_content_mistral(content: str) -> dict[str, Any]:
    """Parse assistant content and extract tool calls.
    Example tool call content:
        content = '[TOOL_CALLS] [{"name": "get_cellular_service_status",
                    "arguments": {}}]\n\nPlease wait while the system checks your cellular service status.\n
                    \n[status]\n
                    \n[if status == \'on\']\n
                    Your cellular service is currently active.\n\n[elseif status == \'off\']\n
                    Your cellular service is currently inactive. Please check your device settings or contact your service provider.\n
                    \n[else]\nUnable to determine your cellular service status. Please verify your network connection and try again.\n
                    \n
                    [endif]'
    """
    if PROMPT_TEMPLATE_MISTRAL_TOOL_CALL not in content:
        return {"content": content}
    match = content.split(PROMPT_TEMPLATE_MISTRAL_TOOL_CALL)[1:]
    tool_calls = []
    match_str = match[0].strip()
    json_end_idx = match_str.find("]") + 1
    json_part = match_str[:json_end_idx]
    tool_call = json.loads(json_part)
    for tc in tool_call:
        if tc.get("name") is None:
            logging.error(f"Unable to find name in {tc}")
            return {"content": content}
        if tc.get("arguments") is None:
            logging.error(f"Unable to find arguments in {tc}")
            return {"content": content}
        curr_function = Function(
            name=tc["name"],
            arguments=json.dumps(tc["arguments"]),
        )
        curr_tool_call = ChatCompletionMessageToolCall(
            id=tc["name"],
            type="function",
            function=curr_function,
        )
        tool_calls.append(curr_tool_call)
    return {"content": "", "tool_calls": tool_calls}


def completion_to_chat_completion(response: Completion) -> ChatCompletion:
    """Convert Open AI Completion response to ChatCompletion response"""
    assert response.choices[0].text is not None
    parsed_messages = parse_assistant_content_mistral(content=response.choices[0].text)
    completion_response = ChatCompletion(
        id=response.id,
        choices=[
            Choice(
                finish_reason=response.choices[0].finish_reason,
                index=response.choices[0].index,
                message=ChatCompletionMessage(
                    **parsed_messages,
                    role="assistant",
                ),
            )
        ],
        created=response.created,
        model=response.model,
        object="chat.completion",
    )
    return completion_response


def to_mistral_tool(tool: dict[str, Any]) -> Tool:
    """Convert open ai tool to mistral tool"""
    function = tool["function"]
    name = function["name"]
    description = function["description"]
    parameters = function["parameters"]
    return Tool(
        function=MistralFunction(
            name=name,
            description=description,
            parameters=parameters,
        )
    )


def to_mistral_message(
    message: dict[str, Any],
) -> Union[AssistantMessage, UserMessage, SystemMessage, ToolMessage]:
    """Convert open ai message to mistral message"""
    if message["role"] == "assistant":
        assistant_message = {}
        if "content" in message:
            assistant_message["content"] = message["content"]
        if "tool_calls" in message:
            for tc in message["tool_calls"]:
                tc["id"] = generate_valid_tool_call_id()
            assistant_message["tool_calls"] = message["tool_calls"]
        return AssistantMessage(**assistant_message)
    if message["role"] == "user":
        return UserMessage(content=message["content"])
    if message["role"] == "system":
        return SystemMessage(content=message["content"])
    if message["role"] == "tool" or message["role"] == "function":
        return ToolMessage(
            content=message["content"],
            tool_call_id=generate_valid_tool_call_id(),
        )
    logging.error(f"Unrecognized role in message: {message}")
    return UserMessage(content=message["content"])


def create_mistral_chat_prompt(
    tokenizer: MistralTokenizer[
        UserMessageType,
        AssistantMessageType,
        ToolMessageType,
        SystemMessageType,
        TokenizedType,
    ],
    messages: list[dict[str, Any]],
    tools: Optional[list[dict[str, Any]]] = None,
) -> str:
    """Process messages requests to mistral prompt for model inference.
    Args:
        tokenizer: Mistral Tokenizer
        messages (list[dict[str, Any]]): OpenAI request messages.
        tools (list[dict[str, Any]]): OpenAI request tools.

    Returns:
        processed mistral prompt.
    """
    mistral_tools = [] if tools is None else [to_mistral_tool(tool) for tool in tools]
    mistral_messages = [to_mistral_message(message) for message in messages]
    completion_request = ChatCompletionRequest(
        tools=mistral_tools,
        messages=mistral_messages,
    )
    encode_chat_completion = tokenizer.encode_chat_completion(completion_request)
    text = encode_chat_completion.text
    assert text is not None
    ## We use [3:] to skip <s> in the start.
    return text[3:]


class MistralAgent(BaseRole):
    """Agent role for mistral model that conforms to OpenAI tool use API"""

    role_type: RoleType = RoleType.AGENT
    model_name: str

    def __init__(self) -> None:
        super().__init__()
        self.openai_client: OpenAI = OpenAI(api_key="EMPTY")

        MISTRAL_PATH.mkdir(parents=True, exist_ok=True)
        if not MISTRAL_TOKENIZER_PATH.exists():
            hf_token = os.environ.get("HF_TOKEN")
            assert (
                hf_token is not None
            ), "`HF_TOKEN` must be set to your Hugging Face token."
            snapshot_download(
                repo_id="mistralai/Mistral-7B-Instruct-v0.3",
                allow_patterns=["tokenizer.model.v3"],
                local_dir=MISTRAL_PATH,
                token=hf_token,
            )
        self.mistral_tokenizer = MistralTokenizer.from_file(
            f"{MISTRAL_PATH}/tokenizer.model.v3"
        )

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
        response = self.model_inference(
            openai_messages=openai_messages, openai_tools=openai_tools
        )
        # Parse response
        openai_response_message = response.choices[0].message
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
    ) -> ChatCompletion:
        """Run OpenAI model inference

        Args:
            openai_messages:    List of OpenAI API format messages
            openai_tools:       List of OpenAI API format tools definition

        Returns:
            OpenAI API chat completion object
        """
        with all_logging_disabled():
            prompt = create_mistral_chat_prompt(
                tokenizer=self.mistral_tokenizer,
                messages=openai_messages,  # type: ignore
                tools=openai_tools,  # type: ignore
            )
            response = self.openai_client.completions.create(
                model=self.model_name,
                prompt=prompt,
                max_tokens=1024,
                temperature=0.0,
            )
            completion_response = completion_to_chat_completion(response=response)
            return completion_response


class MistralOpenAIServerAgent(MistralAgent):
    """Agent using model hosted through an OpenAI API compatible server using vLLM."""

    def __init__(self, model_name: str) -> None:
        super().__init__()
        self.model_name = model_name

        assert (
            "OPENAI_BASE_URL" in os.environ
        ), "The `OPENAI_BASE_URL` environment variable must be set."
        self.openai_client: OpenAI = OpenAI(api_key="EMPTY")

        # Monkey patch self.openai_client.chat.completions.create with pre and post
        # processing specific to vLLM hosted Mistral model.
        create_api = self.openai_client.completions.create

        def patched_create(
            model: str,
            messages: list[dict[str, Any]],
            tools: Optional[list[dict[str, Any]]],
        ) -> ChatCompletion:
            """Add preprocessing ingesting tools into system prompt
            Add postprocessing to parse function call response

            Args:
                model:      Model name
                messages:   OpenAI compatible messages
                tools:      OpenAI compatible tools

            Returns:
                OpenAI compatible response object
            """
            prompt = create_mistral_chat_prompt(
                tokenizer=self.mistral_tokenizer, messages=messages, tools=tools
            )
            response = create_api(
                model=model, prompt=prompt, max_tokens=1024, temperature=0.0
            )
            assert response.choices[0].text is not None
            completion_response = completion_to_chat_completion(response=response)
            return completion_response

        self.openai_client.chat.completions.create = patched_create  # type: ignore
