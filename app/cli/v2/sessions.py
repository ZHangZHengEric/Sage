"""列出某个 session root 下的 v2 会话（只读，不取 SessionStore 的写锁）。

v2 明确不提供全局会话索引（README："Listing … belongs to the embedding application"），
而 v4 的 `FilesystemSessionStore` 是单写者：另一个 `sage v2` 进程在跑时不能再打开它。
因此列表直接读每个会话目录的权威数据：`state.json` 压缩基线 + `journal.jsonl` 增量，
用运行时公开的 `SessionAggregate.apply` 叠加——`run.json`/`session.json` 只是可能滞后的投影。
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from sagents.v2.contracts.commands import StartRun
from sagents.v2.contracts.events import RuntimeEvent
from sagents.v2.contracts.items import MessageItemData, TextBlock
from sagents.v2.runtime.extensions import ExtensionScope, ExtensionScopeContext
from sagents.v2.runtime.extensions.official import builtin_extension_registry
from sagents.v2.runtime.session import SessionStore
from sagents.v2.runtime.session.aggregate import SessionAggregate
from sagents.v2.runtime.session.journal import (
    RunRowSnapshot,
    SessionAggregateSnapshotV2,
    SessionMutationEnvelope,
    SessionSnapshotEnvelope,
)

SESSION_STORE_PLUGIN = "sage.session.filesystem"
SESSION_DIR_PREFIX = "session_"


@dataclass(frozen=True)
class SessionSummary:
    session_id: str
    created_at: datetime
    updated_at: datetime
    run_count: int
    last_run_id: str | None
    last_state: str | None
    agent_id: str | None
    task: str
    workspace: str | None
    package_id: str | None

    def to_json(self) -> dict[str, Any]:
        value = asdict(self)
        value["created_at"] = self.created_at.isoformat()
        value["updated_at"] = self.updated_at.isoformat()
        return value


def open_session_store(session_root: str | Path) -> SessionStore:
    """用与 ``SAgentBuilder`` 相同的插件打开文件系统 SessionStore（会取写锁）。"""

    registration = builtin_extension_registry().get(SESSION_STORE_PLUGIN)
    return registration.factory(
        ExtensionScopeContext(
            scope=ExtensionScope.PROCESS,
            scope_id="sage-cli-v2-sessions",
            config={"root": str(Path(session_root).expanduser())},
        ),
        {},
    )


def discover_session_dirs(session_root: str | Path) -> list[Path]:
    sessions_dir = Path(session_root).expanduser() / "sessions"
    if not sessions_dir.is_dir():
        return []
    return sorted(
        entry
        for entry in sessions_dir.iterdir()
        if entry.is_dir() and entry.name.startswith(SESSION_DIR_PREFIX)
    )


def discover_session_ids(session_root: str | Path) -> list[str]:
    return [entry.name for entry in discover_session_dirs(session_root)]


def read_session_aggregate(session_dir: Path) -> SessionAggregateSnapshotV2:
    """只读地重建一个会话的权威聚合：v4 基线 + 尚未压缩进基线的 journal 增量。

    与 store 的 ``_read_session_aggregate`` 同一套规则：忽略不完整的 journal 尾行，
    跳过基线已包含的旧修订，要求修订连续。不校验 checksum（列表是只读的尽力读取）。
    """

    envelope = SessionSnapshotEnvelope.model_validate_json(
        (session_dir / "state.json").read_bytes()
    )
    aggregate = SessionAggregate(envelope.state)
    revision = envelope.current_session_revision
    journal = session_dir / "journal.jsonl"
    if not journal.exists():
        return aggregate.snapshot
    lines = journal.read_bytes().splitlines(keepends=True)
    for index, line in enumerate(lines):
        if not line.endswith(b"\n"):
            if index != len(lines) - 1:
                raise ValueError("journal contains an incomplete middle record")
            break
        mutation = SessionMutationEnvelope.model_validate_json(line)
        if mutation.current_session_revision <= revision:
            continue
        if mutation.previous_session_revision != revision:
            raise ValueError("journal is not revision-contiguous")
        aggregate = aggregate.apply(mutation.mutation)
        revision = mutation.current_session_revision
    return aggregate.snapshot


def start_command_task(command: StartRun) -> str:
    for item in command.input:
        if item.role != "user":
            continue
        text = " ".join(
            block.text for block in item.content if isinstance(block, TextBlock)
        ).strip()
        if text:
            return text
    return ""


def summarize_aggregate(snapshot: SessionAggregateSnapshotV2) -> SessionSummary:
    if len(snapshot.sessions) != 1:
        raise ValueError("session aggregate must contain exactly one Session")
    session = snapshot.sessions[0]
    runs: list[RunRowSnapshot] = sorted(
        snapshot.runs, key=lambda run: (run.created_at, run.run_id)
    )
    task = ""
    agent_id = None
    workspace = None
    package_id = None
    first_command = next((run.start_command for run in runs if run.start_command), None)
    if first_command is not None:
        task = start_command_task(first_command)
        agent_id = first_command.agent_id
        metadata = first_command.config.metadata
        workspace = metadata.get("workspace") or None
        package_id = metadata.get("package_id") or None
    last = runs[-1] if runs else None
    return SessionSummary(
        session_id=session.session_id,
        created_at=session.created_at,
        updated_at=max((run.updated_at for run in runs), default=session.updated_at),
        run_count=len(runs),
        last_run_id=last.run_id if last else None,
        last_state=last.state.value if last else None,
        agent_id=agent_id,
        task=task,
        workspace=workspace,
        package_id=package_id,
    )


async def list_sessions(
    session_root: str | Path,
    *,
    limit: int | None = None,
) -> tuple[list[SessionSummary], list[str]]:
    """返回按最近活动倒序的会话摘要，以及无法读取的 session id。"""

    summaries: list[SessionSummary] = []
    unreadable: list[str] = []
    for session_dir in discover_session_dirs(session_root):
        try:
            snapshot = await asyncio.to_thread(read_session_aggregate, session_dir)
            summaries.append(summarize_aggregate(snapshot))
        except Exception:  # noqa: BLE001 - 单个损坏会话不该让整个列表失败
            unreadable.append(session_dir.name)
    summaries.sort(key=lambda value: value.updated_at, reverse=True)
    if limit is not None:
        summaries = summaries[:limit]
    return summaries, unreadable


def format_sessions_table(summaries: list[SessionSummary], *, task_width: int = 60) -> str:
    if not summaries:
        return "no v2 sessions found"
    lines = []
    for value in summaries:
        task = value.task.replace("\n", " ")
        if len(task) > task_width:
            task = task[: task_width - 1] + "…"
        lines.append(
            f"{value.session_id}  {value.updated_at.strftime('%Y-%m-%d %H:%M')}  "
            f"runs={value.run_count}  last={value.last_state or '-'}  "
            f"agent={value.agent_id or '-'}  {task}"
        )
    return "\n".join(lines)


def sessions_json(
    session_root: str | Path,
    summaries: list[SessionSummary],
    unreadable: list[str],
) -> str:
    return json.dumps(
        {
            "session_root": str(session_root),
            "total": len(summaries),
            "unreadable": unreadable,
            "list": [value.to_json() for value in summaries],
        },
        ensure_ascii=False,
    )


@dataclass(frozen=True)
class TranscriptEntry:
    kind: str  # "user" | "assistant" | "tool" | "interaction"
    text: str
    detail: str | None = None

    def to_json(self) -> dict[str, Any]:
        value = {"kind": self.kind, "text": self.text}
        if self.detail is not None:
            value["detail"] = self.detail
        return value


@dataclass(frozen=True)
class RunTranscript:
    run_id: str
    state: str
    invocation_mode: str | None
    created_at: datetime
    updated_at: datetime
    entries: tuple[TranscriptEntry, ...]

    def to_json(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "state": self.state,
            "invocation_mode": self.invocation_mode,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "entries": [entry.to_json() for entry in self.entries],
        }


@dataclass(frozen=True)
class SessionTranscript:
    summary: SessionSummary
    runs: tuple[RunTranscript, ...]

    def to_json(self) -> dict[str, Any]:
        return {
            "session": self.summary.to_json(),
            "runs": [run.to_json() for run in self.runs],
        }


def _message_text(data: MessageItemData) -> str:
    return "".join(block.text for block in data.content if isinstance(block, TextBlock))


def transcript_entries(
    command: StartRun | None, events: tuple[RuntimeEvent, ...]
) -> tuple[TranscriptEntry, ...]:
    """从一个 Run 的 durable 事件重建对话：用户输入、assistant 消息、工具终态、交互。"""

    entries: list[TranscriptEntry] = []
    if command is not None:
        task = start_command_task(command)
        if task:
            entries.append(TranscriptEntry("user", task))
    for event in events:
        data = event.data
        if event.type == "message.completed":
            item = getattr(data, "item", None)
            payload = getattr(item, "data", None)
            if isinstance(payload, MessageItemData) and payload.role == "assistant":
                text = _message_text(payload)
                if text:
                    entries.append(TranscriptEntry("assistant", text))
        elif event.type == "item.completed":
            item = getattr(data, "item", None)
            payload = getattr(item, "data", None)
            # 用户输入以 user 消息项落账；StartRun 之外的用户输入（如 steer）也在这里。
            if isinstance(payload, MessageItemData) and payload.role == "user":
                text = _message_text(payload)
                if text and (command is None or text != start_command_task(command)):
                    entries.append(TranscriptEntry("user", text))
        elif data.kind == "tool" and event.type in {
            "tool.call.succeeded",
            "tool.call.failed",
            "tool.call.cancelled",
        }:
            detail = None
            if data.error is not None:
                detail = f"{data.error.code}: {data.error.message}"
            outcome = event.type.rsplit(".", 1)[-1]  # succeeded / failed / cancelled
            entries.append(TranscriptEntry("tool", f"{data.tool_name} {outcome}", detail))
        elif event.type == "interaction.resolved":
            entries.append(
                TranscriptEntry(
                    "interaction",
                    f"{data.interaction_type} -> {data.decision}",
                    str(data.payload.get("tool_name") or data.payload.get("prompt") or "")
                    or None,
                )
            )
    return tuple(entries)


def inspect_session(session_root: str | Path, session_id: str) -> SessionTranscript:
    """只读地重建一个会话的完整转录（与 ``list_sessions`` 同一份权威聚合）。"""

    session_dir = Path(session_root).expanduser() / "sessions" / session_id
    if not (session_dir / "state.json").is_file():
        raise FileNotFoundError(f"v2 session {session_id!r} was not found under {session_root}")
    snapshot = read_session_aggregate(session_dir)
    summary = summarize_aggregate(snapshot)
    runs = sorted(snapshot.runs, key=lambda run: (run.created_at, run.run_id))
    transcripts = tuple(
        RunTranscript(
            run_id=run.run_id,
            state=run.state.value,
            invocation_mode=(
                run.start_command.invocation_mode if run.start_command else None
            ),
            created_at=run.created_at,
            updated_at=run.updated_at,
            entries=transcript_entries(
                run.start_command, snapshot.run_events.get(run.run_id, ())
            ),
        )
        for run in runs
    )
    return SessionTranscript(summary=summary, runs=transcripts)


def format_transcript(transcript: SessionTranscript) -> str:
    summary = transcript.summary
    lines = [
        f"session {summary.session_id}  created {summary.created_at:%Y-%m-%d %H:%M}  "
        f"updated {summary.updated_at:%Y-%m-%d %H:%M}  runs={summary.run_count}"
    ]
    if summary.workspace:
        lines.append(f"workspace: {summary.workspace}")
    for index, run in enumerate(transcript.runs, start=1):
        mode = f" mode={run.invocation_mode}" if run.invocation_mode else ""
        lines.append(f"--- run {index} {run.run_id}  state={run.state}{mode}")
        for entry in run.entries:
            if entry.kind == "user":
                lines.append(f"> {entry.text}")
            elif entry.kind == "assistant":
                lines.append(entry.text)
            elif entry.kind == "tool":
                suffix = f" ({entry.detail})" if entry.detail else ""
                lines.append(f"[tool] {entry.text}{suffix}")
            else:
                suffix = f" ({entry.detail})" if entry.detail else ""
                lines.append(f"[interaction] {entry.text}{suffix}")
    return "\n".join(lines)
