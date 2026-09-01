from __future__ import annotations

import argparse
import ipaddress
import json
import os
import socket
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import TypeVar

import uvicorn

from app.desktop_v2.backend.observability import create_desktop_log_sink
from app.desktop_v2.backend.runtime_protocol import (
    SIDECAR_PROTOCOL,
    SIDECAR_REVISION,
)
from app.desktop_v2.backend.storage import prepare_desktop_v2_storage
from sagents.v2.runtime.observability import StructuredLogger, install_standard_logging
from sagents.v2.runtime.session import StoreInUseError


_ServiceT = TypeVar("_ServiceT")


def _require_loopback_host(host: str) -> str:
    """Keep the unauthenticated Desktop control plane local to this machine."""

    candidate = str(host).strip()
    if candidate.lower() == "localhost":
        # Avoid relying on a mutable hosts/DNS mapping for the security
        # boundary; bind the numeric loopback address explicitly.
        return "127.0.0.1"
    try:
        address = ipaddress.ip_address(candidate)
    except ValueError as exc:
        raise ValueError("Desktop v2 sidecar host must be a loopback address") from exc
    if not address.is_loopback:
        raise ValueError("Desktop v2 sidecar host must be a loopback address")
    if address.version != 4:
        raise ValueError("Desktop v2 sidecar currently requires an IPv4 loopback host")
    return candidate


def _sidecar_registry_path(runtime_root: Path) -> Path:
    return runtime_root / "desktop-v2-sidecar.json"


def _publish_sidecar(
    runtime_root: Path,
    *,
    host: str,
    port: int,
    build_id: str,
) -> Path:
    path = _sidecar_registry_path(runtime_root)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(
            {
                "protocol": SIDECAR_PROTOCOL,
                "revision": SIDECAR_REVISION,
                "build_id": build_id,
                "host": host,
                "port": port,
                "pid": os.getpid(),
            },
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )
    temporary.chmod(0o600)
    temporary.replace(path)
    return path


def _remove_owned_sidecar_registry(path: Path) -> None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        if value.get("pid") == os.getpid():
            path.unlink(missing_ok=True)
    except (OSError, ValueError, AttributeError):
        return


def _create_after_writer_release(
    factory: Callable[[], _ServiceT],
    *,
    timeout_seconds: float = 3.0,
    retry_interval_seconds: float = 0.1,
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> _ServiceT:
    """Wait briefly for a previous Desktop sidecar to release its writer lock."""

    deadline = monotonic() + timeout_seconds
    while True:
        try:
            return factory()
        except StoreInUseError:
            remaining = deadline - monotonic()
            if remaining <= 0:
                raise
            sleep(min(retry_interval_seconds, remaining))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--data-root", type=Path, default=None)
    parser.add_argument("--build-id", default="manual")
    args = parser.parse_args(argv)
    try:
        args.host = _require_loopback_host(args.host)
    except ValueError as exc:
        parser.error(str(exc))
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind((args.host, args.port))
    listener.listen(2048)
    actual_port = int(listener.getsockname()[1])
    storage = prepare_desktop_v2_storage(data_root=args.data_root)
    log_plugin_id, log_sink = create_desktop_log_sink(storage.runtime_root)
    install_standard_logging(log_sink)
    runtime_logger = StructuredLogger(log_sink, "desktop.sidecar")
    runtime_logger.info(
        "sidecar.starting",
        "Sage Desktop v2 sidecar is starting",
        attributes={
            "host": args.host,
            "port": actual_port,
            "build_id": args.build_id,
            "log_plugin": log_plugin_id,
        },
    )
    from app.desktop_v2.backend.app import create_app
    from app.desktop_v2.backend.service import DesktopV2Service

    # Build the application before advertising readiness. In particular, this
    # acquires the SessionStore writer lock, so a losing sidecar never publishes
    # an endpoint that will immediately disappear.
    try:
        service = _create_after_writer_release(
            lambda: DesktopV2Service(
                root=storage.data_root,
                log_sink=log_sink,
                log_plugin_id=log_plugin_id,
                sidecar_port=actual_port,
            )
        )
        application = create_app(
            build_id=args.build_id,
            service=service,
        )
    except Exception as exc:
        runtime_logger.exception(
            "sidecar.start_failed",
            "Sage Desktop v2 sidecar failed during startup",
            exc,
        )
        raise
    registry = _publish_sidecar(
        storage.runtime_root,
        host=args.host,
        port=actual_port,
        build_id=args.build_id,
    )
    print(json.dumps({"host": args.host, "port": actual_port}), flush=True)
    runtime_logger.info(
        "sidecar.ready",
        "Sage Desktop v2 sidecar is ready",
        attributes={
            "host": args.host,
            "port": actual_port,
            "build_id": args.build_id,
        },
    )
    config = uvicorn.Config(
        application,
        host=args.host,
        port=actual_port,
        log_level="info",
        timeout_keep_alive=65,
    )
    try:
        uvicorn.Server(config).run(sockets=[listener])
    finally:
        runtime_logger.info(
            "sidecar.stopped",
            "Sage Desktop v2 sidecar stopped",
        )
        _remove_owned_sidecar_registry(registry)
        log_sink.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
