# For licensing see accompanying LICENSE file.
# Copyright (C) 2024 Apple Inc. All Rights Reserved.
"""Interactive CLI user/agent role for human interfacing."""

import inspect
from dataclasses import dataclass
from logging import getLogger
from typing import List, Optional

from tool_sandbox.common.execution_context import RoleType
from tool_sandbox.common.message_conversion import Message
from tool_sandbox.roles.base_role import BaseRole

LOGGER = getLogger(__name__)


@dataclass
class InteractiveMessage:
    content: Optional[str] = None
    tool_call: Optional[str] = None


class CliRole(BaseRole):
    """Interactive CLI user/agent role for a real human."""

    role_type: RoleType
    model_name: str

    def __init__(self) -> None:
        print(f"Interactive role '{self.role_type}'.")

    def respond(self, ending_index: Optional[int] = None) -> None:
        """Reads a List of messages and attempt to respond with a Message

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
        # Agent does not respond to System
        if self.role_type == RoleType.AGENT and messages[-1].sender == RoleType.SYSTEM:
            return
        # Get tools.
        available_tools = self.get_available_tools()
        available_tool_names = set(available_tools.keys())

        print("*" * 80)
        for msg in messages:
            print(f" [{msg.sender}] -> [{msg.recipient}]: {msg.content}")
        print("-" * 80)
        # Ask user for input.
        response = self.user_input()

        # Parse response
        if response.tool_call is None:
            # Message contains no tool call, aka addressed to agent
            assert response.content is not None
            recipient_role = (
                RoleType.AGENT if self.role_type == RoleType.USER else RoleType.USER
            )
            response_messages = [
                Message(
                    sender=self.role_type,
                    recipient=recipient_role,
                    content=response.content,
                )
            ]
        else:
            assert response.tool_call is not None
            response_messages = [
                Message(
                    sender=self.role_type,
                    recipient=RoleType.EXECUTION_ENVIRONMENT,
                    content=self.user_tool_call_to_python_code(
                        response.tool_call, available_tool_names
                    ),
                )
            ]
        self.add_messages(response_messages)

    def user_input(self) -> InteractiveMessage:
        """Get the user input from the CLI and return a message.

        Returns:
          A message containing the plain text or tool call information.
        """
        available_tool_names = self.get_available_tools().keys()
        text = input(f" [{self.role_type}] > ")
        if text == "end" and "end_conversation" in available_tool_names:
            return InteractiveMessage(tool_call="end_conversation()")
        if text != "tool":
            return InteractiveMessage(content=text)
        # Tool call, show available options.
        tool_names_sigs = [
            (f.__name__, inspect.signature(f))
            for f in self.get_available_tools().values()
        ]
        tools_fmtd = "\n".join([f" - {name}{sig}" for name, sig in tool_names_sigs])
        print(f"Tool options: \n {tools_fmtd}.")
        tool_name = input(f" [{self.role_type}] Tool function call > ")
        return InteractiveMessage(tool_call=tool_name)

    def user_tool_call_to_python_code(
        self, tool_call: str, available_tool_names: set[str]
    ) -> str:
        """Convert a tool call into an execution environment command."""
        return f"print(repr({tool_call}))"


class CliUser(CliRole):
    role_type: RoleType = RoleType.USER
    model_name = "cli_user"


class CliAgent(CliRole):
    role_type: RoleType = RoleType.AGENT
    model_name = "cli_agent"
