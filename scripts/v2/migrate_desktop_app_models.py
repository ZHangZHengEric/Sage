"""Offline Desktop App model migration; creates private backups before writes.

Stop Desktop/sidecar writers, audit with --root, then use --apply
--writers-stopped. Model settings and admitted Run identities stay intact.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3

from scripts.v2.migrate_app_models import migrate_document


def transform(value, references):
    return migrate_document(value, references, host="desktop")


def remap(value, references):
    if isinstance(value, list):
        return [remap(item, references) for item in value]
    if not isinstance(value, dict):
        return value
    keys = {"package_hash", "recommended_hash", "candidate_hash", "baseline_hash", "package_ref", "ref"}
    result = {key: references.get(item, item) if key in keys and isinstance(item, str)
              else remap(item, references) for key, item in value.items()}
    if all(key in result for key in ("name", "config", "fingerprint", "package")):
        result["fingerprint"] = hashlib.sha256(json.dumps(
            {"name": result["name"], "config": result["config"]}, sort_keys=True,
            separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
    return result


def migrate(root, *, apply=False):
    references, documents, databases = {}, [], []
    for path in root.rglob("*"):
        if not path.is_file() or "backups" in path.relative_to(root).parts:
            continue
        if path.suffix == ".json":
            raw = path.read_bytes()
            try:
                value = json.loads(raw)
            except (ValueError, UnicodeError):
                continue
            updated = transform(value, references)
            documents.append((path, raw, value, updated))
        elif path.name == "rsi.sqlite3":
            connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
            try:
                for identity, body, summary in connection.execute('SELECT id,body,summary FROM records'):
                    value = json.loads(body)
                    updated = transform(value, references)
                    databases.append((path, identity, body, summary, updated))
            finally:
                connection.close()
    documents = [(path, raw, remap(updated, references)) for path, raw, value, updated in documents
                 if value != remap(updated, references)]
    databases = [(path, identity, body, summary, remap(updated, references))
                 for path, identity, body, summary, updated in databases
                 if json.loads(body) != remap(updated, references)]
    report = {"files": len(documents), "records": len(databases), "applied": apply}
    if not apply:
        return report
    backup = root / "backups" / ("app-models-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ"))
    backup.mkdir(parents=True, mode=0o700)
    # Back up every affected file and complete SQLite DB before changing anything.
    for path in {entry[0] for entry in documents + databases}:
        target = backup / path.relative_to(root)
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if path.suffix == ".sqlite3":
            with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as source, sqlite3.connect(target) as destination:
                source.backup(destination)
        else:
            shutil.copyfile(path, target)
        target.chmod(0o600)
    for path, raw, updated in documents:
        if path.read_bytes() != raw:
            raise ValueError("Desktop data changed during migration; stop all writers")
        temporary = path.with_name(path.name + ".app-model-migration")
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as output:
            json.dump(updated, output, ensure_ascii=False)
            output.flush()
            os.fsync(output.fileno())
        temporary.replace(path)
    for path in {entry[0] for entry in databases}:
        with sqlite3.connect(path) as connection:
            for _, identity, body, summary, updated in (item for item in databases if item[0] == path):
                # Retain each summary's selected fields, refreshing only changed values.
                brief = json.loads(summary)
                brief = {key: updated.get(key, value) for key, value in brief.items()}
                result = connection.execute('UPDATE records SET body=?,summary=? WHERE id=? AND body=?',
                                            (json.dumps(updated, ensure_ascii=False), json.dumps(brief, ensure_ascii=False), identity, body))
                if result.rowcount != 1:
                    raise ValueError("Desktop RSI changed during migration; stop all writers")
    return {**report, "backup": str(backup)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--writers-stopped", action="store_true")
    args = parser.parse_args()
    if args.apply and not args.writers_stopped:
        parser.error("Stop Desktop and sidecars before applying; pass --writers-stopped")
    print(json.dumps(migrate(args.root, apply=args.apply)))
