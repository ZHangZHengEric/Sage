from __future__ import annotations

import os
import argparse
import json
import socket
import sys

import uvicorn

from app.desktop_v2.backend.storage import prepare_desktop_v2_storage


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=0)
    args = parser.parse_args(argv)
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind((args.host, args.port))
    listener.listen(2048)
    actual_port = int(listener.getsockname()[1])
    os.environ.setdefault("SAGE_INTERNAL_DESKTOP_PROCESS", "1")
    os.environ.setdefault("SAGE_TASK_COMPLETION_MODE", "no_tool_call")
    os.environ["SAGE_HOST"] = args.host
    os.environ["SAGE_PORT"] = str(actual_port)
    os.environ["SAGE_DESKTOP_V2_PORT"] = str(actual_port)
    prepare_desktop_v2_storage()
    from app.desktop_v2.backend.app import create_app

    print(json.dumps({"host": args.host, "port": actual_port}), flush=True)
    config = uvicorn.Config(
        create_app(),
        host=args.host,
        port=actual_port,
        log_level="info",
        timeout_keep_alive=65,
    )
    uvicorn.Server(config).run(sockets=[listener])
    return 0


if __name__ == "__main__":
    sys.exit(main())
