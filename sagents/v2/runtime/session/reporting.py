"""Content-free replay of committed Run and execution events for host reports."""

from dataclasses import dataclass, field
from datetime import datetime, timezone

from sagents.v2.contracts.common import sortable_id_prefix
from sagents.v2.runtime.session.run_metadata import RunMetadata, metadata_from_run

TOOL_STATES = {
    "tool.call.started": "started",
    "tool.call.succeeded": "succeeded",
    "tool.call.failed": "failed",
    "tool.call.cancelled": "cancelled",
    "tool.call.unknown": "unknown",
    "tool.call.reconciled": "reconciled",
}
REPORT_EVENTS = (*TOOL_STATES, "usage.recorded")
TOKEN_FIELDS = ("input_tokens", "output_tokens", "cached_input_tokens", "reasoning_tokens")


def run_id_range(start: float, end: float) -> tuple[str, str]:
    return (
        sortable_id_prefix("run", datetime.fromtimestamp(start, timezone.utc)),
        sortable_id_prefix("run", datetime.fromtimestamp(end, timezone.utc)),
    )


@dataclass
class RunBusinessFacts:
    metadata: RunMetadata
    tools: dict[tuple, str] = field(default_factory=dict)
    started_tools: dict[tuple, str] = field(default_factory=dict)
    tokens: dict[str, int] = field(default_factory=lambda: dict.fromkeys(TOKEN_FIELDS, 0))
    event_count: int = 0
    usage_records: int = 0
    reported_usage_records: int = 0
    events_complete: bool = True
    _sequence: int = 0

    def record(self, sequence, event, tool_id=None, usage=None, *, operation_id=None, step_id=None):
        if sequence <= self._sequence:
            return
        self._sequence = sequence
        self.event_count += 1
        if event == "usage.recorded" and usage is not None:
            self.usage_records += 1
            self.reported_usage_records += int(usage.get("reported", False))
            for name in TOKEN_FIELDS:
                self.tokens[name] += usage.get(name, 0)
        elif tool_id and event in TOOL_STATES:
            identity = (operation_id,) if operation_id else (step_id, tool_id)
            self.tools[identity] = TOOL_STATES[event]
            if event == "tool.call.started":
                self.started_tools[identity] = tool_id


@dataclass
class BusinessReplay:
    runs: dict[tuple[str, str], RunBusinessFacts] = field(default_factory=dict)
    cohort_truncated: bool = False
    archive_pending: bool = False

    @property
    def events_truncated(self) -> bool:
        return any(not run.events_complete for run in self.runs.values())


async def replay_session_views(store, candidates, *, start, end, agent_id, max_runs, max_events):
    """Read already-scoped Run views in bounded groups for local stores."""
    report = BusinessReplay(cohort_truncated=len(candidates) > max_runs)
    candidates = candidates[:max_runs]
    remaining = max_events
    for offset in range(0, len(candidates), 100):
        batch = candidates[offset : offset + 100]
        ids = {rid for _, rid in batch}
        views = await store.read_session_views(
            {sid for sid, _ in batch}, include_events=remaining > 0, run_ids=ids,
        )
        for sid, view in views.items():
            for entry in view.runs:
                metadata = metadata_from_run(entry.run, entry.command)
                if metadata.run_id not in ids or not start <= metadata.created_at.timestamp() < end:
                    continue
                if agent_id and metadata.agent_id != agent_id:
                    continue
                facts = RunBusinessFacts(metadata)
                report.runs[sid, metadata.run_id] = facts
                relevant = [event for event in entry.events if event.type in REPORT_EVENTS]
                if not remaining or len(relevant) > remaining:
                    facts.events_complete = False
                    remaining = 0
                    continue
                remaining -= len(relevant)
                for event in relevant:
                    data = event.data
                    usage = data.usage.model_dump(include={"reported", *TOKEN_FIELDS}) if data.kind == "usage" else None
                    facts.record(
                        event.run_sequence, event.type, getattr(data, "tool_call_id", None), usage,
                        operation_id=getattr(data, "operation_id", None), step_id=event.step_id,
                    )
    return report
