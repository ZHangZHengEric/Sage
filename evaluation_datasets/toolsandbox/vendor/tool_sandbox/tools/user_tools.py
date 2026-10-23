# For licensing see accompanying LICENSE file.
# Copyright (C) 2024 Apple Inc. All Rights Reserved.
"""A collection of tools dedicated for user access, mostly to support user simulation."""

import polars as pl

from tool_sandbox.common.execution_context import (
    DatabaseNamespace,
    RoleType,
    get_current_context,
)
from tool_sandbox.common.utils import register_as_tool


@register_as_tool(visible_to=(RoleType.USER,))
def end_conversation() -> None:
    """Finish the conversation

    Trigger this tool when you think the agent have completed the task for you,
    or the agent is unable to complete the task. Either way this tool will stop the conversation

    Returns:

    Raises:
        ValueError: If conversation already ended
    """
    current_context = get_current_context()
    sandbox_database = current_context.get_database(DatabaseNamespace.SANDBOX)
    if not sandbox_database["conversation_active"][-1]:
        raise ValueError("Conversation already ended")
    current_context.update_database(
        DatabaseNamespace.SANDBOX,
        dataframe=sandbox_database.with_columns(~pl.col("conversation_active")),
    )
