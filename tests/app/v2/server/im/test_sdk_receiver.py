"""Real SDK frames and process lifecycles, with the network endpoint isolated."""

import asyncio
import json
from pathlib import Path
import sys

import pytest

from app.v2.server.im.feishu import FeishuConfig
from app.v2.server.im.feishu_ws import SDKReceiver
from tests.app.v2.server.im.test_feishu import event


@pytest.fixture
def sdk_process(tmp_path, monkeypatch):
    worker = Path(__file__).resolve().parents[5] / "app/v2/server/im"
    script = tmp_path / "local_sdk.py"
    script.write_text(f"""
import asyncio, json, sys, time
from pathlib import Path
sys.path.insert(0, {str(worker)!r})
import lark_oapi as lark
from lark_oapi.ws.client import Client as Native
from lark_oapi.ws.pb.pbbp2_pb2 import Frame
from feishu_worker import run
class LocalSDK(Native):
    async def _connect(self):
        pass
    def start(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(self._connect())
        payload = {event("中" * 20000)!r}
        payload['header']['app_id'] = self._app_id
        frame = Frame(SeqID=1, LogID=1, service=1, method=1)
        for key,value in {{'message_id':'m1','trace_id':'t1','sum':'1','seq':'0','type':'event'}}.items():
            h=frame.headers.add(); h.key,h.value=key,value
        frame.payload=json.dumps(payload).encode()
        async def write(raw):
            reply=Frame(); reply.ParseFromString(raw)
            Path({str(tmp_path)!r}, 'ack-' + self._app_id).write_text(reply.payload.decode())
        self._write_message=write
        loop.run_until_complete(self._handle_data_frame(frame))
        while True: time.sleep(1)
run(LocalSDK)
""")
    processes = []

    async def spawn(self):
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-u",
            str(script),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            limit=256 * 1024,
        )
        processes.append(process)
        return process

    monkeypatch.setattr(SDKReceiver, "_spawn", spawn)
    return processes


@pytest.mark.parametrize("failure", [False, True])
async def test_sdk_ack_waits_for_commit_and_propagates_failure(
    tmp_path, sdk_process, failure
):
    entered, release = asyncio.Event(), asyncio.Event()

    async def admit(payload):
        assert len(json.loads(payload["event"]["message"]["content"])["text"]) == 20000
        entered.set()
        await release.wait()
        if failure:
            raise OSError("private database details")

    receiver = SDKReceiver(
        FeishuConfig(app_id="cli_test", app_secret="secret"), admit, lambda state: None
    )
    task = asyncio.create_task(receiver.run())
    try:
        await asyncio.wait_for(entered.wait(), 10)
        ack = tmp_path / "ack-cli_test"
        assert not ack.exists()
        release.set()
        async with asyncio.timeout(5):
            while not ack.exists():
                await asyncio.sleep(0.01)
        assert json.loads(ack.read_text())["code"] == (500 if failure else 200)
        # An idle child exits even if no further event arrives after parent EOF.
        process = sdk_process[0]
        process.stdin.close()
        assert await asyncio.wait_for(process.wait(), 3) == 0
    finally:
        release.set()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    assert all(process.returncode is not None for process in sdk_process)


async def test_two_app_connections_are_isolated_and_stop_independently(
    tmp_path, sdk_process
):
    tasks = []
    receivers = []

    async def admit(payload):
        pass

    try:
        for app in ("cli_first", "cli_second"):
            receiver = SDKReceiver(
                FeishuConfig(app_id=app, app_secret="secret"), admit, lambda state: None
            )
            receivers.append(receiver)
            tasks.append(asyncio.create_task(receiver.run()))
        async with asyncio.timeout(15):
            while not all(
                (tmp_path / ("ack-" + app)).exists()
                for app in ("cli_first", "cli_second")
            ):
                await asyncio.sleep(0.01)
        first, second = [receiver.process for receiver in receivers]
        tasks[0].cancel()
        await asyncio.gather(tasks[0], return_exceptions=True)
        assert first.returncode is not None
        assert second.returncode is None
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
    assert all(process.returncode is not None for process in sdk_process)
