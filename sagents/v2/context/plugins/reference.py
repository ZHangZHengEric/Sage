"""Reference-only compaction for oversized indivisible context units."""

from __future__ import annotations

from sagents.v2.context.references import compact_unit_to_references


class ReferenceContextUnitCompactor:
    """Use a Tool-provided durable reference; never truncate arbitrary text."""

    plugin_id = "sage.context.unit-compactor.reference"
    name = "Durable-reference context unit compactor"
    description = (
        "Compacts oversized units into durable references instead of dropping them."
    )

    async def compact(self, unit):
        return await compact_unit_to_references(unit)


__all__ = ["ReferenceContextUnitCompactor"]
