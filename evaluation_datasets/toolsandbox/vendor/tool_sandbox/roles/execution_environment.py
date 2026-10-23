# For licensing see accompanying LICENSE file.
# Copyright (C) 2024 Apple Inc. All Rights Reserved.
"""Python Execution Environment"""

import code
import copy
import io
import itertools
import traceback
from contextlib import redirect_stderr, redirect_stdout
from typing import List, Optional, Sequence

import polars as pl
from attrs import evolve

from tool_sandbox.common.execution_context import (
    DatabaseNamespace,
    ExecutionContext,
    RoleType,
    get_current_context,
    set_current_context,
)
from tool_sandbox.common.message_conversion import Message
from tool_sandbox.roles.base_role import BaseRole


def respond_to_single_message(
    interactive_console: code.InteractiveConsole,
    message: Message,
    role_type: RoleType,
) -> Optional[Message]:
    """Respond to a single message.

    Args:
        interactive_console: The interactive console to use for executing the function
                             call.
        message:             The message to which to respond.
        role_type:           The role type of the responder (e.g. sender of the
                             response).

    Returns:
        A message if there was a response. More specifically, if the sender is the
        `system` role then the returned value is `None`.
    """
    # First compile the code string to a command, which checks if the command is
    # valid and complete (regarding completeness see `if command is None` below for
    # details). Note that we cannot use the default `symbol=single` since that assumes
    # that we want to only generate a single statement. This would result in a syntax
    # error for e.g. `a = 1\nb = 2` saying
    #    "multiple statements found while compiling a single statement"
    try:
        command = code.compile_command(message.content, symbol="exec")
    except (OverflowError, SyntaxError, ValueError):
        # We do not want to leak details like the code path so we only include the
        # actual exception in the traceback.
        traceback_str = traceback.format_exc(limit=0)
        return Message(
            sender=role_type,
            recipient=message.sender,
            content=traceback_str,
            openai_tool_call_id=message.openai_tool_call_id,
            openai_function_name=message.openai_function_name,
            tool_call_exception=traceback_str,
        )
    if command is None:
        # `None` is returned when the given code string is incomplete. An example
        # would be `code.compile_command("if True:")`. The LLM should not generate
        # such code so we consider this an error/failure.
        response = f"Error: The given code was incomplete and could not be executed: '{message.content}'"
        return Message(
            sender=role_type,
            recipient=message.sender,
            content=response,
            openai_tool_call_id=message.openai_tool_call_id,
            openai_function_name=message.openai_function_name,
            tool_call_exception=response,
        )

    # Open StringIO and capture stdout && stderr from env
    with (
        io.StringIO() as f_stdout,
        io.StringIO() as f_stderr,
        redirect_stdout(f_stdout),
        redirect_stderr(f_stderr),
    ):
        # Execute the code. At this point we know that the code is valid Python, but it
        # can still throw exceptions.
        interactive_console.runcode(command)
        # If this message is from system, do not respond
        if message.sender == RoleType.SYSTEM:
            return None

        stdout_message = f_stdout.getvalue()
        stderr_message = f_stderr.getvalue()
        # Start with stdout, it ends with newline
        content_lines = stdout_message.rstrip().split("\n") if stdout_message else []
        if stderr_message:
            stderr_lines = stderr_message.rstrip().split("\n")
            exception_str = stderr_lines[-1]
            content_lines.append(exception_str)
        else:
            exception_str = None
        # The state update of all messages are attached to the first responded message.
        # Fix this by responding immediately instead. Remember to move tool trace processing here as well
        return Message(
            sender=role_type,
            recipient=message.sender,
            content="\n".join(content_lines),
            openai_tool_call_id=message.openai_tool_call_id,
            openai_function_name=message.openai_function_name,
            tool_call_exception=exception_str,
        )


def respond_to_messages(
    interactive_console: code.InteractiveConsole,
    messages: Sequence[Message],
    role_type: RoleType,
) -> list[Message]:
    """Respond to the given messages.

    Args:
        interactive_console: The interactive console to use for executing the function
                             call.
        messages:            The messages to which to respond.
        role_type:           The role type of the responder (e.g. sender of the
                             response).

    Returns:
        The response messages. Note that it can be an empty list if the messages came
        from the `system` role.
    """
    response_messages = [
        respond_to_single_message(interactive_console, message, role_type)
        for message in messages
    ]
    return [message for message in response_messages if message is not None]


def respond_to_messages_set_all_order_permutations(
    execution_context: ExecutionContext,
    messages: list[Message],
    role_type: RoleType,
) -> list[Message]:
    """Respond to the given messages performing tool calls in all possible orderings.

    If `messages` contains parallel function calls then we execute them in all possible
    orderings. If all tool call permutations were successful we return the responses in
    the same order as the incoming messages. If a tool call permutation failed then we
    consider the parallel function call to be invalid (i.e. potentially the function
    calls are not truly independent) and return the responses matching the permutated
    tool call order.

    Args:
        execution_context: The original execution context.
        messages:          The messages to which to respond.
        role_type:         The role type of the responder (e.g. sender of the response).

    Returns:
        The response messages. Note that it can be an empty list if the messages came
        from the `system` role.
    """
    # Simple case: a single function call.
    if len(messages) <= 1:
        return respond_to_messages(
            interactive_console=execution_context.interactive_console,
            messages=messages,
            role_type=role_type,
        )

    # Parallel function calls should only be requested when the functions are
    # independent, i.e. one function call does not depend on another function. However,
    # we have seen cases where LLMs erroneously use parallel function calls instead of
    # sequential ones. Since we execute functions sequentially here we cannot simply
    # execute the calls one after another since then actually invalid parallel function
    # calls may succeed (because they happen to be in the right order). To robustly
    # identify such invalid parallel tool calls we call the tools in all possible
    # permutations and if any permutation failed we consider the tool call to have
    # failed. Some notes about this design decision:
    #  - It is pessimistic for function calls that may fail non-deterministically
    #    (e.g. a call to a REST API that happens to fail intermittently)
    #  - The number of permutations is the factorial of the number of function calls,
    #    which means that the time it takes to execute all possible permutations
    #    increases rapidly. We expect that the number of tool calls is small so this
    #    should be okay.
    original_context = copy.deepcopy(execution_context)
    response_messages: list[Message] = []
    # When failure happens, the currently set context is the same as current failure messages
    # When all permutation succeeds, since we want to return original response order,
    # corresponding resulting execution context needs to be reset as well.
    result_context: Optional[ExecutionContext] = None
    for i, permutated_messages in enumerate(itertools.permutations(messages)):
        modifiable_context = copy.deepcopy(original_context)
        set_current_context(modifiable_context)
        current_response_messages = respond_to_messages(
            modifiable_context.interactive_console,
            permutated_messages,
            role_type,
        )
        # If all permutations of the tool call order execute successfully we want
        # to return the responses that match the originally requested tool call
        # order. This original ordering is the first element returned by
        # `itertools.permutations`.
        if i == 0:
            response_messages = current_response_messages
            result_context = get_current_context()
            # Consistency check. We compare the contents since comparing the list of
            # messages fails (presumably because `itertools.permutations` copies
            # objects or something like that).
            assert [message.content for message in messages] == [
                message.content for message in permutated_messages
            ]

        # If a failure occurred for any permutation of tool calls there is no need
        # to execute the remaining permutations since we consider the parallel tool
        # invalid (i.e. previous permutations may have just succeeded out of luck).
        failure = any(
            response.tool_call_exception is not None
            for response in current_response_messages
        )
        if failure:
            # On failure we want to return the current responses even if they do not
            # match the originally requested tool call order.
            return current_response_messages
    # Reset context
    if result_context is not None:
        set_current_context(result_context)
    return response_messages


def get_messages_to_process(
    messages: list[Message], recipient: RoleType
) -> list[Message]:
    """Filter out the message to which the execution environment should respond.

    Args:
        messages:   All messages of the current conversation.
        recipient:  The role type of the recipient.

    Returns:
        The messages to which the `recipient` should respond.
    """
    new_messages_index = len(messages) - 1
    while new_messages_index >= 0:
        if messages[new_messages_index].recipient != recipient:
            break
        new_messages_index -= 1
    messages_to_process = messages[new_messages_index + 1 :]
    return messages_to_process


class ExecutionEnvironment(BaseRole):
    """An Execution Environment able to execute python code in an REPL console in a stateful manner
    Note that this happens in the same process and thread as your main process, just under a different scope
    """

    role_type: RoleType = RoleType.EXECUTION_ENVIRONMENT

    def respond(self, ending_index: Optional[int] = None) -> None:
        """Reads a List of messages and attempt to respond with a Message

        Specifically, reads python source code from other Roles, executes and return with REPL env stdout / stderr
        System could provide necessary imports and init commands at the start, in which case we won't respond,
        just silently execute the code snippet
        User could provide tool call to terminate the conversation
        Agent could provide tool call to help complete the ongoing task

        Message comes from current context, the last k messages should be directed to this role type
        Response are written to current context as well. k new messages, addressed to appropriate recipient

        Args:
            ending_index:   Optional index. Will respond to message located at ending_index instead of most recent one
                            if provided. Utility for processing system message, which could contain multiple entries
                            before each was responded to

        Raises:
            KeyError:   When the last message is not directed to this role
        """
        messages: List[Message] = self.get_messages(ending_index=ending_index)
        self.messages_validation(messages)

        # Some LLMs (e.g. GPT-3.5 turbo) can return multiple function calls in a single
        # request, which is called parallel function calling. Thus, the execution
        # environment may have to process multiple messages.
        messages_to_process = get_messages_to_process(
            messages, recipient=self.role_type
        )

        response_messages = respond_to_messages_set_all_order_permutations(
            execution_context=get_current_context(),
            messages=messages_to_process,
            role_type=self.role_type,
        )
        # At this point the tool calls have been performed and the global execution
        # context reflects the changes introduced by the tool calls. Note that we need
        # to get the current context again since
        # `respond_to_messages_set_all_order_permutations` may have changed the context.
        current_context = get_current_context()

        # Since tool_trace is technically the outcome of calling a tool, assign tool_trace collected in the last
        # Agent -> ExecutionEnvironment message to ExecutionEnvironment -> Agent messages
        # Note that tool traces are being stored in permuted order, while responses messages are in original order.
        # Need to reorder tool trace accordingly.
        tool_trace_series: Optional[pl.Series] = current_context.get_database(
            DatabaseNamespace.SANDBOX
        )["tool_trace"][0]
        if tool_trace_series is not None:
            tool_trace_list = tool_trace_series.to_list()
            # Erase tool trace collected in Agent -> ExecutionEnvironment message
            current_context.update_database(
                DatabaseNamespace.SANDBOX,
                current_context.get_database(DatabaseNamespace.SANDBOX).with_columns(
                    pl.lit(None).alias("tool_trace")
                ),
            )
            # Hack for skipping execution where an exception happened
            tool_trace_index = 0
            for i in range(len(response_messages)):
                if response_messages[i].tool_call_exception is not None:
                    continue
                response_messages[i] = evolve(
                    response_messages[i], tool_trace=[tool_trace_list[tool_trace_index]]
                )
                tool_trace_index += 1
            assert tool_trace_index == len(tool_trace_list), (
                f"The tool trace index of {tool_trace_index} does not match the "
                f"length of the tool trace list of {len(tool_trace_list)}."
            )
        self.add_messages(response_messages)
