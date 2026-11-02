"""Bounded private IPC between Sage and an application-isolated official SDK."""

import asyncio
import json
from pathlib import Path
import sys

from sagents.v2.runtime.observability.logs import get_logger

LOGGER = get_logger(__name__)


class SDKReceiver:
    def __init__(self, config, admit, state):
        self.config, self.admit, self.state = config, admit, state
        self.process = None

    async def _spawn(self):
        return await asyncio.create_subprocess_exec(
            sys.executable,
            "-X",
            "utf8",
            "-u",
            str(Path(__file__).with_name("feishu_worker.py")),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            limit=256 * 1024,
        )

    async def run(self):
        delay = 1
        while True:
            self.state("connecting")
            try:
                self.process = await self._spawn()
                self.process.stdin.write(
                    (
                        json.dumps(
                            {
                                "app_id": self.config.app_id,
                                "app_secret": self.config.app_secret.get_secret_value(),
                            }
                        )
                        + "\n"
                    ).encode()
                )
                await self.process.stdin.drain()
                connected = False
                while True:
                    async with asyncio.timeout(None if connected else 20):
                        raw = await self.process.stdout.readline()
                    if not raw:
                        break
                    frame = json.loads(raw)
                    if frame.get("kind") == "state":
                        connected = frame.get("state") == "connected"
                        self.state("connected" if connected else "reconnecting")
                        if connected:
                            delay = 1
                    elif frame.get("kind") == "event":
                        ok = False
                        try:
                            async with asyncio.timeout(2.5):
                                await self.admit(frame["payload"])
                            ok = True
                        except Exception:
                            LOGGER.warning(
                                "server.im.sdk.admission_failed",
                                "IM event admission will be retried",
                            )
                        self.process.stdin.write(
                            (json.dumps({"id": frame["id"], "ok": ok}) + "\n").encode()
                        )
                        await self.process.stdin.drain()
            except asyncio.CancelledError:
                raise
            except Exception:
                LOGGER.warning(
                    "server.im.sdk.reconnect", "IM SDK receiver will reconnect"
                )
            finally:
                await self.close()
            self.state("reconnecting")
            await asyncio.sleep(delay)
            delay = min(30, delay * 2)

    async def close(self):
        process, self.process = self.process, None
        if process is None:
            return
        if process.stdin is not None:
            process.stdin.close()
        if process.returncode is None:
            try:
                process.terminate()
            except ProcessLookupError:
                pass
        try:
            async with asyncio.timeout(3):
                await process.wait()
        except TimeoutError:
            if process.returncode is None:
                try:
                    process.kill()
                except ProcessLookupError:
                    pass
            await process.wait()
