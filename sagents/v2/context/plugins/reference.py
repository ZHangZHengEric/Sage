"""Reference-only compaction for oversized indivisible context units."""

from __future__ import annotations

import json

from sagents.v2.context.plugins.estimator_json import JsonHeuristicTokenEstimator
from sagents.v2.context.token_estimator import TokenEstimator
from sagents.v2.contracts.items import TextBlock
from sagents.v2.model.contracts import ModelMessage


class ReferenceContextUnitCompactor:
    """Use a Tool-provided durable reference; never truncate arbitrary text."""

    plugin_id = "sage.context.unit-compactor.reference"

    def __init__(self, estimator: TokenEstimator | None = None) -> None:
        self.estimator = estimator or JsonHeuristicTokenEstimator()

    async def compact(
        self, unit: tuple[ModelMessage, ...]
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
                                "<tool_result_reference>"
                                f"{encoded}"
                                "</tool_result_reference>"
                            )
                        ),
                    ),
                    "metadata": {
                        **message.metadata,
                        "context_compacted_to_reference": True,
                    },
                }
            )
            if self.estimator.estimate((replacement,)) < self.estimator.estimate(
                (message,)
            ):
                result.append(replacement)
                changed = True
            else:
                result.append(message)
        return tuple(result) if changed else None


__all__ = ["ReferenceContextUnitCompactor"]
