"""Shared tool units and default user-turn protection boundaries."""

from __future__ import annotations

from sagents.v2.contracts.conversation import is_tool_context, is_user_request


def conversation_units(messages):
    units = []
    index = 0
    while index < len(messages):
        message = messages[index]
        unit = [message]
        index += 1
        if message.role == "assistant" and message.tool_calls:
            expected = {call.tool_call_id for call in message.tool_calls}
            while index < len(messages) and messages[index].role == "tool":
                if messages[index].tool_call_id not in expected:
                    break
                unit.append(messages[index])
                index += 1
            while index < len(messages) and is_tool_context(messages[index]):
                source = messages[index].metadata.get("source_tool_call_id")
                if source is not None and source not in expected:
                    break
                unit.append(messages[index])
                index += 1
        units.append(tuple(unit))
    return units


def current_turn_boundary(units):
    return next(
        (
            index
            for index in range(len(units) - 1, -1, -1)
            if any(is_user_request(message) for message in units[index])
        ),
        max(0, len(units) - 1),
    )


def protected_boundary(units, costs, *, recent_units, recent_tokens):
    """Current turn is mandatory; older recent units consume a soft token budget."""
    mandatory = current_turn_boundary(units)
    boundary = mandatory
    used = 0
    for index in range(mandatory - 1, max(-1, len(units) - recent_units - 1), -1):
        if used + costs[index] > recent_tokens:
            break
        used += costs[index]
        boundary = index
    return boundary
