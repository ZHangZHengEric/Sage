"""Process ownership for durable RSI records, without replaying any calls."""
import os

import psutil


def process_identity():
    return {"pid": os.getpid(), "started": psutil.Process().create_time()}


def process_alive(owner):
    if not isinstance(owner, dict) or type(owner.get("pid")) is not int or owner["pid"] <= 1:
        return False
    try:
        process = psutil.Process(owner["pid"])
        return (process.is_running() and process.status() != psutil.STATUS_ZOMBIE
                and process.create_time() == owner.get("started"))
    except psutil.AccessDenied:
        # An unreadable process is not proof that an execution has stopped.
        return True
    except psutil.NoSuchProcess:
        return False


def legacy_sidecar_alive(path):
    """Old hosts have no per-run owner, but may have a live sidecar registry."""
    import json
    try:
        pid = json.loads(path.read_text())["pid"]
        if type(pid) is not int or pid <= 1 or pid == os.getpid():
            return False
        return psutil.pid_exists(pid)
    except (OSError, ValueError, KeyError, TypeError):
        return False
