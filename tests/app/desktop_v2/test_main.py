from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from app.desktop_v2.backend.main import (
    _create_after_writer_release,
    _publish_sidecar,
    _remove_owned_sidecar_registry,
    _require_loopback_host,
)
from app.desktop_v2.backend.observability import create_desktop_log_sink
from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo
from sagents.v2.runtime.observability import FilesystemLogSink, NoopLogSink
from sagents.v2.runtime.session.filesystem import StoreInUseError


def test_sidecar_registry_is_private_and_removed_only_by_its_owner(
    tmp_path: Path,
):
    registry = _publish_sidecar(
        tmp_path,
        host="127.0.0.1",
        port=54321,
        build_id="test-build",
    )

    assert json.loads(registry.read_text(encoding="utf-8")) == {
        "protocol": "sage.runtime/v2",
        "revision": 3,
        "build_id": "test-build",
        "host": "127.0.0.1",
        "port": 54321,
        "pid": os.getpid(),
    }
    assert registry.stat().st_mode & 0o777 == 0o600

    registry.write_text(
        json.dumps({"pid": os.getpid() + 1}),
        encoding="utf-8",
    )
    _remove_owned_sidecar_registry(registry)
    assert registry.exists()

    registry.write_text(json.dumps({"pid": os.getpid()}), encoding="utf-8")
    _remove_owned_sidecar_registry(registry)
    assert not registry.exists()


def test_desktop_log_sink_is_resolved_from_the_component_plugin_selection(
    tmp_path: Path,
):
    (tmp_path / "settings.json").write_text(
        json.dumps(
            {"component_selections": {"observability.log-sink": "sage.logging.noop"}}
        ),
        encoding="utf-8",
    )

    plugin_id, sink = create_desktop_log_sink(tmp_path)

    assert plugin_id == "sage.logging.noop"
    assert isinstance(sink, NoopLogSink)


def test_desktop_log_sink_falls_back_to_the_builtin_file_plugin(tmp_path: Path):
    (tmp_path / "settings.json").write_text(
        json.dumps(
            {
                "component_selections": {
                    "observability.log-sink": "removed.logging.plugin"
                }
            }
        ),
        encoding="utf-8",
    )

    plugin_id, sink = create_desktop_log_sink(tmp_path)

    assert plugin_id == "sage.logging.filesystem"
    assert isinstance(sink, FilesystemLogSink)
    assert sink.path == tmp_path / "logs/sage.jsonl"


def test_sidecar_waits_for_previous_writer_lock_to_be_released():
    attempts = 0
    now = 0.0
    delays: list[float] = []

    def create_service():
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise StoreInUseError(
                RuntimeErrorInfo(
                    code="session_store.in_use",
                    category=ErrorCategory.CONFLICT,
                    message="busy",
                    safe_to_resume=True,
                )
            )
        return "service"

    def sleep(delay: float) -> None:
        nonlocal now
        delays.append(delay)
        now += delay

    result = _create_after_writer_release(
        create_service,
        timeout_seconds=1,
        retry_interval_seconds=0.1,
        monotonic=lambda: now,
        sleep=sleep,
    )

    assert result == "service"
    assert attempts == 3
    assert delays == [0.1, 0.1]


def test_sidecar_rejects_non_loopback_bind_addresses():
    assert _require_loopback_host("127.0.0.1") == "127.0.0.1"
    assert _require_loopback_host("127.0.0.42") == "127.0.0.42"
    assert _require_loopback_host("localhost") == "127.0.0.1"
    with pytest.raises(ValueError, match="loopback"):
        _require_loopback_host("0.0.0.0")
    with pytest.raises(ValueError, match="loopback"):
        _require_loopback_host("192.168.1.10")
