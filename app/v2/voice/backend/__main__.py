"""Sage Voice's private newline-delimited JSON subprocess interface."""

import asyncio
import json
import os
import sys
from pathlib import Path
from tempfile import TemporaryDirectory


def main():
    # Reserve stdout for the Flutter protocol, including when a native library logs.
    output = os.fdopen(os.dup(sys.stdout.fileno()), "w", encoding="utf-8", buffering=1)
    os.dup2(sys.stderr.fileno(), sys.stdout.fileno())

    def emit(event, **data):
        print(json.dumps({"event": event, **data}, ensure_ascii=False), file=output)

    try:
        from .runtime import serve

        root = Path(
            os.environ.get(
                "SAGE_VOICE_HOME",
                Path.home() / "Library" / "Application Support" / "Sage Voice",
            )
        )
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        with TemporaryDirectory(prefix="sage-voice-") as state:
            asyncio.run(serve(root / "settings.json", Path(state), emit))
    except (ImportError, OSError) as error:
        emit(
            "error",
            message=f"语音引擎启动失败。请检查 Python 环境和 Sage Voice 依赖。{error}",
        )
        raise SystemExit(1) from None
    finally:
        output.close()


if __name__ == "__main__":
    main()
