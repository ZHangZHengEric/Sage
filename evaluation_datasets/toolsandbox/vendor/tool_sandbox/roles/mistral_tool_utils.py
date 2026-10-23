# For licensing see accompanying LICENSE file.
# Copyright (C) 2024 Apple Inc. All Rights Reserved.
"""Utilities for working with tools in the Mistral API.

Adapted from mistral-common >= v1.2.1 , see
https://github.com/mistralai/mistral-common/tree/release-v1.2.1

The reason for copying instead of depending on it is that we are currently pinned to
jsonschema<4.20.0.
"""

import json
import logging
import os
import re
from abc import ABC, abstractmethod
from enum import Enum
from functools import cached_property
from pathlib import Path
from typing import (
    Any,
    Callable,
    Dict,
    Generic,
    List,
    Literal,
    Optional,
    Sequence,
    Set,
    Tuple,
    Type,
    TypeVar,
    Union,
)

from jsonschema import Draft7Validator, SchemaError  # type: ignore
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sentencepiece import SentencePieceProcessor  # type: ignore
from typing_extensions import Annotated, TypeAlias  # compatibility with 3.8


class MistralBase(BaseModel):
    """
    Base class for all Mistral Pydantic models.
    """

    model_config = ConfigDict(
        extra="forbid", validate_default=True, use_enum_values=True
    )


class Function(MistralBase):
    name: str
    description: str = ""
    parameters: Dict[str, Any]


class FunctionCall(MistralBase):
    name: str
    arguments: str

    @field_validator("arguments", mode="before")
    def validate_arguments(cls, v: Union[str, Dict[str, Any]]) -> str:
        """
        This is for backward compatibility
        """
        if isinstance(v, dict):
            return json.dumps(v)
        return v


class ToolTypes(str, Enum):
    function = "function"


class ToolChoice(str, Enum):
    auto: str = "auto"
    none: str = "none"
    any: str = "any"


class ToolCall(MistralBase):
    id: str = "null"  # required for V3 tokenization
    type: ToolTypes = ToolTypes.function
    function: FunctionCall


class Tool(MistralBase):
    type: ToolTypes = ToolTypes.function
    function: Function


class Roles(str, Enum):
    system = "system"
    user = "user"
    assistant = "assistant"
    tool = "tool"


class ChunkTypes(str, Enum):
    text = "text"


class ContentChunk(MistralBase):
    type: ChunkTypes = ChunkTypes.text
    text: str


class BaseMessage(MistralBase):
    role: Literal[Roles.system, Roles.user, Roles.assistant, Roles.tool]


class UserMessage(BaseMessage):
    role: Literal[Roles.user] = Roles.user
    content: Union[str, List[ContentChunk]]


class SystemMessage(BaseMessage):
    role: Literal[Roles.system] = Roles.system
    content: Union[str, List[ContentChunk]]


class AssistantMessage(BaseMessage):
    role: Literal[Roles.assistant] = Roles.assistant
    content: Optional[str] = None
    tool_calls: Optional[List[ToolCall]] = None
    prefix: bool = False


class FinetuningAssistantMessage(AssistantMessage):
    weight: Optional[float] = None


class ToolMessage(BaseMessage):
    content: str
    role: Literal[Roles.tool] = Roles.tool
    tool_call_id: Optional[str] = None

    # Deprecated in V3 tokenization
    name: Optional[str] = None


ChatMessage = Annotated[
    Union[SystemMessage, UserMessage, AssistantMessage, ToolMessage],
    Field(discriminator="role"),
]
ChatMessageType = TypeVar("ChatMessageType", bound=ChatMessage)

# Used for type hinting in generic classes where we might override the message types
UserMessageType = TypeVar("UserMessageType", bound=UserMessage)
AssistantMessageType = TypeVar("AssistantMessageType", bound=AssistantMessage)
ToolMessageType = TypeVar("ToolMessageType", bound=ToolMessage)
SystemMessageType = TypeVar("SystemMessageType", bound=SystemMessage)

UATS: TypeAlias = Union[
    UserMessageType, AssistantMessageType, ToolMessageType, SystemMessageType
]


class BaseCompletionRequest(MistralBase):
    temperature: float = Field(default=0.7, ge=0.0, le=1.0)
    top_p: float = Field(default=1.0, ge=0.0, le=1.0)
    max_tokens: Optional[int] = Field(default=None, ge=0)
    random_seed: Optional[int] = Field(default=None, ge=0)


class ResponseFormats(str, Enum):
    text: str = "text"
    json: str = "json_object"


class ResponseFormat(MistralBase):
    type: ResponseFormats = ResponseFormats.text


class ChatCompletionRequest(BaseCompletionRequest, Generic[ChatMessageType]):
    model: Optional[str] = None
    messages: List[ChatMessageType]
    response_format: ResponseFormat = Field(default_factory=ResponseFormat)
    tools: Optional[List[Tool]] = None
    tool_choice: ToolChoice = ToolChoice.auto


class Tokenizer(ABC):
    @property
    @abstractmethod
    def n_words(self) -> int:
        """Vocabulary size"""

    @abstractmethod
    def vocab(self) -> List[str]:
        """All tokens in the vocabulary as strings"""

    @property
    @abstractmethod
    def bos_id(self) -> int:
        """id of the Beginning of String token"""

    @property
    @abstractmethod
    def eos_id(self) -> int:
        """id of the End of String token"""

    @abstractmethod
    def encode(self, s: str, bos: bool, eos: bool) -> List[int]:
        """String to token ids"""

    @abstractmethod
    def decode(self, t: List[int]) -> str:
        """Token ids to string"""

    @abstractmethod
    def get_control_token(self, s: str) -> int:
        """Get the id of a control token"""

    @abstractmethod
    def to_string(self, tokens: List[int]) -> str:
        """Convert token ids to string"""


class MistralCommonException(Exception):
    message: str = "Internal server error"

    def __init__(
        self,
        message: Optional[str] = None,
    ) -> None:
        if message:
            self.message = message


class TokenizerException(MistralCommonException):
    def __init__(self, message: str) -> None:
        super().__init__(message)


class UnsupportedTokenizerFeatureException(MistralCommonException):
    def __init__(self, message: str) -> None:
        super().__init__(message)


class InvalidRequestException(MistralCommonException):
    def __init__(self, message: str) -> None:
        super().__init__(message)


class InvalidSystemPromptException(MistralCommonException):
    def __init__(self, message: str) -> None:
        super().__init__(message)


class InvalidMessageStructureException(MistralCommonException):
    def __init__(self, message: str) -> None:
        super().__init__(message)


class InvalidAssistantMessageException(MistralCommonException):
    def __init__(self, message: str) -> None:
        super().__init__(message)


class InvalidToolMessageException(MistralCommonException):
    def __init__(self, message: str) -> None:
        super().__init__(message)


class InvalidToolSchemaException(MistralCommonException):
    def __init__(self, message: str) -> None:
        super().__init__(message)


class InvalidUserMessageException(MistralCommonException):
    def __init__(self, message: str) -> None:
        super().__init__(message)


class InvalidFunctionCallException(MistralCommonException):
    def __init__(self, message: str) -> None:
        super().__init__(message)


class InvalidToolException(MistralCommonException):
    def __init__(self, message: str) -> None:
        super().__init__(message)


class Tokenized(MistralBase):
    """
    A tokenized InstructRequest
    """

    tokens: List[int]
    text: Optional[str] = None
    prefix_ids: Optional[List[int]] = None


class FIMRequest(MistralBase):
    """
    A valid Fill in the Middle completion request to be tokenized
    """

    prompt: str
    suffix: Optional[str] = None


class InstructRequest(MistralBase, Generic[ChatMessageType, ToolMessageType]):
    """
    A valid request to be tokenized
    """

    messages: List[ChatMessageType]
    system_prompt: Optional[str] = None
    available_tools: Optional[List[ToolMessageType]] = None


InstructRequestType = TypeVar("InstructRequestType", bound=InstructRequest)  # type: ignore
FIMRequestType = TypeVar("FIMRequestType", bound=FIMRequest)
TokenizedType = TypeVar("TokenizedType", bound=Tokenized)


class InstructTokenizer(
    Generic[InstructRequestType, FIMRequestType, TokenizedType, AssistantMessageType]
):
    tokenizer: Tokenizer

    def __init__(self, tokenizer: Tokenizer) -> None:
        """Init from tokenizer"""

    @abstractmethod
    def encode_instruct(self, request: InstructRequestType) -> TokenizedType:
        """Instruct request to Tokenized object"""

    @abstractmethod
    def decode(self, tokens: List[int]) -> str:
        """Convert token ids to string"""

    @abstractmethod
    def encode_fim(self, request: FIMRequestType) -> TokenizedType:
        """FIM request to Tokenized object"""


class ValidationMode(Enum):
    serving = "serving"
    finetuning = "finetuning"
    test = "test"


class MistralRequestValidator(
    Generic[UserMessageType, AssistantMessageType, ToolMessageType, SystemMessageType]
):
    def __init__(self, mode: ValidationMode = ValidationMode.test):
        self._mode = mode

    def validate_messages(self, messages: List[UATS]) -> None:  # type: ignore
        """
        Validates the list of messages
        """
        self._validate_message_list_structure(messages)
        self._validate_message_list_content(messages)

    def validate_request(
        self,
        request: ChatCompletionRequest,  # type: ignore
    ) -> ChatCompletionRequest[UATS]:  # type: ignore
        """
        Validates the request
        """

        if self._mode == ValidationMode.serving:
            if request.model is None:
                raise InvalidRequestException(
                    "Model name parameter is required for serving mode"
                )

        # Validate the messages
        self.validate_messages(request.messages)

        # Validate the tools
        self._validate_tools(request.tools or [])

        return request

    def _validate_function(self, function: Function) -> None:
        """
        Checks:
        - That the function schema is valid
        """
        try:
            Draft7Validator.check_schema(function.parameters)
        except SchemaError as e:
            raise InvalidToolSchemaException(f"Invalid tool schema: {e.message}")

        if not re.match(r"^[a-zA-Z0-9_-]{1,64}$", function.name):
            raise InvalidToolException(
                f"Function name was {function.name} but must be a-z, A-Z, 0-9, "
                "or contain underscores and dashes, with a maximum length of 64."
            )

    def _validate_tools(self, tools: List[Tool]) -> None:
        """
        Checks:
        - That the tool schemas are valid
        """

        for tool in tools:
            self._validate_function(tool.function)

    def _validate_user_message(self, message: UserMessageType) -> None:
        pass

    def _validate_tool_message(self, message: ToolMessageType) -> None:
        """
        Checks:
        - The tool name is valid
        """
        if message.name is not None:
            if not re.match(r"^[a-zA-Z0-9_-]{1,64}$", message.name):
                raise InvalidToolMessageException(
                    f"Function name was {message.name} but must be a-z, A-Z, 0-9, "
                    "or contain underscores and dashes, with a maximum length of 64."
                )

    def _validate_system_message(self, message: SystemMessageType) -> None:
        """
        Checks:
        - That the system prompt has content
        """
        if message.content is None:
            raise InvalidSystemPromptException("System prompt must have content")

    def _validate_function_call(self, function_call: FunctionCall) -> None:
        """
        Checks:
        - That the function call has a valid name
        """
        if not re.match(r"^[a-zA-Z0-9_-]{1,64}$", function_call.name):
            raise InvalidFunctionCallException(
                f"Function name was {function_call.name} but must be a-z, A-Z, 0-9, "
                "or contain underscores and dashes, with a maximum length of 64."
            )

    def _validate_tool_call(self, tool_call: ToolCall, is_last_message: bool) -> None:
        """
        Checks:
        - That the tool call has a valid function
        """

        self._validate_function_call(tool_call.function)

    def _validate_assistant_message(
        self, message: AssistantMessageType, is_last_message: bool = False
    ) -> None:
        """
        Checks:
        - That the assistant message has either text or tool_calls, but not both
        - That the tool calls are valid
        """

        # Validate that the message has either text or tool_calls
        # but not both and not neither.
        if bool(message.content) == bool(message.tool_calls):
            raise InvalidAssistantMessageException(
                "Assistant message must have either content or tool_calls, but not both."
            )

        # If we have tool calls, validate them
        if message.tool_calls is not None:
            # Validate that the tool calls are valid
            for tool_call in message.tool_calls:
                self._validate_tool_call(tool_call, is_last_message=is_last_message)

        if self._mode == ValidationMode.finetuning and isinstance(
            message, FinetuningAssistantMessage
        ):
            if message.weight is not None and message.weight not in [0, 1]:
                raise InvalidAssistantMessageException(
                    "Assistant message weight must be either 0 or 1"
                )

        if message.prefix:
            if not is_last_message:
                raise InvalidAssistantMessageException(
                    "Assistant message with prefix True must be last message"
                )
            # note : we already validate that assistant messsage has content 3 lines up.

    def _validate_tool_calls_followed_by_tool_messages(
        self,
        messages: List[UATS],  # type: ignore
    ) -> None:
        """
        Checks:
        - That the number of tool calls and tool messages are the same
        - That the tool calls are followed by tool messages
        """
        prev_role = None
        expected_tool_messages = 0
        for message in messages:
            if prev_role is None:
                prev_role = message.role
                continue

            if message.role == Roles.tool:
                expected_tool_messages -= 1
            elif message.role == Roles.assistant:
                # if we have an assistant message and we have not recieved all the function calls
                # we need to raise an exception
                if expected_tool_messages != 0:
                    raise InvalidMessageStructureException(
                        "Not the same number of function calls and responses"
                    )

                if message.tool_calls is not None:
                    # Validate that the number of function calls and responses are the same
                    expected_tool_messages = len(message.tool_calls)

            prev_role = message.role

        if expected_tool_messages != 0 and self._mode == ValidationMode.serving:
            raise InvalidMessageStructureException(
                "Not the same number of function calls and responses"
            )
        elif (
            expected_tool_messages not in [0, 1]
            and self._mode == ValidationMode.finetuning
        ):
            # if last assistant message has no tool calls, then same number of tool calls and messages => 0
            # if last assistant message has a tool call we have one more tool call => 1
            raise InvalidMessageStructureException(
                "Too many function calls and too few responses"
            )

    def _validate_message_order(self, messages: List[UATS]) -> None:  # type: ignore
        """
        Validates the order of the messages, for example user -> assistant -> user -> assistant -> ...
        """
        previous_role = None
        for message in messages:
            current_role = message.role

            if previous_role is not None:
                if previous_role == Roles.system:
                    expected_roles = {Roles.user, Roles.assistant, Roles.system}
                elif previous_role == Roles.user:
                    expected_roles = {Roles.assistant, Roles.system, Roles.user}
                elif previous_role == Roles.assistant:
                    expected_roles = {Roles.assistant, Roles.user, Roles.tool}
                elif previous_role == Roles.tool:
                    expected_roles = {Roles.assistant, Roles.tool}

                if current_role not in expected_roles:
                    raise InvalidMessageStructureException(
                        f"Unexpected role '{current_role.value}' after role '{previous_role.value}'"
                    )

            previous_role = current_role

    def _validate_last_message(self, message: UATS) -> None:  # type: ignore
        # The last message must be a user or tool message in serving mode or an assistant message in finetuning mode
        last_message_role = message.role
        if self._mode == ValidationMode.finetuning:
            if last_message_role != Roles.assistant:
                raise InvalidMessageStructureException(
                    f"Expected last role Assistant for finetuning but got {last_message_role.value}"
                )
        else:
            bad_assistant = isinstance(message, AssistantMessage) and not message.prefix
            bad_role = message.role not in {Roles.user, Roles.tool}
            if bad_assistant and bad_role:
                raise InvalidMessageStructureException(
                    f"Expected last role User or Tool (or Assistant with prefix True) for serving"
                    f" but got {last_message_role.value}"
                )

    def _validate_message_list_structure(self, messages: List[UATS]) -> None:  # type: ignore
        """
        Validates the structure of the list of messages

        For example the messages must be in the correct order of user/assistant/tool
        """

        if len(messages) == 0:
            raise InvalidMessageStructureException(
                "Conversation must have at least one message"
            )

        # If we have one message it must be a user or a system message
        if len(messages) == 1:
            if messages[0].role not in {Roles.user, Roles.system}:
                raise InvalidMessageStructureException(
                    "Conversation must start with a user message or system message"
                )
        else:
            self._validate_last_message(messages[-1])

        self._validate_message_order(messages)
        self._validate_tool_calls_followed_by_tool_messages(messages)

    def _validate_message_list_content(self, messages: List[UATS]) -> None:  # type: ignore
        """
        Validates the content of the messages
        """

        for idx, message in enumerate(messages):
            if message.role == Roles.user:
                self._validate_user_message(message)
            elif message.role == Roles.assistant:
                self._validate_assistant_message(
                    message, is_last_message=idx == len(messages) - 1
                )
            elif message.role == Roles.tool:
                self._validate_tool_message(message)
            elif message.role == Roles.system:
                self._validate_system_message(message)
            else:
                raise InvalidRequestException(
                    f"Unsupported message type {type(message)}"
                )


class MistralRequestValidatorV3(MistralRequestValidator):  # type: ignore
    def _validate_tool_message(self, message: ToolMessageType) -> None:
        """
        Checks:
        - The tool name is valid
        - Tool call id is valid
        """
        if message.name is not None:
            if not re.match(r"^[a-zA-Z0-9_-]{1,64}$", message.name):
                raise InvalidToolMessageException(
                    f"Function name was {message.name} but must be a-z, A-Z, 0-9, "
                    "or contain underscores and dashes, with a maximum length of 64."
                )

        if message.tool_call_id is None:
            raise InvalidRequestException("Tool call id has to be defined.")

        if not re.match(r"^[a-zA-Z0-9]{9}$", message.tool_call_id):
            raise InvalidToolMessageException(
                f"Tool call id was {message.tool_call_id} but must be a-z, A-Z, 0-9, with a length of 9."
            )

    def _validate_tool_call(self, tool_call: ToolCall, is_last_message: bool) -> None:
        """
        Validate that the tool call has a valid ID
        """
        if tool_call.id != "null":
            if not re.match(r"^[a-zA-Z0-9]{9}$", tool_call.id):
                raise InvalidFunctionCallException(
                    f"Tool call id was {tool_call.id} but must be a-z, A-Z, 0-9, with a length of 9."
                )
        if (
            self._mode == ValidationMode.finetuning
            and not is_last_message
            and tool_call.id == "null"
        ):
            err_message = "Tool call id of assistant message that is not last has to be defined in finetuning mode."
            raise InvalidFunctionCallException(err_message)

        if self._mode == ValidationMode.serving and tool_call.id == "null":
            raise InvalidFunctionCallException(
                "Tool call id has to be defined in serving mode."
            )

        self._validate_function_call(tool_call.function)

    def _validate_last_message(self, message: UATS) -> None:  # type: ignore
        super()._validate_last_message(message)

        if self._mode == ValidationMode.finetuning:
            # in finetuning mode it has to be an assistant message
            # as checked by parent `_validate_last_message`
            if message.tool_calls is not None:
                for tool_call in message.tool_calls:
                    self._validate_tool_call(tool_call, is_last_message=True)


class InstructRequestNormalizer(
    Generic[
        UserMessageType,
        AssistantMessageType,
        ToolMessageType,
        SystemMessageType,
        InstructRequestType,
    ]
):
    """
    Takes a ChatCompletionRequest and normalizes it into an InstructRequest.

    The normalization process does several things such as:
    - Aggregate consecutive messages of the same role
    - Aggregate system prompts
    - Normalize json content
    - Normalize tool calls
    """

    def __init__(
        self,
        user_message_class: Type[UserMessageType],
        assistant_message_class: Type[AssistantMessageType],
        tool_message_class: Type[ToolMessageType],
        system_message_class: Type[SystemMessageType],
        instruct_request_class: Type[InstructRequestType],
    ):
        self._user_message_class = user_message_class
        self._assistant_message_class = assistant_message_class
        self._tool_message_class = tool_message_class
        self._instruct_request_class = instruct_request_class
        # this is unused but makes creation nicer
        self._system_message_class = system_message_class

    @staticmethod
    def normalizer() -> "InstructRequestNormalizer":  # type: ignore
        return InstructRequestNormalizer(
            UserMessage,
            AssistantMessage,
            ToolMessage,
            SystemMessage,
            InstructRequest[UATS, Tool],  # type: ignore
        )

    def _normalize_json_content(self, content: Optional[str]) -> str:
        if content is None or len(content) == 0:
            return "{}"

        try:
            parsed_json = json.loads(content)
            normalized_content = json.dumps(parsed_json, ensure_ascii=False)
        except json.JSONDecodeError:
            normalized_content = content
        return normalized_content

    def _aggregate_content_chunks(
        self, content: Union[str, List[ContentChunk]], chunk_join_str: str = "\n\n"
    ) -> str:
        if isinstance(content, list):
            return chunk_join_str.join([chunk.text for chunk in content])
        else:
            return content

    def _aggregate_system_prompts(
        self,
        request: ChatCompletionRequest[UATS],  # type: ignore
    ) -> Optional[str]:
        system_prompt: List[str] = []

        for message in request.messages:
            if message.role == Roles.system and message.content:
                system_prompt.append(self._aggregate_content_chunks(message.content))

        return "\n\n".join(system_prompt) if len(system_prompt) else None

    def _aggregate_tool_messages(self, messages: List[UATS]) -> List[ToolMessageType]:  # type: ignore
        """
        We currently do not do any aggregation for tool messages, but we normalize the json content
        """
        tool_messages: List[ToolMessageType] = []
        for message in messages:
            assert isinstance(
                message, self._tool_message_class
            ), "Expected tool message"
            content = self._aggregate_content_chunks(message.content)
            normalized_content = self._normalize_json_content(content)
            tool_messages.append(
                self._tool_message_class(
                    content=normalized_content,
                    tool_call_id=message.tool_call_id,
                    name=message.name,
                )
            )

        return tool_messages

    def _normalize_tool_call(self, tool_call: ToolCall) -> ToolCall:
        normalized_function_aruments = self._normalize_json_content(
            tool_call.function.arguments
        )
        return ToolCall(
            function=FunctionCall(
                name=tool_call.function.name, arguments=normalized_function_aruments
            ),
            id=tool_call.id,
        )

    def _aggregate_assistant_messages(
        self,
        messages: List[UATS],  # type: ignore
    ) -> AssistantMessageType:
        aggregated_content: List[str] = []
        tool_calls: List[ToolCall] = []
        prefix: bool = False
        for message in messages:
            assert isinstance(
                message, self._assistant_message_class
            ), "Expected assistant message"
            if message.tool_calls is not None:
                for tool_call in message.tool_calls:
                    normalized_tool_call = self._normalize_tool_call(tool_call)
                    tool_calls.append(normalized_tool_call)
            elif message.content:
                aggregated_content.append(
                    self._aggregate_content_chunks(message.content)
                )
            prefix |= message.prefix

        return self._assistant_message_class(
            content="\n\n".join(aggregated_content)
            if len(aggregated_content)
            else None,
            tool_calls=tool_calls or None,
            prefix=prefix,
        )

    def _aggregate_user_messages(self, messages: List[UATS]) -> UserMessageType:  # type: ignore
        aggregated_content: List[str] = []
        for message in messages:
            assert isinstance(
                message, self._user_message_class
            ), "Expected user message"
            content = self._aggregate_content_chunks(message.content)
            if content:
                aggregated_content.append(content)

        aggregated_content_str = "\n\n".join(aggregated_content)
        return self._user_message_class(content=aggregated_content_str)

    def _aggregate_role(
        self,
        messages: List[UATS],  # type: ignore
        role: Optional[Roles],
    ) -> Sequence[UATS]:  # type: ignore
        if role == Roles.tool:
            return self._aggregate_tool_messages(messages)
        elif role == Roles.assistant:
            return [self._aggregate_assistant_messages(messages)]
        elif role == Roles.user:
            return [self._aggregate_user_messages(messages)]
        else:  # System messages are ignored
            return []

    def _aggregate_messages(self, request: ChatCompletionRequest[UATS]) -> List[UATS]:  # type: ignore
        aggregated_messages: List[UATS] = []  # type: ignore
        messages_to_aggregate: List[UATS] = []  # type: ignore
        current_role: Optional[Roles] = None

        # Collect consecutive lists of messages with the same role
        for message in request.messages:
            if current_role != message.role:
                aggregated_messages.extend(
                    self._aggregate_role(messages_to_aggregate, current_role)
                )
                messages_to_aggregate.clear()

            current_role = message.role
            messages_to_aggregate.append(message)

        # Add the last set of messages
        aggregated_messages.extend(
            self._aggregate_role(messages_to_aggregate, current_role)
        )

        # If the first message is not a user message, or we didnt aggregate
        # anything (all system messages) for example, add an empty user message
        if len(aggregated_messages) == 0 or aggregated_messages[0].role != Roles.user:
            aggregated_messages.insert(0, self._user_message_class(content=""))

        return aggregated_messages

    def from_chat_completion_request(
        self,
        request: ChatCompletionRequest[UATS],  # type: ignore
    ) -> InstructRequestType:
        system_prompt = self._aggregate_system_prompts(request)
        messages = self._aggregate_messages(request)

        return self._instruct_request_class(
            messages=messages,
            system_prompt=system_prompt,
            available_tools=request.tools,
        )


class SentencePieceTokenizer(Tokenizer):
    def __init__(self, model_path: str) -> None:
        self._logger = logging.getLogger(self.__class__.__name__)
        # reload tokenizer
        assert os.path.isfile(model_path), model_path
        self._model = SentencePieceProcessor(model_file=model_path)

        assert self._model.vocab_size() == self._model.get_piece_size()
        self._vocab = [self._model.id_to_piece(i) for i in range(self.n_words)]

        super().__init__()

    def get_control_token(self, s: str) -> int:
        return self._model.piece_to_id(s)  # type: ignore

    @property
    def n_words(self) -> int:
        return self._model.vocab_size()  # type: ignore

    def vocab(self) -> List[str]:
        return self._vocab

    @property
    def bos_id(self) -> int:
        return self._model.bos_id()  # type: ignore

    @property
    def eos_id(self) -> int:
        return self._model.eos_id()  # type: ignore

    @cached_property
    def _control_tokens(self) -> Set[int]:
        return {tok for tok in range(self.n_words) if self._model.IsControl(tok)}

    def encode(self, s: str, bos: bool, eos: bool) -> List[int]:
        assert isinstance(s, str)
        t: List[int] = self._model.encode(s)
        if bos:
            t = [self.bos_id, *t]
        if eos:
            t = [*t, self.eos_id]
        return t

    def decode(self, t: List[int]) -> str:
        return self._model.decode(t)  # type: ignore

    def id_to_piece(self, token_id: int) -> str:
        return self._model.id_to_piece(token_id)  # type: ignore

    def to_string(self, tokens: List[int]) -> str:
        """
        Converts tokens into a string for debugging purposes
        """
        text = ""
        curr_tokens: List[int] = []
        for tok in tokens:
            if tok in self._control_tokens:
                if curr_tokens:
                    text += "".join([self.id_to_piece(tok) for tok in curr_tokens])
                    curr_tokens = []

                text += self.id_to_piece(tok)

            else:
                curr_tokens.append(tok)

        if curr_tokens:
            text += "".join([self.id_to_piece(tok) for tok in curr_tokens])

        return text


class InstructTokenizerBase(
    InstructTokenizer,  # type: ignore
    Generic[InstructRequestType, FIMRequestType, TokenizedType, AssistantMessageType],
):
    def __init__(self, tokenizer: Tokenizer):
        self.tokenizer = tokenizer
        super().__init__(tokenizer)

    def start(self) -> List[int]:
        return [self.tokenizer.bos_id]

    @staticmethod
    def find_first_last_user(request: InstructRequest) -> Tuple[int, int]:  # type: ignore
        # find last user message
        last_user_idx = -1
        first_user_idx = -1
        for i, msg in list(enumerate(request.messages)):
            if isinstance(msg, UserMessage):
                if first_user_idx == -1:
                    first_user_idx = i
                last_user_idx = i
        return first_user_idx, last_user_idx

    @abstractmethod
    def encode_user_message(
        self,
        message: UserMessage,
        available_tools: Optional[List[Tool]],
        is_last: bool,
        is_first: bool,
        system_prompt: Optional[str] = None,
    ) -> List[int]: ...

    @abstractmethod
    def encode_tool_message(
        self, message: ToolMessage, is_before_last_user_message: bool
    ) -> List[int]:
        raise NotImplementedError("Tool message not implemented")

    @abstractmethod
    def encode_assistant_message(
        self, message: AssistantMessageType, is_before_last_user_message: bool
    ) -> List[int]:
        raise NotImplementedError("Assistant message not implemented")

    def encode_instruct(
        self,
        request: InstructRequest[AssistantMessageType, Tool],  # type: ignore
    ) -> Tokenized:
        # init at bos
        tokens = self.start()
        prefix_ids: Optional[List[int]] = None
        # find last user message
        first_user_idx, last_user_idx = self.find_first_last_user(request)
        for msg_idx, msg in enumerate(request.messages):
            if isinstance(msg, UserMessage):
                new_tokens = self.encode_user_message(
                    msg,
                    request.available_tools,
                    msg_idx == last_user_idx,
                    msg_idx == first_user_idx,
                    system_prompt=request.system_prompt,
                )
            elif isinstance(msg, ToolMessage):
                new_tokens = self.encode_tool_message(msg, msg_idx < last_user_idx)
            elif isinstance(msg, AssistantMessage):
                new_tokens = self.encode_assistant_message(msg, msg_idx < last_user_idx)
                if msg_idx == len(request.messages) - 1:
                    prefix_ids = new_tokens

            tokens.extend(new_tokens)

        return Tokenized(
            tokens=tokens, text=self.tokenizer.to_string(tokens), prefix_ids=prefix_ids
        )

    def decode(self, tokens: List[int]) -> str:
        return self.tokenizer.decode(tokens)


class InstructTokenizerV1(
    InstructTokenizerBase,  # type: ignore
    Generic[InstructRequestType, FIMRequestType, TokenizedType, AssistantMessageType],
):
    def encode_user_message(
        self,
        message: UserMessage,
        available_tools: Optional[List[Tool]],
        is_last: bool,
        is_first: bool,
        system_prompt: Optional[str] = None,
    ) -> List[int]:
        assert message.content is not None
        assert isinstance(message.content, str), "Message content must be normalized"
        content = ""
        if is_first and system_prompt:
            content = system_prompt + "\n\n" + message.content
        else:
            content = message.content

        message_txt = f"[INST] {content} [/INST]"
        curr_tokens = self.tokenizer.encode(message_txt, bos=False, eos=False)
        return curr_tokens

    def encode_tool_message(
        self, message: ToolMessage, is_before_last_user_message: bool
    ) -> List[int]:
        raise TokenizerException("Tools not implemented for tokenizer V1")

    def encode_assistant_message(
        self, message: AssistantMessageType, is_before_last_user_message: bool
    ) -> List[int]:
        assert isinstance(message, AssistantMessage), message
        if message.tool_calls is not None and len(message.tool_calls) > 0:
            raise TokenizerException("Tools not implemented for tokenizer V1")
        elif message.content:
            curr_tokens = self.tokenizer.encode(message.content, bos=False, eos=False)
        else:
            raise TokenizerException(f"{message.content} // {message.tool_calls}")
        if not message.prefix:
            curr_tokens.append(self.tokenizer.eos_id)
        return curr_tokens

    def encode_fim(self, request: FIMRequest) -> Tokenized:
        raise TokenizerException("FIM not available for tokenizer V1")


class SpecialTokens(str, Enum):
    bos = "<s>"
    eos = "</s>"
    begin_inst = "[INST]"
    end_inst = "[/INST]"
    begin_tools = "[AVAILABLE_TOOLS]"
    end_tools = "[/AVAILABLE_TOOLS]"
    begin_tool_results = "[TOOL_RESULTS]"
    end_tool_results = "[/TOOL_RESULTS]"
    tool_calls = "[TOOL_CALLS]"
    prefix = "[PREFIX]"
    middle = "[MIDDLE]"
    suffix = "[SUFFIX]"


class InstructTokenizerV2(
    InstructTokenizerV1,  # type: ignore
    Generic[InstructRequestType, FIMRequestType, TokenizedType, AssistantMessageType],
):
    def __init__(self, tokenizer: Tokenizer):
        super().__init__(tokenizer)
        self.BEGIN_INST = self.tokenizer.get_control_token(
            SpecialTokens.begin_inst.value
        )
        self.END_INST = self.tokenizer.get_control_token(SpecialTokens.end_inst.value)
        self.BEGIN_AVAILABLE_TOOLS = self.tokenizer.get_control_token(
            SpecialTokens.begin_tools.value
        )
        self.END_AVAILABLE_TOOLS = self.tokenizer.get_control_token(
            SpecialTokens.end_tools.value
        )
        self.BEGIN_TOOL_RESULTS = self.tokenizer.get_control_token(
            SpecialTokens.begin_tool_results.value
        )
        self.END_TOOL_RESULTS = self.tokenizer.get_control_token(
            SpecialTokens.end_tool_results.value
        )
        self.TOOL_CALLS = self.tokenizer.get_control_token(
            SpecialTokens.tool_calls.value
        )
        self.BOS = self.tokenizer.get_control_token(SpecialTokens.bos.value)
        self.PREFIX = self.tokenizer.get_control_token(SpecialTokens.prefix.value)
        self.SUFFIX = self.tokenizer.get_control_token(SpecialTokens.suffix.value)

    def encode_user_message(
        self,
        message: UserMessage,
        available_tools: Optional[List[Tool]],
        is_last: bool,
        is_first: bool,
        system_prompt: Optional[str] = None,
    ) -> List[int]:
        assert message.content is not None
        assert isinstance(message.content, str), "Message content must be nornmalized"
        content = ""
        tools_tokens: List[int] = []
        if is_last and available_tools:
            tools = [tool.model_dump() for tool in available_tools]
            tools_json_tokens = self.tokenizer.encode(
                json.dumps(tools, ensure_ascii=False), bos=False, eos=False
            )
            tools_tokens = [
                self.BEGIN_AVAILABLE_TOOLS,
                *tools_json_tokens,
                self.END_AVAILABLE_TOOLS,
            ]

        if is_last and system_prompt:
            content = system_prompt + "\n\n" + message.content
        else:
            content = message.content

        curr_tokens = [
            *tools_tokens,
            self.BEGIN_INST,
            *self.tokenizer.encode(content, bos=False, eos=False),
            self.END_INST,
        ]
        return curr_tokens

    def _parse_json_content(self, content: str) -> Any:
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            return content

    def _prepare_tool_result(self, tool_message: ToolMessage) -> Dict[str, Any]:
        """
        Bit of a hack due to the way tool results are tokenized
        """
        assert tool_message.content is not None, "Tool message content cannot be None"
        return {
            "name": tool_message.name,
            "content": self._parse_json_content(tool_message.content),
        }

    def encode_tool_message(
        self, message: ToolMessage, is_before_last_user_message: bool
    ) -> List[int]:
        if is_before_last_user_message:
            # don't tokenize last tool response before last user msg
            return []

        # Currently only supports single tool results
        tool_result_str = json.dumps(
            [self._prepare_tool_result(message)], ensure_ascii=False
        )
        curr_tokens = [
            self.BEGIN_TOOL_RESULTS,
            *self.tokenizer.encode(tool_result_str, bos=False, eos=False),
            self.END_TOOL_RESULTS,
        ]
        return curr_tokens

    def _prepare_function_call(self, tool_call: ToolCall) -> Dict[str, Any]:
        """
        Bit of a hack due to the way function calls are tokenized
        """
        return {
            "name": tool_call.function.name,
            "arguments": self._parse_json_content(tool_call.function.arguments),
        }

    def encode_assistant_message(
        self, message: AssistantMessageType, is_before_last_user_message: bool
    ) -> List[int]:
        if message.tool_calls is not None and len(message.tool_calls) > 0:
            if is_before_last_user_message:
                # don't tokenize tool call before last user message
                return []

            prepared_tool_calls = []
            for tool_call in message.tool_calls:
                prepared_tool_calls.append(self._prepare_function_call(tool_call))

            tool_call_str = json.dumps(prepared_tool_calls, ensure_ascii=False)
            curr_tokens = [
                self.TOOL_CALLS,
                *self.tokenizer.encode(tool_call_str, bos=False, eos=False),
            ]
        elif message.content:
            curr_tokens = self.tokenizer.encode(message.content, bos=False, eos=False)
        else:
            raise TokenizerException(f"Invalid assistant message: {message.content}")

        if not message.prefix:
            curr_tokens.append(self.tokenizer.eos_id)
        return curr_tokens

    def _encode_infilling(self, text: str) -> List[int]:
        """
        Remove prefix space in the case of SentencePieceTokenizers
        Thanks Fabian !
        """

        return self.tokenizer.encode("☺" + text, bos=False, eos=False)[2:]

    def encode_fim(self, request: FIMRequest) -> Tokenized:
        prefix_tokens = self.tokenizer.encode(request.prompt, bos=False, eos=False)
        suffix_tokens = self._encode_infilling(request.suffix) if request.suffix else []
        tokens = [
            self.BOS,
            self.SUFFIX,
            *suffix_tokens,
            self.PREFIX,
            *prefix_tokens,
        ]
        return Tokenized(tokens=tokens, text=self.tokenizer.to_string(tokens))


class InstructTokenizerV3(
    InstructTokenizerV2,  # type: ignore
    Generic[InstructRequestType, FIMRequestType, TokenizedType, AssistantMessageType],
):
    """
    The only difference with V3 tokenizer is that it encodes the tool messages differently
    """

    def __init__(self, tokenizer: Tokenizer):
        super().__init__(tokenizer)

    def _prepare_function_call(self, tool_call: ToolCall) -> Dict[str, Any]:
        function_call = {
            "name": tool_call.function.name,
            "arguments": self._parse_json_content(tool_call.function.arguments),
        }

        if tool_call.id and tool_call.id != "null":
            function_call["id"] = tool_call.id

        return function_call

    def _prepare_tool_result(self, tool_message: ToolMessage) -> Dict[str, Any]:
        assert tool_message.content is not None, "Tool message content cannot be None"
        assert (
            tool_message.tool_call_id is not None
        ), "Tool message has to have the tool call id defined in v3"

        return {
            "content": self._parse_json_content(tool_message.content),
            "call_id": tool_message.tool_call_id,
        }

    def encode_tool_message(
        self, message: ToolMessage, is_before_last_user_message: bool
    ) -> List[int]:
        """
        Same as V2 but tools not wrapped in a list and history is tokenized also
        """
        tool_result_str = json.dumps(
            self._prepare_tool_result(message), ensure_ascii=False
        )
        curr_tokens = [
            self.BEGIN_TOOL_RESULTS,
            *self.tokenizer.encode(tool_result_str, bos=False, eos=False),
            self.END_TOOL_RESULTS,
        ]
        return curr_tokens

    def encode_assistant_message(
        self, message: AssistantMessageType, is_before_last_user_message: bool
    ) -> List[int]:
        """
        Same as V2 but always encode tool history
        """
        return super().encode_assistant_message(message, False)


class MistralTokenizer(
    Generic[
        UserMessageType,
        AssistantMessageType,
        ToolMessageType,
        SystemMessageType,
        TokenizedType,
    ]
):
    def __init__(
        self,
        instruct_tokenizer: InstructTokenizer[  # type: ignore
            InstructRequest, FIMRequest, TokenizedType, AssistantMessageType
        ],
        validator: MistralRequestValidator[
            UserMessageType, AssistantMessageType, ToolMessageType, SystemMessageType
        ],
        request_normalizer: InstructRequestNormalizer[
            UserMessageType,
            AssistantMessageType,
            ToolMessageType,
            SystemMessageType,
            InstructRequestType,
        ],
    ):
        self._chat_completion_request_validator = validator
        self._instruct_request_normalizer = request_normalizer
        self.instruct_tokenizer = instruct_tokenizer

    @classmethod
    def _data_path(cls) -> Path:
        return Path(__file__).parents[2] / "data"

    @classmethod
    def v1(cls):  # type: ignore
        """open-mistral-7b // open-mixtral-8x7b // mistral-embed"""
        return cls.from_file(
            str(cls._data_path() / "tokenizer.model.v1"), mode=ValidationMode.test
        )

    @classmethod
    def v2(cls):  # type: ignore
        """mistral-small // mistral-large"""
        return cls.from_file(
            str(cls._data_path() / "mistral_instruct_tokenizer_240216.model.v2"),
            mode=ValidationMode.test,
        )

    @classmethod
    def v3(cls):  # type: ignore
        """open-mixtral-8x22b // codestral-22b"""
        return cls.from_file(
            str(cls._data_path() / "mistral_instruct_tokenizer_240323.model.v3"),
            mode=ValidationMode.test,
        )

    @classmethod
    def from_model(cls, model: str):  # type: ignore
        model_name_to_tokenizer_cls: Dict[str, Callable[[], MistralTokenizer]] = {  # type: ignore
            "open-mistral-7b": MistralTokenizer.v1,
            "open-mixtral-8x7b": MistralTokenizer.v1,
            "mistral-embed": MistralTokenizer.v1,
            "mistral-small": MistralTokenizer.v2,
            "mistral-large": MistralTokenizer.v2,
            "open-mixtral-8x22b": MistralTokenizer.v3,
            "codestral-22b": MistralTokenizer.v3,
        }

        # Prefix search the model name mapping
        for model_name, tokenizer_cls in model_name_to_tokenizer_cls.items():
            if model_name in model:
                return tokenizer_cls()

        raise TokenizerException(f"Unrecognized model: {model}")

    @classmethod
    def from_file(  # type: ignore
        cls, tokenizer_filename: str, mode: ValidationMode = ValidationMode.test
    ):
        """
        Depending on which model we are loading, tokenization and validation might be different.
        """
        if tokenizer_filename.endswith(".model.v1") or tokenizer_filename.endswith(
            ".model"
        ):
            return MistralTokenizer(
                InstructTokenizerV1(SentencePieceTokenizer(tokenizer_filename)),
                validator=MistralRequestValidator(mode=mode),
                request_normalizer=InstructRequestNormalizer.normalizer(),
            )
        elif tokenizer_filename.endswith(".model.v2"):
            return MistralTokenizer(
                InstructTokenizerV2(SentencePieceTokenizer(tokenizer_filename)),
                validator=MistralRequestValidator(mode=mode),
                request_normalizer=InstructRequestNormalizer.normalizer(),
            )
        elif tokenizer_filename.endswith(".model.v3"):
            return MistralTokenizer(
                InstructTokenizerV3(SentencePieceTokenizer(tokenizer_filename)),
                validator=MistralRequestValidatorV3(mode=mode),
                request_normalizer=InstructRequestNormalizer.normalizer(),
            )
        else:
            raise TokenizerException(
                f"Unrecognized tokenizer filename: {tokenizer_filename}"
            )

    def encode_chat_completion(self, request: ChatCompletionRequest[UATS]) -> Tokenized:  # type: ignore
        validated_request = self._chat_completion_request_validator.validate_request(
            request
        )
        instruct_request = (
            self._instruct_request_normalizer.from_chat_completion_request(
                validated_request
            )
        )
        return self.instruct_tokenizer.encode_instruct(instruct_request)

    def encode_fim(self, request: FIMRequest) -> Tokenized:
        return self.instruct_tokenizer.encode_fim(request)

    def decode(self, tokens: List[int]) -> str:
        return self.instruct_tokenizer.decode(tokens)
