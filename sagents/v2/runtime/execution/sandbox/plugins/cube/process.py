"""Bounded command supervision inside Cube; cancellation waits for remote exit.

The SDK's blocking commands.run does not expose a cancellable command handle.
A short-lived supervisor owns one process group and a private output spool.
It needs only Python 3 in the trusted Cube template, not a new host service.
"""

from __future__ import annotations

import asyncio
import base64
import json
import shlex
import time

from sagents.v2.contracts.common import new_id
from sagents.v2.runtime.execution.sandbox.contracts import ProcessResult


_WORKER = r"""
import base64, json, os, selectors, signal, subprocess, sys, time
p = json.loads(base64.b64decode(sys.argv[1]))
root = p["directory"]
cancelled = False
def stop(*_):
    global cancelled
    cancelled = True
signal.signal(signal.SIGTERM, stop)
out, err = bytearray(), bytearray()
truncated = False
child = None
started = time.monotonic()
try:
    child = subprocess.Popen(p["argv"], cwd=p["cwd"], env={**os.environ, **p["env"]},
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
    selector = selectors.DefaultSelector()
    selector.register(child.stdout, selectors.EVENT_READ, out)
    selector.register(child.stderr, selectors.EVENT_READ, err)
    while selector.get_map() or child.poll() is None:
        try:
            with open(root + "/cancel") as f: cancelled = cancelled or f.read() == p["token"]
        except FileNotFoundError: pass
        if cancelled or time.monotonic() - started >= p["timeout"]:
            try: os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError: pass
            cancelled = True
        elif child.poll() is not None:
            # A command must not leave detached descendants holding its pipes.
            try: os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError: pass
        events = selector.select(.05) if selector.get_map() else ()
        if not selector.get_map(): time.sleep(.05)
        for key, _ in events:
            data = os.read(key.fd, 65536)
            if not data:
                selector.unregister(key.fileobj)
                key.fileobj.close()
                continue
            remaining = max(0, p["max_output_bytes"] - len(out) - len(err))
            key.data.extend(data[:remaining])
            truncated = truncated or len(data) > remaining
    child.wait()
    result = {"exit_code": child.returncode, "stdout": base64.b64encode(out).decode(),
        "stderr": base64.b64encode(err).decode(), "truncated": truncated}
except BaseException as exc:
    result = {"error": type(exc).__name__}
finally:
    if child is not None:
        try: os.killpg(child.pid, signal.SIGKILL)
        except ProcessLookupError: pass
        child.wait()
result["duration_seconds"] = time.monotonic() - started
with open(root + "/result.tmp", "x") as f: json.dump(result, f)
os.replace(root + "/result.tmp", root + "/result.json")
"""

_CONTROL = r"""
import base64, json, os, shutil, subprocess, sys, tempfile
p = json.loads(base64.b64decode(sys.argv[1]))
op = p.pop("operation")
if op == "start":
    worker = p.pop("worker")
    p["directory"] = tempfile.mkdtemp(prefix="sage-exec-")
    p["token"] = os.urandom(24).hex()
    encoded = base64.b64encode(json.dumps(p).encode()).decode()
    child = subprocess.Popen([sys.executable, "-I", "-c", worker, encoded],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True)
    print(json.dumps({"directory": p["directory"], "token": p["token"]}))
else:
    root = p["directory"]
    if op == "poll":
        try:
            with open(root + "/result.json") as f: print(f.read())
        except FileNotFoundError: print("null")
    elif op == "stop":
        # Only the supervisor signals its own child group; no PID reuse race.
        fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            target = os.open("cancel", os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600, dir_fd=fd)
            with os.fdopen(target, "w") as f: f.write(p["token"])
        finally: os.close(fd)
        print("null")
    elif op == "clean":
        shutil.rmtree(root)
        print("null")
"""


def _call(sandbox, operation, **payload):
    encoded = base64.b64encode(
        json.dumps({"operation": operation, **payload}).encode()
    ).decode()
    result = sandbox.commands.run(
        "python3 -I -c " + shlex.quote(_CONTROL) + " " + shlex.quote(encoded),
        cwd="/",
        timeout=30,
    )
    if result.exit_code:
        raise RuntimeError("Cube command supervisor request failed")
    return json.loads(result.stdout)


async def _settle(task):
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            continue
    return task.result()


async def run_cube_process(sandbox, argv, *, cwd, env, timeout, max_output_bytes):
    start = asyncio.create_task(
        asyncio.to_thread(
            _call,
            sandbox,
            "start",
            worker=_WORKER,
            argv=argv,
            cwd=cwd,
            env=env,
            timeout=timeout,
            max_output_bytes=max_output_bytes,
        )
    )
    job = None
    try:
        job = await asyncio.shield(start)
        while True:
            result = await asyncio.to_thread(_call, sandbox, "poll", **job)
            if result is not None:
                if "error" in result:
                    raise RuntimeError(
                        "Cube command failed to start: " + result["error"]
                    )
                return ProcessResult(
                    process_id=new_id("process"),
                    argv=argv,
                    exit_code=result["exit_code"],
                    stdout=base64.b64decode(result["stdout"]),
                    stderr=base64.b64decode(result["stderr"]),
                    truncated=result["truncated"],
                    duration_seconds=result["duration_seconds"],
                )
            await asyncio.sleep(0.1)
    finally:
        # Shield cleanup from repeated task/AnyIO cancellation. A connection
        # failure leaves the supervisor's own wall-time limit in force.
        async def cleanup():
            current = job if job is not None else await _settle(start)
            await asyncio.to_thread(_call, sandbox, "stop", **current)
            deadline = time.monotonic() + 10
            while await asyncio.to_thread(_call, sandbox, "poll", **current) is None:
                if time.monotonic() >= deadline:
                    raise RuntimeError("Cube command exit could not be confirmed")
                await asyncio.sleep(0.05)
            await asyncio.to_thread(_call, sandbox, "clean", **current)

        from anyio import CancelScope

        with CancelScope(shield=True):
            await _settle(asyncio.create_task(cleanup()))
