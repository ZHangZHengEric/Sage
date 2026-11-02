"""Isolated official SDK WS entry point; credentials arrive only through stdin."""

import itertools
import json
import os
import queue
import sys
import threading

import lark_oapi as lark


def run(client_type=None):
    config = json.loads(sys.stdin.readline(8192))
    acknowledgements = queue.Queue(maxsize=1)
    output_lock = threading.Lock()
    sequence = itertools.count()

    def emit(value):
        with output_lock:
            sys.stdout.write(json.dumps(value, ensure_ascii=False) + "\n")
            sys.stdout.flush()

    def controls():
        try:
            for line in sys.stdin:
                acknowledgements.put(json.loads(line), timeout=3)
        finally:
            # Close the socket even if the parent dies while no events arrive.
            os._exit(0)

    def receive(data):
        message_id = next(sequence)
        emit(
            {
                "kind": "event",
                "id": message_id,
                "payload": json.loads(lark.JSON.marshal(data)),
            }
        )
        try:
            reply = acknowledgements.get(timeout=3)
        except queue.Empty:
            # A late ACK must never acknowledge a different event.
            os._exit(1)
        if reply != {"id": message_id, "ok": True}:
            raise RuntimeError("Sage event admission unavailable")

    class Client(client_type or lark.ws.Client):
        async def _connect(self):
            await super()._connect()
            emit({"kind": "state", "state": "connected"})

        async def _disconnect(self):
            await super()._disconnect()
            emit({"kind": "state", "state": "reconnecting"})

    dispatcher = (
        lark.EventDispatcherHandler.builder("", "", lark.LogLevel.CRITICAL)
        .register_p2_im_message_receive_v1(receive)
        .build()
    )
    client = Client(
        config["app_id"],
        config["app_secret"],
        log_level=lark.LogLevel.CRITICAL,
        event_handler=dispatcher,
    )
    threading.Thread(target=controls, daemon=True).start()
    try:
        client.start()
    except Exception:
        emit({"kind": "state", "state": "reconnecting"})
        raise SystemExit(1) from None


if __name__ == "__main__":
    run()
