"""Select recent Session turns once at Run entry."""

from datetime import datetime
from typing import Mapping

from sagents.v2.model import ModelMessage


class RecentRunHistoryWindow:
    plugin_id = "sage.context.history-window.recent"
    name = "Recent Run history window"
    description = "Selects complete prior user turns by age or turn count at Run entry."

    def __init__(
        self,
        *,
        max_age_seconds: int | None = None,
        max_turns: int | None = None,
    ) -> None:
        if any(value is not None and value < 1 for value in (max_age_seconds, max_turns)):
            raise ValueError("history window limits must be positive")
        self.max_age_seconds = max_age_seconds
        self.max_turns = max_turns

    def history_start(
        self,
        messages: tuple[ModelMessage, ...],
        *,
        accepted_at: datetime,
        item_times: Mapping[str, datetime],
    ) -> int:
        if self.max_turns is None and self.max_age_seconds is None:
            return 0

        # The loop records one Turn per source Run. Multiple input items and
        # steering messages belong to that same Turn.
        bounds: dict[str, tuple[int, int]] = {}
        for index, message in enumerate(messages):
            run_id = message.metadata.get("source_run_id") or message.metadata.get("run_id")
            if isinstance(run_id, str):
                first, _ = bounds.get(run_id, (index, index))
                bounds[run_id] = (first, index)

        turns = list(bounds.values())
        turn_start = 0
        if self.max_turns is not None and len(turns) > self.max_turns:
            turn_start = turns[-self.max_turns][0]

        age_start = 0
        if self.max_age_seconds is not None and turns:
            age_start = len(messages)
            for index, _ in reversed(turns):
                item_id = messages[index].metadata.get("source_item_id")
                occurred_at = item_times.get(item_id) if isinstance(item_id, str) else None
                if (
                    occurred_at is not None
                    and (accepted_at - occurred_at).total_seconds() > self.max_age_seconds
                ):
                    break
                age_start = index
        start = max(turn_start, age_start)
        # Published concurrent Runs can have interleaved events. Advance past
        # every Turn that crosses the cut so its remaining items stay together.
        for first, last in turns:
            if first >= start:
                break
            start = max(start, last + 1)
        return start
