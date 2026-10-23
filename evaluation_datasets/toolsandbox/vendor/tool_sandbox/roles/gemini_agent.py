# For licensing see accompanying LICENSE file.
# Copyright (C) 2024 Apple Inc. All Rights Reserved.
"""Agent role for the Gemini model."""

import os
import uuid
from typing import Any, Callable, List, Optional, Sequence

# Mypy thinks that the `vertexai` module does not have type hints:
# Skipping analyzing "vertexai": module is installed, but missing library stubs or py.typed marker
import vertexai  # type: ignore
from google.api_core.exceptions import InternalServerError
from requests.exceptions import HTTPError
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_random_exponential,
)
from vertexai import generative_models

from tool_sandbox.common.execution_context import RoleType, get_current_context
from tool_sandbox.common.message_conversion import Message
from tool_sandbox.common.tool_conversion import convert_to_openai_tools
from tool_sandbox.roles.base_role import BaseRole


def gemini_tools_from_functions(
    tool_functions: list[Callable[..., Any]],
) -> list[generative_models.Tool]:
    """Convert a list of tool functions to the Gemini tool format.

    Args:
      tool_functions: A list of functions that are considered tools
    Returns:
      A `Tool` object that can be forwarded to the Gemini constructor or chat calls.
    """
    return [
        generative_models.Tool(
            [
                generative_models.FunctionDeclaration.from_func(fn)
                for fn in tool_functions
            ]
        )
    ]


def gemini_tools_from_openai_tools(
    openai_tools: list[dict[str, Any]],
) -> list[generative_models.Tool]:
    """Convert a list of OpenAI style tools to Gemini tools format.

    Args:
      openai_tools: A list of OpenAI format tools.
    Returns:
      A list of `Tool` objects that can be forwarded to the Gemini constructor or chat calls.

    Note: the API doc
    https://cloud.google.com/python/docs/reference/aiplatform/latest/vertexai.generative_models.Tool
    suggests that multiple `Tool`s can be passed (as a list) to model.generate_content(), but that
    didn't seem to work at the time of testing, instead all `FunctionDeclaration`s are collected in
    a list passed to `Tool` and then that `Tool` as single item in the list forwarded to
    generate_content(). This might be just a limitation of 'gemini-1.0-pro'.
    """
    function_declarations = [
        generative_models.FunctionDeclaration(
            name=tool["function"]["name"],
            description=tool["function"]["description"].replace("\n", " "),
            parameters={
                "type": "object",
                "properties": {
                    param_name: {
                        # The type and/or description may be missing when tool
                        # schema augmentations are enabled.
                        "type": param.get("type", "object"),
                        "description": param.get("description", "No description."),
                    }
                    for param_name, param in tool["function"]["parameters"][
                        "properties"
                    ].items()
                },
                "required": tool["function"]["parameters"]["required"],
            },
        )
        for tool in openai_tools
    ]
    # The single tool contains all function declarations of the available tools.
    return [generative_models.Tool(function_declarations)]


def extract_system_prompt_parts(
    messages: Sequence[Message],
) -> Optional[list[generative_models.Part]]:
    """Extract the system prompt from the given messages."""
    system_messages = [
        message for message in messages if message.sender == RoleType.SYSTEM
    ]
    if len(system_messages) == 0:
        return None

    return [
        generative_models.Part.from_text(system_message.content)
        for system_message in system_messages
    ]


class GeminiAgent(BaseRole):
    """Agent role for a Gemini model with tool use.

    API doc: https://cloud.google.com/python/docs/reference/aiplatform/latest/vertexai.generative_models
    """

    role_type: RoleType = RoleType.AGENT

    def __init__(self, model_name: str = "gemini-1.5-pro-preview-0409"):
        """Gemini agent.
        Args:
          model_name: The model name to use.
        """
        assert (
            "GOOGLE_CLOUD_PROJECT" in os.environ or "CLOUD_ML_PROJECT_ID" in os.environ
        ), (
            "The `GOOGLE_CLOUD_PROJECT` or `CLOUD_ML_PROJECT_ID` environment variable "
            "must be set for specifying the project."
        )
        assert "GOOGLE_CLOUD_REGION" in os.environ or "CLOUD_ML_REGION" in os.environ, (
            "The `GOOGLE_CLOUD_REGION` or `CLOUD_ML_REGION` environment variable "
            "must be set for specifying the location."
        )
        vertexai.init()
        self.model_name = model_name
        # Make the behavior of the model as deterministic as possible.
        self.generation_config = generative_models.GenerationConfig(
            temperature=0.0, top_k=1, candidate_count=1
        )
        self.reset()

    def reset(self) -> None:
        """Reset any state of the agent."""
        self.model: Optional[generative_models.GenerativeModel] = None
        self.chat: Optional[generative_models.ChatSession] = None

    def gemini_response_to_tool_sandbox_messages(
        self, response: generative_models.GenerationResponse
    ) -> list[Message]:
        # Parse model response and convert into a sandbox message.
        assert len(response.candidates) == 1, (
            f"Response contains {len(response.candidates)} candidates, but only a "
            f"single one is supported. Response:\n{response}"
        )
        candidate = response.candidates[0]

        # Similar to the Anthropic models Gemini sometimes returns a response with two
        # parts: the first being a text explaining the model's reasoning and the second
        # being a tool use. Below is an example response for the
        # `send_message_with_contact_content_cellular_off_10_distraction_tools`
        # scenario:
        #   parts {
        #     text: "I can do that. I\'ll first need to search for Fredrik Thordendal\'s contact information. \n\n"
        #   }
        #   parts {
        #     function_call {
        #       name: "search_contacts"
        #       args {
        #         fields {
        #           key: "name"
        #           value {
        #             string_value: "Fredrik Thordendal"
        #           }
        #         }
        #       }
        #     }
        #   }
        # The `vertexai` API itself does not handle multi-part responses. Accessing
        # `response.text` raises this exception:
        #   ValueError: Multiple content parts are not supported.
        # Similar to the Anthropic API if there are function calls we are going to
        # ignore the text. Note that unlike the Anthropic API there is no explicit tool
        # use stop reason so instead we just check if there are any function calls in
        # the response.
        function_call_parts = [
            part for part in candidate.content.parts if part.function_call
        ]
        if len(function_call_parts) > 0:
            # Note that `function_call` is using the agent facing tool names so we need
            # to get the execution facing tool name.
            current_context = get_current_context()
            return [
                Message(
                    sender=self.role_type,
                    recipient=RoleType.EXECUTION_ENVIRONMENT,
                    content=self.gemini_tool_call_to_python_code(
                        function_name=current_context.get_execution_facing_tool_name(
                            part.function_call.name
                        ),
                        part=part,
                    ),
                    openai_function_name=part.function_call.name,
                    # Unlike OpenAI and Anthropic the Gemini API has no concept of tool
                    # use IDs since Gemini keeps track of the conversation history on
                    # the server side. To keep things similar we just make up an ID
                    # here.
                    openai_tool_call_id=str(uuid.uuid4()),
                )
                for part in function_call_parts
            ]

        # Message contains no tool call, therefore is addressed to the user.
        return [
            Message(
                sender=self.role_type, recipient=RoleType.USER, content=response.text
            )
        ]

    def _initialize_chat_session(self, messages: Sequence[Message]) -> None:
        """Initialize a chat session.

        In the `vertexai` API the system prompt is not a regular message, but an
        explicit argument of the `GenerativeModel` constructor. In the tool sandbox
        however system prompts are regular messages. We do not have access to them when
        constructing the `GeminiAgent`. This means we need to delay initialization until
        we have received a system prompt message.
        """
        assert self.model is None
        assert self.chat is None

        # In theory, one could use the `history` argument of `self.model.start_chat` to
        # provide few-shot examples visible to the LLM, but we do not support that. The
        # assumption here is that we have at most one message from a sender other than
        # the system role and if present, it is the final message (which is being
        # processed in the `respond` function and not here).
        non_system_messages = [
            message for message in messages if message.sender != RoleType.SYSTEM
        ]
        assert len(non_system_messages) <= 1, (
            "Initializing the chat session with a history is not supported. Expected "
            f"to have at most one message from a sender other than {RoleType.SYSTEM} "
            f"but got {len(non_system_messages)}. Non-system role messages:\n"
            f"{non_system_messages}"
        )
        if len(non_system_messages) > 0:
            assert messages[-1].sender != RoleType.SYSTEM, (
                f"The only message with a sender other than {RoleType.SYSTEM} must be "
                f"the final message. Messages:\n{messages}"
            )

        system_prompt_parts = extract_system_prompt_parts(messages)
        self.model = generative_models.GenerativeModel(
            model_name=self.model_name,
            generation_config=self.generation_config,
            system_instruction=system_prompt_parts,
        )

        # Start a new chat with disabled response validation to avoid blocked model
        # responses.
        self.chat = self.model.start_chat(response_validation=False)

    def respond(self, ending_index: Optional[int] = None) -> None:
        """Reads a List of messages and attempt to respond with a Message.

        Specifically, interprets system, user, execution environment messages and sends out NL
        response to user, or code snippet to execution environment.

        Message comes from current context, the last k messages should be directed to this role type
        Response are written to current context as well. Handles a single message at a time.

        Args:
            ending_index:   Optional index. Will respond to message located at ending_index instead
                            of most recent one if provided. Utility for processing system message,
                            which could contain multiple entries before each was responded to.

        Raises:
            KeyError:   When the last message is not directed to this role
        """
        messages: list[Message] = self.get_messages(ending_index=ending_index)
        self.messages_validation(messages=messages)
        # Keeps only relevant messages
        messages = self.filter_messages(messages=messages)

        if self.model is None:
            assert self.chat is None
            self._initialize_chat_session(messages)
        assert self.model is not None and self.chat is not None

        if messages[-1].sender == RoleType.SYSTEM:
            # Do not respond to messages sent by the system role.
            return

        # Get tools if most recent message is from user
        available_tools = self.get_available_tools()
        openai_tools = (
            convert_to_openai_tools(available_tools)
            if messages[-1].sender == RoleType.USER
            or messages[-1].sender == RoleType.EXECUTION_ENVIRONMENT
            else []
        )
        # Note: this simpler call currently doesn't work will all local tools.
        # gemini_tools = gemini_tools_from_functions(available_tools.values())
        # Detour over openai_tools structure.
        gemini_tools = gemini_tools_from_openai_tools(openai_tools)

        # Convert internal messages to Gemini messages.
        gemini_messages = self.to_gemini_messages(messages=messages)

        # Call model.
        response = self.model_inference(
            gemini_messages=gemini_messages[-1], gemini_tools=gemini_tools
        )

        response_messages = self.gemini_response_to_tool_sandbox_messages(response)
        self.add_messages(response_messages)

    @retry(
        wait=wait_random_exponential(multiplier=1, max=40),
        stop=stop_after_attempt(3),
        retry=retry_if_exception_type((HTTPError, InternalServerError)),
    )
    def model_inference(
        self,
        gemini_messages: list[generative_models.Content],
        gemini_tools: Optional[list[generative_models.Tool]] = None,
    ) -> generative_models.GenerationResponse:
        """Run Gemini model inference.

        Args:
            gemini_messages:    List of Gemini API format messages.
            gemini_tools:       Optional list of Gemini API format tools.

        Returns:
            Gemini API chat completion object.
        """
        assert self.chat is not None
        return self.chat.send_message(gemini_messages, tools=gemini_tools)

    def to_gemini_messages(
        self, messages: List[Message]
    ) -> list[generative_models.Content]:
        """Converts a list of Tool Sandbox messages to Gemini API messages

        Args:
            messages:   A list of Tool Sandbox messages

        Returns:
            A list of Gemini API messages
        """
        # Unlike the OpenAI and Anthropic APIs Gemini does not use tool use IDs to
        # associate tool use requests with their responses. Instead, Gemini assumes that
        # tool responses are returned in the exact same order as the requests. Gemini
        # supports parallel tool calling, but in the tool sandbox message format there
        # is always one message per tool call. Thus, in `to_gemini_messages` we need to
        # combine tool sandbox messages that are responses to a parallel tool call. So
        # we need to handle two cases here:
        #  1) Gemini requested parallel tool calls
        #  2) Gemini requests tool calls sequentially, i.e. the interaction is
        #     Gemini -> Execution Environment -> Gemini -> Execution Environment ...
        # So when we process a tool response we create a new Gemini message and set
        # `combine_tool_response` to `True`. Now there are two cases:
        #  1) The next tool sandbox message is another tool response and we add it to
        #     the previous Gemini message. This is what happens for parallel tool calls.
        #  2) The next tool sandbox message is from the agent to the execution
        #     environment requesting the next tool call (sequentially). Now we need to
        #     set `combine_tool_response` to `False` since this response was not from a
        #     parallel tool call.
        combine_tool_response = False

        gemini_messages: list[generative_models.Content] = []
        for message in messages:
            if (
                message.sender == RoleType.SYSTEM
                and message.recipient == RoleType.AGENT
            ):
                parts = [generative_models.Part.from_text(message.content)]
                gemini_messages.append(
                    generative_models.Content(role="system", parts=parts)
                )
            elif (
                message.sender == RoleType.USER and message.recipient == RoleType.AGENT
            ):
                parts = [generative_models.Part.from_text(message.content)]
                gemini_messages.append(
                    generative_models.Content(role="user", parts=parts)
                )
            elif (
                message.sender == RoleType.EXECUTION_ENVIRONMENT
                and message.recipient == RoleType.AGENT
            ):
                assert message.openai_function_name is not None, message
                function_response_part = generative_models.Part.from_function_response(
                    name=message.openai_function_name,
                    response={"content": message.content},
                )

                if combine_tool_response:
                    assert len(gemini_messages) > 0, message
                    assert gemini_messages[-1].role == "tool", gemini_messages[-1]
                    assert len(gemini_messages[-1].parts) > 0, gemini_messages[-1]
                    # Note: `gemini_messages[-1].parts.append(function_response_part)`
                    # does not actually change the last message. Probably because
                    # `.parts` returns a view instead of giving access to the raw data.
                    # As a workaround we create a new message.
                    gemini_messages[-1] = generative_models.Content(
                        role="tool",
                        parts=gemini_messages[-1].parts + [function_response_part],
                    )
                else:
                    # Create a new message.
                    gemini_messages.append(
                        generative_models.Content(
                            role="tool",
                            parts=[function_response_part],
                        )
                    )
                    combine_tool_response = True
            elif (
                message.sender == RoleType.AGENT
                and message.recipient == RoleType.EXECUTION_ENVIRONMENT
            ):
                # A tool call request from the agent to the execution environment means
                # that coming tool responses should not be combined with the last tool
                # response. This is only meant for parallel tool calls and we are now
                # issuing a new tool call request.
                combine_tool_response = False
            elif (
                message.sender == RoleType.AGENT and message.recipient == RoleType.USER
            ):
                parts = [generative_models.Part.from_text(message.content)]
                gemini_messages.append(
                    generative_models.Content(role="assistant", parts=parts)
                )
            else:
                raise ValueError(
                    f"Unrecognized sender recipient pair {(message.sender, message.recipient)}"
                )

        return gemini_messages

    def gemini_tool_call_to_python_code(
        self, function_name: str, part: generative_models.Part
    ) -> str:
        """Call a python tool with the parameters from the model response."""

        potentially_scrambled_function_name = part.function_call.name

        # Check if function name is a known allowed tool.
        available_tool_names = self.get_available_tools().keys()
        if potentially_scrambled_function_name not in available_tool_names:
            raise KeyError(
                f"Agent tool call {potentially_scrambled_function_name=} is not a known allowed tool. "
                f"Options are {available_tool_names=}"
            )

        # Extract arguments from function call.
        args = part.to_dict()["function_call"]["args"]
        function_call_code = (
            f"{function_name}_parameters = {args}\n"
            f"{function_name}_response = {function_name}(**{function_name}_parameters)\n"
            f"print(repr({function_name}_response))"
        )
        return function_call_code
