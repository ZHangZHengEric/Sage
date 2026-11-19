"""Fingerprint stamps for snapshots with a verified explicit owner."""

import json


def _stamp(snapshot):
    return snapshot.with_name("owner-confirmed.json")


def _signature(snapshot):
    stat = snapshot.stat()
    return [stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns]


def owner_confirmed(snapshot):
    try:
        return json.loads(_stamp(snapshot).read_bytes()) == {
            "version": 1,
            "snapshot": _signature(snapshot),
        }
    except (OSError, ValueError):
        return False


def record_owner(snapshot, atomic_write):
    try:
        atomic_write(_stamp(snapshot), {"version": 1, "snapshot": _signature(snapshot)})
    except OSError:
        # The canonical snapshot is already durable. A missing stamp just
        # makes the migration verify ownership on its next pass.
        pass
