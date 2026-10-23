# For licensing see accompanying LICENSE file.
# Copyright (C) 2024 Apple Inc. All Rights Reserved.
"""Implementation of an agent that is not able to perform any task."""

from typing import Optional

from tool_sandbox.common.execution_context import RoleType
from tool_sandbox.common.message_conversion import Message
from tool_sandbox.roles.base_role import BaseRole


class UnhelpfulAgent(BaseRole):
    """An unhelpful agent that is not able to complete tasks.

    It is meant to enable measuring the performance across all scenarios for an agent
    that is generally non-functioning. This is useful to set the similarity score for
    actual agents into perspective.
    """

    role_type: RoleType = RoleType.AGENT

    def respond(self, ending_index: Optional[int] = None) -> None:
        """Reads a List of messages and attempt to respond with a Message

        Args:
            ending_index:   Optional index. Will respond to message located at ending_index instead of most recent one
                            if provided. Utility for processing system message, which could contain multiple entries
                            before each was responded to

        Raises:
            KeyError:   When the last message is not directed to this role
        """
        response_message = Message(
            sender=self.role_type,
            recipient=RoleType.USER,
            content="I am sorry, but I cannot assist with that.",
        )
        self.add_messages([response_message])
