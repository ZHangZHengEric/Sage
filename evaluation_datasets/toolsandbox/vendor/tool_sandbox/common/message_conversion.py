# For licensing see accompanying LICENSE file.
# Copyright (C) 2024 Apple Inc. All Rights Reserved.
import ast
import json
import re
from collections import defaultdict
from typing import Any, Literal, Optional, cast

import polars as pl
from attrs import asdict, define, field
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from openai.types.chat.chat_completion_message_tool_call import (
    ChatCompletionMessageToolCall,
    Function,
)

from tool_sandbox.common.evaluation import EvaluationResult, Milestone, Minefield
from tool_sandbox.common.execution_context import (
    DatabaseNamespace,
    ExecutionContext,
    RoleType,
)
from tool_sandbox.common.utils import attrs_serialize


@define(frozen=True)
class Message:
    """Messages each role reads and writes"""

    sender: RoleType = field(converter=RoleType)
    recipient: RoleType = field(converter=RoleType)
    content: str
    conversation_active: Optional[bool] = None
    # Optional fields to support OpenAI API
    openai_tool_call_id: Optional[str] = None
    openai_function_name: Optional[str] = None
    # Optional field for storing exceptions that occurred as part of the tool call.
    tool_call_exception: Optional[str] = None
    # Optional field tracing tool execution for this message
    tool_trace: Optional[list[str]] = None
    # Message visibility. By default, should be visible to sender and recipient
    visible_to: Optional[list[RoleType]] = None

    def __attrs_post_init__(self) -> None:
        # Bypass frozen. See https://github.com/python-attrs/attrs/issues/120.
        # Assign default visibility
        if self.visible_to is None:
            object.__setattr__(self, "visible_to", [self.sender, self.recipient])


def openai_tool_call_to_python_code(
    tool_call: ChatCompletionMessageToolCall,
    available_tool_names: set[str],
    execution_facing_tool_name: Optional[str],
) -> str:
    """Converts OpenAI ChatCompletionMessageToolCall to python code

    Args:
        tool_call:                   ChatCompletionMessageToolCall object
        available_tool_names:        Set of tools available
        execution_facing_tool_name:  The execution facing name of the function. In the
                                     case of tool name scrambling the OpenAI API in- and
                                     outputs are filled with scrambled tool names. When
                                     executing the code we need to use the actual tool
                                     name. If `None` the tool name stored in `tool_call`
                                     will be used.

    Returns:
        A python code making the tool call

    Raises:
        KeyError:   If the tool name is not a known tool
    """
    tool_id = tool_call.id
    agent_facing_tool_name = tool_call.function.name

    # Check if function name is known allowed tool
    if agent_facing_tool_name not in available_tool_names:
        raise KeyError(
            f"Agent tool call {agent_facing_tool_name=} is not a known allowed tool. Options are {available_tool_names=}"
        )
    function_name = (
        agent_facing_tool_name
        if execution_facing_tool_name is None
        else execution_facing_tool_name
    )
    function_call_code = (
        f"{tool_id}_parameters = {json.loads(tool_call.function.arguments)}\n"
        f"{tool_id}_response = {function_name}(**{tool_id}_parameters)\n"
        f"print(repr({tool_id}_response))"
    )
    return function_call_code


def python_code_to_openai_tool_call(
    python_code: str,
    agent_facing_tool_name: Optional[str],
) -> ChatCompletionMessageToolCall:
    """Converts python code to OpenAI ChatCompletionMessageToolCall.

    Execution facing tool_name shall be converted back to agent facing tool_name.

    Args:
        python_code:            A python code making the tool call
        agent_facing_tool_name: The agent facing name of the function. In the
                                case of tool name scrambling the OpenAI API in- and
                                outputs are filled with scrambled tool names. When
                                executing the code we need to use the actual tool
                                name. If `None` the tool name stored in python
                                will be used.

    Returns:
        ChatCompletionMessageToolCall object


    Raises:
        KeyError:   If the tool name is not a known tool
    """
    pattern = r"^(?P<tool_id>.+)_parameters = (?P<arguments>[^\n]+)\n(?P=tool_id)_response = (?P<name>[^\(]+)"
    match = re.match(pattern=pattern, string=python_code)
    assert match is not None
    function_name = (
        match.group("name")
        if agent_facing_tool_name is None
        else agent_facing_tool_name
    )
    return ChatCompletionMessageToolCall(
        id=match.group("tool_id"),
        type="function",
        function=Function(
            name=function_name,
            arguments=json.dumps(ast.literal_eval(match.group("arguments"))),
        ),
    )


def to_openai_messages(
    messages: list[Message],
) -> tuple[
    list[
        dict[
            Literal["role", "content", "tool_call_id", "name", "tool_calls"],
            Any,
        ]
    ],
    list[list[int]],
]:
    """Converts a list of Tool Sandbox messages to OpenAI API messages

    Multiple sandbox messages could be compressed into a single OpenAI API message. Because of this,
    we return a mapping between the indices of these two in addition. This is useful for serialization

    Args:
        messages:   A list of Tool Sandbox messages

    Returns:
        A list of OpenAI API messages and a list of openai_messages index -> messages index mapping
    """
    openai_messages: list[
        dict[
            Literal["role", "content", "tool_call_id", "name", "tool_calls"],
            Any,
        ]
    ] = []
    # kth entry in this list contains the list of messages indices openai_messages[k] maps to
    indices_mapping: list[list[int]] = []

    for i, message in enumerate(messages):
        # Process messages
        if message.sender == RoleType.SYSTEM and message.recipient == RoleType.AGENT:
            openai_messages.append({"role": "system", "content": message.content})
        elif message.sender == RoleType.USER and message.recipient == RoleType.AGENT:
            openai_messages.append({"role": "user", "content": message.content})
        elif (
            message.sender == RoleType.EXECUTION_ENVIRONMENT
            and message.recipient == RoleType.AGENT
        ):
            assert message.openai_tool_call_id is not None
            assert message.openai_function_name is not None
            openai_messages.append(
                {
                    "tool_call_id": message.openai_tool_call_id,
                    "role": "tool",
                    "name": message.openai_function_name,
                    "content": message.content,
                }
            )
        elif (
            message.sender == RoleType.AGENT
            and message.recipient == RoleType.EXECUTION_ENVIRONMENT
        ):
            # Aggregate multiple function calls
            if "tool_calls" not in openai_messages[-1]:
                # Create a new message with empty tool call
                # Note: We do not use `"content": None` since that breaks assumptions in
                # the Cohere tokenizer. More specifically, the prompt generation using
                # templates fails because `None` is not a string.
                openai_messages.append(
                    {"role": "assistant", "content": "", "tool_calls": []}
                )
            # Add tool call
            openai_messages[-1]["tool_calls"].append(
                python_code_to_openai_tool_call(
                    message.content, message.openai_function_name
                ).model_dump(mode="dict", exclude_unset=True)
            )
        elif message.sender == RoleType.AGENT and message.recipient == RoleType.USER:
            openai_messages.append({"role": "assistant", "content": message.content})
        else:
            raise ValueError(
                f"Unrecognized sender recipient pair {(message.sender, message.recipient)}"
            )
        # Process mapping
        if (
            message.sender == RoleType.AGENT
            and message.recipient == RoleType.EXECUTION_ENVIRONMENT
            and "tool_calls" in openai_messages[-1]
            and len(openai_messages[-1]["tool_calls"]) > 1
        ):
            indices_mapping[-1].append(i)
        else:
            indices_mapping.append([i])

    return openai_messages, indices_mapping


def openai_messages_to_langchain_messages(
    openai_messages: list[dict[str, Any]],
) -> list[BaseMessage]:
    """Convert OpenAI dict messages to langchain strongly typed messages

    Args:
        openai_messages:    OpenAI messages to convert

    Returns:
        langchain messages between human, assistant and tool
    """
    langchain_messages: list[BaseMessage] = []
    for message in openai_messages:
        if message["role"] == "user":
            langchain_messages.append(HumanMessage(content=message.get("content", "")))
        elif message["role"] == "assistant":
            tool_calls = message.get("tool_calls", [])
            for tool_call in tool_calls:
                tool_call["type"] = "TOOL_TYPE_FUNCTION"
            # More recent langchain versions contain a `tool_calls`` field, but our
            # version is pinned to version 0.1.3, which does not have it yet.
            langchain_messages.append(
                AIMessage(  # type: ignore[call-arg]
                    content=message.get("content", "")
                    if message.get("content", "") is not None
                    else "",
                    tool_calls=tool_calls,
                )
            )

        elif message["role"] == "tool":
            langchain_messages.append(
                ToolMessage(
                    tool_call_id=message["tool_call_id"],
                    content=message.get("content", ""),
                )
            )
    return langchain_messages


def get_snapshot_indices_to_databases(
    execution_context: ExecutionContext,
) -> dict[int, dict[str, pl.DataFrame]]:
    """Create a mapping of snapshot index -> database update that happened at said index.

    Args:
        execution_context:  The execution context containing databases.

    Returns:

    """
    snapshot_indices_to_databases: dict[int, dict[str, pl.DataFrame]] = defaultdict(
        dict
    )
    for namespace in set(DatabaseNamespace) - {DatabaseNamespace.SANDBOX}:
        # Find indices where a new snapshot was created, add to the mapping
        update_indices = (
            execution_context.get_database(
                namespace=cast(DatabaseNamespace, namespace),
                get_all_history_snapshots=True,
                drop_sandbox_message_index=False,
                drop_headguard=False,
            )
            .select("sandbox_message_index")
            .unique()["sandbox_message_index"]
            .to_list()
        )
        for update_index in update_indices:
            snapshot_indices_to_databases[update_index][namespace] = (
                execution_context.get_database(
                    namespace=cast(DatabaseNamespace, namespace),
                    sandbox_message_index=update_index,
                )
            )

    return snapshot_indices_to_databases


def serialize_to_conversation(
    execution_context: ExecutionContext,
    evaluation_result: EvaluationResult,
    milestones: list[Milestone],
    minefields: list[Minefield],
) -> list[dict[str, Any]]:
    """Serialize an Execution Context and evaluation result.

    This function serializes the following objects:
        1. Serialize Sandbox database into messages, including the stacktrace if the session errored out with an
            exception.
        2. All other database snapshots, attached to the message where the update happened.

    Args:
        execution_context:      The final execution context object after playing out the scenario
        evaluation_result:      Evaluation result of the scenario. Contains milestone mapping.
        milestones:             Milestones associated with this scenario
        minefields:             Minefields associated with this scenario

    Returns:
        A list of per-turn dictionary elements.
    """
    # Finds the database subset only containing System -> Agent, User <-> Agent, Agent <-> ExecutionEnvironment
    # Ignore user simulator few-shot messages
    message_subset_database: pl.DataFrame = execution_context.get_database(
        DatabaseNamespace.SANDBOX,
        drop_sandbox_message_index=False,
        get_all_history_snapshots=True,
    ).filter(
        ((pl.col("sender") == RoleType.AGENT) | (pl.col("recipient") == RoleType.AGENT))
        & (
            (pl.col("visible_to") != [RoleType.USER])
            | (pl.col("visible_to").is_null())
        )
    )
    subset_to_snapshot_indices_mapping: list[int] = cast(
        list[int], message_subset_database["sandbox_message_index"].to_list()
    )
    message_subset = [
        Message(**row)
        for row in message_subset_database.drop("sandbox_message_index").to_dicts()
    ]
    # Convert SANDBOX database to OpenAI API messages
    openai_messages, openai_messages_to_subset_indices_mapping = to_openai_messages(
        messages=message_subset
    )
    # Create a mapping of snapshot index -> database update that happened at said index
    snapshot_indices_to_databases: dict[int, dict[str, pl.DataFrame]] = (
        get_snapshot_indices_to_databases(execution_context)
    )
    # Create a mapping of snapshot index -> matching milestone
    snapshot_indices_to_milestones: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for milestone_index, (
        snapshot_index,
        milestone_similarity,
    ) in evaluation_result.milestone_mapping.items():
        snapshot_indices_to_milestones[snapshot_index].append(
            {
                "milestone_index": milestone_index,
                "milestone": asdict(
                    milestones[milestone_index],
                    value_serializer=attrs_serialize,
                ),
                "milestone_similarity": milestone_similarity,
            }
        )
    # Create a mapping of snapshot index -> matching minefield
    snapshot_indices_to_minefields: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for minefield_index, (
        snapshot_index,
        minefield_similarity,
    ) in evaluation_result.minefield_mapping.items():
        snapshot_indices_to_minefields[snapshot_index].append(
            {
                "minefield_index": minefield_index,
                "minefield": asdict(
                    minefields[minefield_index],
                    value_serializer=attrs_serialize,
                ),
                "minefield_similarity": minefield_similarity,
            }
        )

    # Find a one to many mapping between OpenAI messages and its original snapshot index
    openai_messages_to_snapshot_indices_mapping: list[list[int]] = [
        [subset_to_snapshot_indices_mapping[i] for i in subset_indices]
        for subset_indices in openai_messages_to_subset_indices_mapping
    ]
    turns: list[dict[str, Any]] = []
    for openai_message, snapshot_indices in zip(
        openai_messages, openai_messages_to_snapshot_indices_mapping
    ):
        # Add message
        turns.append(cast(dict[str, Any], openai_message))

        current_extras_key = f"{openai_message['role']}_details"
        for snapshot_index in snapshot_indices:
            # Try to add db update
            if snapshot_index in snapshot_indices_to_databases:
                for database_name, database in snapshot_indices_to_databases[
                    snapshot_index
                ].items():
                    if current_extras_key not in turns[-1]:
                        turns[-1][current_extras_key] = defaultdict(
                            lambda: defaultdict()
                        )
                    turns[-1][current_extras_key]["database_update"][database_name] = (
                        database.to_dicts()
                    )
            # Try to add milestone mapping
            if snapshot_index in snapshot_indices_to_milestones:
                if current_extras_key not in turns[-1]:
                    turns[-1][current_extras_key] = defaultdict()
                turns[-1][current_extras_key]["milestone_matches"] = (
                    snapshot_indices_to_milestones[snapshot_index]
                )
            # Try to add minefield mapping
            if snapshot_index in snapshot_indices_to_minefields:
                if current_extras_key not in turns[-1]:
                    turns[-1][current_extras_key] = defaultdict()
                turns[-1][current_extras_key]["minefield_matches"] = (
                    snapshot_indices_to_minefields[snapshot_index]
                )

    return turns
