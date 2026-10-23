# For licensing see accompanying LICENSE file.
# Copyright (C) 2024 Apple Inc. All Rights Reserved.
"""Base class for all Roles"""

from logging import getLogger
from typing import Any, Callable, Optional, cast

import attrs
import polars as pl

from tool_sandbox.common.execution_context import (
    DatabaseNamespace,
    RoleType,
    get_current_context,
)
from tool_sandbox.common.message_conversion import Message

LOGGER = getLogger(__name__)


class BaseRole:
    """Base class for all roles. A role is an object that can read and write messages from execution context.
    A role could be a dialog agent, a user simulator, a code execution environment and more.

    At this point roles are designed to be stateless. State representations are stored in execution context database
    """

    role_type: Optional[RoleType] = None

    @staticmethod
    def get_messages(ending_index: Optional[int] = None) -> list[Message]:
        """Access database to get all current historical messages

        Args:
            ending_index:   Optional index to provide get_messages. Will truncate message history till ending_index
                            if provided. Utility for processing system message, which could contain multiple entries
                            before each was responded to

        Returns:
            List of Message object
        """
        current_context = get_current_context()
        sandbox_database = current_context.get_database(
            namespace=DatabaseNamespace.SANDBOX,
            get_all_history_snapshots=True,
            drop_sandbox_message_index=False,
        )
        if ending_index is not None:
            sandbox_database = sandbox_database.filter(
                pl.col("sandbox_message_index") <= ending_index
            )
        # Cast str back to enum
        return [
            Message(**row)
            for row in sandbox_database.drop("sandbox_message_index").to_dicts()
        ]

    @staticmethod
    def add_messages(messages: list[Message]) -> None:
        """Add a list of Messages to database

        Args:
            messages:   Messages to be added to the database

        Returns:

        """
        current_context = get_current_context()
        current_context.add_to_database(
            namespace=DatabaseNamespace.SANDBOX,
            rows=[attrs.asdict(x) for x in messages],
        )

    @classmethod
    def messages_validation(cls, messages: list[Message]) -> None:
        """Verify if the messages are valid.

            Criteria include:
            1. The last message should be addressed to this role_type

        Args:
            messages:   List of message to be validated

        Returns:

        Raises:
            KeyError:   When the last message is not directed to this role

        """
        if messages[-1].recipient != cls.role_type:
            raise KeyError(
                f"The last message should be addressed to {cls.role_type}, found {messages[-1].recipient}"
            )

    @classmethod
    def filter_messages(cls, messages: list[Message]) -> list[Message]:
        """Filter messages, keeping only messages addressed to or sent by this role

        Args:
            messages:   List of message to be filtered

        Returns:
            A List of filtered messages
        """
        return [
            message
            for message in messages
            if cls.role_type in cast(list[RoleType], message.visible_to)
        ]

    @classmethod
    def get_available_tools(cls) -> dict[str, Callable[..., Any]]:
        """Get the available tools for this role."""
        name_to_tool = get_current_context().get_available_tools(
            scrambling_allowed=cls.role_type == RoleType.AGENT
        )
        return {
            name: tool
            for name, tool in name_to_tool.items()
            if cls.role_type in getattr(tool, "visible_to", (RoleType.AGENT,))
        }

    def reset(self) -> None:
        """Reset any state of the agent."""
        # By default doesn't do anything.
        pass

    def teardown(self) -> None:
        """Clean up the agent and free resources."""
        pass

    def respond(self, ending_index: Optional[int] = None) -> None:
        """Reads a List of messages and attempt to respond with a Message

        System is considered a special role, where roles won't respond back to System when System sends a message.
        How roles deal with system message can vary depending on the role

        Message comes from current context, the last k messages should be directed to this role type
        Response are written to current context as well. k new messages, addressed to appropriate recipient

        Args:
            ending_index:   Optional index. Will respond to message located at ending_index instead of most recent one
                            if provided. Utility for processing system message, which could contain multiple entries
                            before each was responded to

        Raises:
            KeyError:   When the last message is not directed to this role
        """
        raise NotImplementedError
