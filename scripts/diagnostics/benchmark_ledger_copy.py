"""Offline equal-output ledger CPU comparison against release 284abc7f.

Run from the repository root with PYTHONPATH=. No model/network requests.
"""

import subprocess, time, statistics, json
from sagents.context.messages import message, message_manager

old_message = subprocess.check_output(
    ["git", "show", "284abc7f:sagents/context/messages/message.py"], text=True
)
ns = dict(vars(message))
exec(
    old_message[
        old_message.index("def copy_message_snapshot(") : old_message.index(
            "def is_message_client_visible("
        )
    ],
    ns,
)
old_manager_source = subprocess.check_output(
    ["git", "show", "284abc7f:sagents/context/messages/message_manager.py"], text=True
)
old_ns = dict(vars(message_manager))
exec(compile(old_manager_source, "before_manager", "exec"), old_ns)
old_ns["copy_message_snapshot"] = ns["copy_message_snapshot"]
for tools in (False, True):
    parts = [
        message.MessageChunk(
            role="assistant",
            message_id="a",
            content=None if tools else "中文文本",
            tool_calls=[
                {
                    "index": 0,
                    "id": "a",
                    "function": {"name": "tool", "arguments": "x" * 32},
                }
            ]
            if tools
            else None,
        )
        for _ in range(5600)
    ]
    result = {}
    outputs = []
    for label, cls in [
        ("before", old_ns["MessageManager"]),
        ("after", message_manager.MessageManager),
    ]:
        timings = []
        for _ in range(5):
            manager = cls()
            start = time.thread_time()
            for part in parts:
                manager.add_messages(part)
            timings.append((time.thread_time() - start) * 1000)
        outputs.append(manager.messages)
        result[label] = round(statistics.median(timings), 3)
    assert outputs[0] == outputs[1]
    print("tools" if tools else "text", json.dumps(result), flush=True)
