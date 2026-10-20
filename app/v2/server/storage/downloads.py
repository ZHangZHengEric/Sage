"""Read workspace files and build temporary downloads without following symlinks."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import os
import json
from urllib.parse import quote
from pathlib import Path, PurePosixPath
import stat
from tempfile import SpooledTemporaryFile
from zipfile import ZipFile, ZIP_DEFLATED

MAX_ARCHIVE_BYTES = 1024 * 1024 * 1024
MAX_ARCHIVE_ENTRIES = 20000


def relative_path(value: str) -> PurePosixPath:
    # UI tree entries remain relative. Also accept paths returned by Server
    # tools; resolve the mount alias only within the already authorized root.
    if value == "/workspace":
        value = ""
    elif value.startswith("/workspace/"):
        value = value[len("/workspace/"):]
    path = PurePosixPath(value or ".")
    if path.is_absolute() or ".." in path.parts or "\\" in value or "\0" in value:
        raise ValueError("invalid workspace path")
    return path


@contextmanager
def open_entry(root: Path, path: PurePosixPath):
    """Open each component relative to its parent fd; reject symlink swaps."""
    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for index, part in enumerate(path.parts):
            flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
            if index < len(path.parts) - 1:
                flags |= os.O_DIRECTORY
            child = os.open(part, flags, dir_fd=fd)
            os.close(fd)
            fd = child
        if not (stat.S_ISDIR(os.fstat(fd).st_mode) or stat.S_ISREG(os.fstat(fd).st_mode)):
            raise ValueError("unsupported file type")
        yield fd
    finally:
        os.close(fd)


def list_directory(root: Path, value: str) -> list[dict]:
    path = relative_path(value)
    with open_entry(root, path) as fd:
        if not stat.S_ISDIR(os.fstat(fd).st_mode):
            raise NotADirectoryError(value)
        items = []
        with os.scandir(fd) as entries:
            for entry in entries:
                info = entry.stat(follow_symlinks=False)
                if not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)):
                    continue
                items.append({
                    "name": entry.name, "path": (path / entry.name).as_posix(),
                    "is_directory": stat.S_ISDIR(info.st_mode), "size": info.st_size,
                    "modified_at": datetime.fromtimestamp(info.st_mtime, timezone.utc).isoformat(),
                })
                if len(items) > MAX_ARCHIVE_ENTRIES:
                    raise OverflowError("too many files in directory")
        return sorted(items, key=lambda item: (not item["is_directory"], item["name"].casefold()))


class SnapshotChangedError(ValueError):
    """The workspace changed while a download was being assembled."""


def prepare_download(root: Path, value: str, *, archive_name: str = "workspace",
                     max_bytes: int = MAX_ARCHIVE_BYTES, max_entries: int = MAX_ARCHIVE_ENTRIES):
    path = relative_path(value)
    output = SpooledTemporaryFile(max_size=8 * 1024 * 1024, mode="w+b")
    try:
        with open_entry(root, path) as fd:
            if stat.S_ISREG(os.fstat(fd).st_mode):
                if os.fstat(fd).st_size > max_bytes:
                    raise OverflowError("file is too large to download")
                with os.fdopen(os.dup(fd), "rb") as source:
                    remaining = os.fstat(fd).st_size
                    while remaining:
                        chunk = source.read(min(remaining, 1024 * 1024))
                        if not chunk:
                            break
                        output.write(chunk)
                        remaining -= len(chunk)
                filename = path.name
            else:
                filename = f"{path.name or archive_name}.zip"
                total = [0, 0]
                with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
                    _archive_directory(fd, archive, path.name or archive_name, total,
                                       max_bytes=max_bytes, max_entries=max_entries)
        output.seek(0)
        return output, filename
    except BaseException:
        output.close()
        raise


def _archive_directory(fd: int, archive: ZipFile, prefix: str, total: list[int],
                       *, max_bytes: int = MAX_ARCHIVE_BYTES,
                       max_entries: int = MAX_ARCHIVE_ENTRIES):
    total[0] += 1
    if total[0] > max_entries:
        raise OverflowError("directory is too large to archive")
    archive.writestr(f"{prefix}/", b"")
    with os.scandir(fd) as entries:
        for entry in entries:
            info = entry.stat(follow_symlinks=False)
            if not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)):
                continue
            child = os.open(entry.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
            try:
                opened = os.fstat(child)
                name = f"{prefix}/{entry.name}"
                if stat.S_ISDIR(opened.st_mode):
                    _archive_directory(child, archive, name, total,
                                       max_bytes=max_bytes, max_entries=max_entries)
                elif stat.S_ISREG(opened.st_mode):
                    total[0] += 1
                    total[1] += opened.st_size
                    if total[0] > max_entries or total[1] > max_bytes:
                        raise OverflowError("directory is too large to archive")
                    with os.fdopen(os.dup(child), "rb") as source, archive.open(name, "w") as target:
                        # Reject files changed during this snapshot; the caller
                        # may retry after the Agent finishes writing.
                        remaining = opened.st_size
                        while remaining:
                            chunk = source.read(min(remaining, 1024 * 1024))
                            if not chunk:
                                break
                            target.write(chunk)
                            remaining -= len(chunk)
                    after = os.fstat(child)
                    if (remaining or opened.st_size != after.st_size
                            or opened.st_mtime_ns != after.st_mtime_ns
                            or opened.st_ctime_ns != after.st_ctime_ns):
                        raise SnapshotChangedError("file changed while creating workspace snapshot")
            finally:
                os.close(child)


def prepare_session_export(session_id: str, run_ids: set[str], evidence: dict | None = None):
    """Package observation evidence; the Run allowlist contains no business state."""
    from app.v2.server.observability.diagnostics import redact

    evidence = redact(evidence or {"models": [], "logs": [], "unavailable": True})
    pending_writes = bool(evidence.get("pending_writes"))
    name = quote(session_id, safe="")
    if name in {"", ".", ".."}:
        raise ValueError("invalid Session id")
    output = SpooledTemporaryFile(max_size=8 * 1024 * 1024, mode="w+b")
    total = 0
    try:
        with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:

            def write_json(path, value):
                nonlocal total
                encoded = json.dumps(value, ensure_ascii=False, indent=2).encode(
                    "utf-8"
                )
                total += len(encoded)
                if (
                    total > MAX_ARCHIVE_BYTES
                    or len(archive.filelist) >= MAX_ARCHIVE_ENTRIES
                ):
                    raise OverflowError("Session is too large to archive")
                archive.writestr(f"{name}/{path}", encoded)

            tools = evidence.get("tools", [])
            failures = evidence.get("failures", [])
            models = sorted(evidence.get("models", []), key=lambda row: (row.get("started_at", ""), row.get("request_id", "")))
            requests_index = []
            for sequence, row in enumerate(models, 1):
                row["sequence"] = sequence
                path = f"requests/{sequence:06d}-{quote(str(row.get('request_id', 'unknown')), safe='')}.json"
                write_json(path, row)
                requests_index.append({key: row.get(key) for key in (
                    "sequence", "run_id", "request_id", "step_id", "purpose", "started_at", "completed_at", "status"
                )} | {"path": path})
            write_json("requests/index.json", requests_index)
            captured_ids = {row.get("request_id") for row in models}
            expected_ids = {row.get("request_id") for row in evidence.get("logs", [])
                            if row.get("event") == "model.request.started" and row.get("request_id")}
            missing_requests = sorted(expected_ids - captured_ids)
            write_json("models.json", models)
            write_json("logs.json", evidence.get("logs", []))
            if "traces" in evidence:
                write_json("traces.json", evidence["traces"])
            write_json("tools.json", tools)
            write_json("failures.json", failures)
            write_json(
                "manifest.json",
                {
                    "format_version": "sage.session-diagnostic-bundle/v2",
                    "session_id": session_id,
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                    "redacted": True,
                    "diagnostic_source": evidence.get("source", "local"),
                    "external_traces_truncated": evidence.get("truncated", False),
                    "raw_model_streams_available": evidence.get("raw_model_streams_available", any(
                        row.get("stream", {}).get("wire_capture_available") for row in models
                    )),
                    "restorable_backup": False,
                    "diagnostic_storage_available": not evidence.get(
                        "unavailable", False
                    ),
                    "run_ids": sorted(run_ids),
                    "model_records": len(models),
                    "model_request_ids_missing": missing_requests,
                    "model_request_coverage": "external_traces_only" if "traces" in evidence else ("incomplete" if missing_requests or evidence.get("dropped_logs", 0) or evidence.get("unavailable") else "matched_captured_start_logs"),
                    "unfinished_model_request_ids": [row.get("request_id") for row in models if row.get("status") == "started"],
                    "stream_evidence_missing_for_requests": [row.get("request_id") for row in models if not row.get("stream", {}).get("wire_capture_available")],
                    "stream_events_dropped": sum(row.get("stream", {}).get("dropped_wire_events", 0) + row.get("stream", {}).get("dropped_normalized_events", 0) for row in models),
                    "log_records": len(evidence.get("logs", [])),
                    "tool_records": len(tools),
                    "tool_results_available": evidence.get("tool_results_available", False),
                    "tool_results_missing": [
                        {"run_id": row["run_id"], "tool_call_id": row["tool_call_id"]}
                        for row in tools if not row.get("result_available")
                    ],
                    "tool_failures": len(failures),
                    "tool_failures_without_stack_trace": [
                        {"run_id": row["run_id"], "tool_call_id": row["tool_call_id"]}
                        for row in failures if not row["stack_trace_available"]
                    ],
                    "truncated_model_records": sum(
                        bool(row.get("truncated")) for row in evidence.get("models", [])
                    ),
                    "truncated_log_records": sum(
                        bool(row.get("truncated")) for row in evidence.get("logs", [])
                    ),
                    "dropped_logs": evidence.get("dropped_logs", 0),
                    "diagnostic_writes_pending": pending_writes,
                    "capture_failures_since_start": evidence.get(
                        "capture_failures_since_start", 0
                    ),
                    "models_missing_for_runs": sorted(
                        run_ids
                        - {row.get("run_id") for row in evidence.get("models", [])}
                    ),
                    "logs_missing_for_runs": sorted(
                        run_ids
                        - {row.get("run_id") for row in evidence.get("logs", [])}
                    ),
                    "limitations": [
                        "Historical evidence not captured before diagnostics were enabled is unavailable.",
                        "Model responses are normalized; stream.wire_events contains SDK-decoded provider events when capture is available, not HTTP bytes. requests/index.json lists chronological attempts.",
                        "Only logs with an exact Session and Run association are included.",
                        "Credential fields and recognizable inline secrets are redacted; review unlabelled prose before sharing.",
                        "Observation delivery is asynchronous and best effort; missing records are not reconstructed from business state.",
                    ],
                },
            )
        output.seek(0)
        return output, f"{name}-diagnostics.zip"
    except BaseException:
        output.close()
        raise
