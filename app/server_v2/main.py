from __future__ import annotations

import argparse
import socket
import sys
from dataclasses import replace
from pathlib import Path

import uvicorn
from dotenv import load_dotenv

from sagents.v2.compat import require_python

ENV_FILE = Path(__file__).resolve().parent / ".env"


def load_env_file(path: Path | None = None) -> Path | None:
    candidate = path or ENV_FILE
    if not candidate.is_file():
        return None
    load_dotenv(candidate, override=False)
    return candidate


def _pick_port(host: str, port: int) -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            listener.bind((host, port))
        except OSError:
            listener.bind((host, 0))
        return int(listener.getsockname()[1])


def main(argv: list[str] | None = None) -> int:
    require_python()
    load_env_file()
    parser = argparse.ArgumentParser(description="Sage Server v2")
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--data-root", type=Path, default=None)
    args = parser.parse_args(argv)

    from app.server_v2.app import create_app
    from app.server_v2.core.settings import ServerV2Settings

    settings = ServerV2Settings.from_env(data_root=args.data_root)
    host = args.host or settings.host
    requested = args.port or settings.port
    port = _pick_port(host, requested)
    if port != requested:
        print(f"port {requested} is busy, switching to {port}", flush=True)
    application = create_app(settings=replace(settings, host=host, port=port))
    uvicorn.run(application, host=host, port=port, log_level="info")
    return 0


if __name__ == "__main__":
    sys.exit(main())
