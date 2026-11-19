"""Pure durable-reference projection shared by context implementations."""

import json

from sagents.v2.concurrency import bounded_to_thread
from sagents.v2.contracts.items import JsonBlock, TextBlock
from sagents.v2.model.contracts import ModelMessage


async def compact_units_to_references(
    units: list[tuple[ModelMessage, ...]],
) -> tuple[tuple[ModelMessage, ...] | None, ...]:
    if not any(
        message.role == "tool"
        and isinstance(message.metadata.get("context_reference"), (dict, str))
        for unit in units
        for message in unit
    ):
        return ()

    def project():
        return tuple(_compact_references(unit) for unit in units)

    return await bounded_to_thread("context-cpu", project)


def _content_exceeds(message: ModelMessage, length: int) -> bool:
    # JSON string encoding can add escapes, but cannot make the encoded
    # string shorter than its source. Skip serializing an oversized body.
    for block in message.content:
        if isinstance(block, TextBlock) and len(block.text) > length:
            return True
        if isinstance(block, JsonBlock) and isinstance(block.value, dict):
            if any(
                isinstance(value, str) and len(value) > length
                for value in block.value.values()
            ):
                return True
    return False


def _compact_references(
    unit: tuple[ModelMessage, ...],
) -> tuple[ModelMessage, ...] | None:
    result = []
    changed = False
    for message in unit:
        reference = message.metadata.get("context_reference")
        if message.role != "tool" or not isinstance(reference, (dict, str)):
            result.append(message)
            continue
        encoded = json.dumps(
            reference,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        replacement = message.model_copy(
            update={
                "content": (
                    TextBlock(
                        text=(
                            f"<tool_result_reference>{encoded}</tool_result_reference>"
                        )
                    ),
                ),
                "metadata": {
                    **message.metadata,
                    "context_compacted_to_reference": True,
                },
            }
        )
        replacement_length = len(replacement.model_dump_json())
        if _content_exceeds(message, replacement_length) or replacement_length < len(
            message.model_dump_json()
        ):
            result.append(replacement)
            changed = True
        else:
            result.append(message)
    return tuple(result) if changed else None
