"""Keep a bounded view of the current execution segment's committed output."""

from collections.abc import Iterator
from contextlib import contextmanager

from sagents.v2.contracts.events import ItemEventData, RunEventData, RuntimeEvent
from sagents.v2.contracts.items import ItemSnapshot
from sagents.v2.runtime.session.subscriptions import observe_commits

_MAX_ITEMS = 32


class RunTraceOutput:
    def __init__(self, run_id: str):
        self.run_id = run_id
        self.items: dict[str, ItemSnapshot] = {}
        self.error = None
        self.active = True

    def record(self, run_id: str, events: tuple[RuntimeEvent, ...]) -> None:
        if not self.active or run_id != self.run_id:
            return
        for event in events:
            data = event.data
            if isinstance(data, ItemEventData) and data.item is not None:
                item = data.item
                self.items.pop(item.item_id, None)
                if len(self.items) >= _MAX_ITEMS:
                    del self.items[next(iter(self.items))]
                self.items[item.item_id] = item
            elif event.type == "run.failed" and isinstance(data, RunEventData):
                self.error = data.error


@contextmanager
def capture_run_trace_output(run_id: str, *, enabled: bool) -> Iterator[RunTraceOutput | None]:
    capture = RunTraceOutput(run_id) if enabled else None
    with observe_commits(capture.record if capture is not None else None):
        try:
            yield capture
        finally:
            if capture is not None:
                capture.active = False
