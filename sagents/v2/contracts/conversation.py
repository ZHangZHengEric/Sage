"""Semantic user boundaries and transport ordering for tool-provided context."""


def is_tool_context(message):
    # Recognize older persisted image followups as well as the explicit marker.
    return message.role == "user" and (
        message.metadata.get("tool_context") is True
        or message.metadata.get("tool_source") == "analyze_image"
    )


def is_user_request(message):
    return (
        message.role == "user"
        and not is_tool_context(message)
        and not message.metadata.get("runtime_continuation_guidance", False)
    )


def order_tool_context(messages):
    """Move supplemental context after its contiguous tool batch, including replay.

    Never cross a real user/assistant boundary or move an unrelated tool result.
    Incomplete pairs remain incomplete for the assembler to handle normally.
    """
    output = []
    index = 0
    while index < len(messages):
        message = messages[index]
        output.append(message)
        index += 1
        if message.role != "assistant" or not message.tool_calls:
            continue
        expected = {call.tool_call_id for call in message.tool_calls}
        results, followups = [], []
        while index < len(messages):
            candidate = messages[index]
            if candidate.role == "tool" and candidate.tool_call_id in expected:
                results.append(candidate)
            elif is_tool_context(candidate) and (
                candidate.metadata.get("source_tool_call_id") is None
                or candidate.metadata["source_tool_call_id"] in expected
            ):
                followups.append(candidate)
            else:
                break
            index += 1
        output.extend(results)
        output.extend(followups)
    return tuple(output)
