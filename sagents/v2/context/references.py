"""Pure durable-reference projection shared by context implementations."""

import json
from sagents.v2.contracts.items import TextBlock
from sagents.v2.model.contracts import ModelMessage


async def compact_unit_to_references(
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
        if len(replacement.model_dump_json()) < len(message.model_dump_json()):
            result.append(replacement)
            changed = True
        else:
            result.append(message)
    return tuple(result) if changed else None
