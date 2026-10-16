"""Explicit Server v2 Package model migration, with backup before any writes.

Stop Server writers, run an audit first, then apply with --writers-stopped and
--backup /secure/path.json. Unknown connection overrides abort the migration.
Run identities are deliberately retained. This is not a runtime parser fallback.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path

from sagents.v2.agent.management import AgentPackageBundle
from sagents.v2.package.manifest.models import ModelRoute


def migrate_document(value, references=None, *, host="server"):
    """Convert Server model aliases, preserving all non-model execution state."""
    references = references if references is not None else {}
    if isinstance(value, list):
        return [migrate_document(item, references, host=host) for item in value]
    if not isinstance(value, dict):
        return value
    result = {key: migrate_document(item, references, host=host) for key, item in value.items()}
    if value.get("schema_version") == "sage/v2" and isinstance(value.get("agents"), dict):
        if "models" not in value and "credentials" not in value:
            return result
        if host == "server" and value.get("credentials"):
            raise ValueError("Package credentials require an explicit App catalog migration")
        aliases = {}
        for alias, raw in value.get("models", {}).items():
            route = ModelRoute.model_validate(raw)
            if host == "desktop":
                credential = value.get("credentials", {}).get(route.credential, {})
                ref = credential.get("ref") or ""
                if credential.get("source") != "host" or not ref.startswith("llm-provider:"):
                    raise ValueError("Desktop route requires an explicit provider reference")
                aliases[alias] = ref.removeprefix("llm-provider:")
            else:
                expected = ModelRoute(provider="server", model=route.model)
                # Old built-in presets advertised these generic capabilities;
                # Server execution always used the authorized ModelRecord instead.
                preset = expected.model_copy(update={"capabilities": expected.capabilities.model_copy(
                    update={"reasoning": True, "parallel_tool_calls": True})})
                if route not in (expected, preset):
                    raise ValueError("Nonstandard Package model route requires explicit migration")
                aliases[alias] = route.model
        for agent in result["agents"].values():
            for field in ("models", "delegation_model_bindings"):
                for slot, alias in list(agent.get(field, {}).items()):
                    if alias not in aliases:
                        raise ValueError(f"Package references missing legacy model alias: {alias}")
                    agent[field][slot] = aliases[alias]
        result.pop("models", None)
        result.pop("credentials", None)
    if isinstance(value.get("manifest"), dict) and value["manifest"].get("schema_version") == "sage/v2":
        bundle = AgentPackageBundle.model_validate(result)
        old_ref = hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        references[old_ref] = bundle.content_hash
        result = bundle.model_dump(mode="json")
    return result


def replace_references(value, references):
    """Only Package references change; Run/composition hashes are admission facts."""
    if isinstance(value, list):
        return [replace_references(item, references) for item in value]
    if not isinstance(value, dict):
        return value
    return {key: references.get(item, item)
            if key in {"ref", "package_ref", "expected_ref", "previous_ref"} and isinstance(item, str)
            else replace_references(item, references)
            for key, item in value.items()}


def plan_rows(rows):
    """Plan keyed JSON cell updates without touching the database."""
    references, staged = {}, []
    for row in rows:
        entry = deepcopy(row)
        entry["after"] = migrate_document(row["value"], references)
        staged.append(entry)
    # The database's stored reference is authoritative, including old serializers.
    for entry in staged:
        if entry["table"] == "managed_agent_records" and entry.get("kind") == "bundle":
            references[entry["ref"]] = AgentPackageBundle.model_validate(entry["after"]).content_hash
    for entry in staged:
        entry["after"] = replace_references(entry["after"], references)
    return staged, references


def quote(name):
    return "`" + name.replace("`", "``") + "`"


def migrate(connection, *, backup=None):
    from app.v2.server.packages.repository import key as record_key
    rows, indices = [], []
    with connection.cursor() as cursor:
        cursor.execute("START TRANSACTION")
        try:
            cursor.execute("SELECT TABLE_NAME,COLUMN_NAME FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND DATA_TYPE IN ('json','text','mediumtext','longtext')")
            columns = cursor.fetchall()
            for table, column in columns:
                cursor.execute("SELECT COLUMN_NAME FROM information_schema.KEY_COLUMN_USAGE WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=%s AND CONSTRAINT_NAME='PRIMARY' ORDER BY ORDINAL_POSITION", (table,))
                keys = [row[0] for row in cursor.fetchall()]
                if not keys:
                    continue
                extra = ["kind", "ref"] if table == "managed_agent_records" else []
                names = [*keys, *extra, column]
                cursor.execute("SELECT " + ",".join(map(quote, names)) + " FROM " + quote(table) + " WHERE " + quote(column) + " LIKE %s", ('%sage/v2%',))
                for values in cursor.fetchall():
                    try:
                        value = json.loads(values[-1])
                    except (ValueError, TypeError):
                        continue
                    rows.append({"table": table, "column": column,
                                 "pk": dict(zip(keys, values[:len(keys)])), "value": value,
                                 **dict(zip(extra, values[len(keys):-1]))})
            planned, references = plan_rows(rows)
            changed = [row for row in planned if row["after"] != row["value"]]
            # Include reference-only rows that do not contain a manifest.
            cursor.execute("SELECT `key`,owner,kind,ref,payload FROM managed_agent_records")
            for old_key, owner, kind, ref, payload in cursor.fetchall():
                payload = json.loads(payload) if isinstance(payload, str) else payload
                updated = replace_references(payload, references)
                new_ref = references.get(ref, ref)
                new_key = record_key(owner, kind, new_ref) if kind == "bundle" else old_key
                if updated != payload or new_ref != ref or new_key != old_key:
                    indices.append({"table": "managed_agent_records", "pk": {"key": old_key},
                                    "before": {"key": old_key, "ref": ref, "payload": payload},
                                    "after": {"key": new_key, "ref": new_ref, "payload": updated}})
            cursor.execute("SELECT id,package_ref FROM agents")
            for agent_id, ref in cursor.fetchall():
                if references.get(ref, ref) != ref:
                    indices.append({"table": "agents", "pk": {"id": agent_id},
                                    "before": {"package_ref": ref}, "after": {"package_ref": references[ref]}})
            report = {"cells": len(changed), "references": len(indices), "applied": backup is not None}
            if backup is None:
                connection.rollback()
                return report
            descriptor = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "w") as output:
                json.dump({"migration": "app-models-v1", "cells": changed, "indices": indices}, output, ensure_ascii=False)
                output.flush()
                os.fsync(output.fileno())
            # Update JSON cells before changing bundle primary keys.
            for row in changed:
                where = " AND ".join(quote(key) + "=%s" for key in row["pk"])
                cursor.execute("UPDATE " + quote(row["table"]) + " SET " + quote(row["column"]) + "=%s WHERE " + where,
                               (json.dumps(row["after"], ensure_ascii=False), *row["pk"].values()))
                if cursor.rowcount != 1:
                    raise ValueError("Migration row changed concurrently")
            changed_payloads = {(row["table"], tuple(row["pk"].items())) for row in changed if row["column"] == "payload"}
            for row in indices:
                updates = dict(row["after"])
                if (row["table"], tuple(row["pk"].items())) in changed_payloads:
                    updates.pop("payload", None)
                where = " AND ".join(quote(key) + "=%s" for key in row["pk"])
                cursor.execute("UPDATE " + quote(row["table"]) + " SET " + ",".join(quote(key) + "=%s" for key in updates) + " WHERE " + where,
                               (*[json.dumps(value) if isinstance(value, dict) else value for value in updates.values()], *row["pk"].values()))
            connection.commit()
            return {**report, "backup": str(backup)}
        except BaseException:
            connection.rollback()
            raise


if __name__ == "__main__":
    import pymysql
    from app.v2.server.config.settings import ServerSettings
    from sagents.v2.runtime.session.plugins.mysql import parse_mysql_dsn
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backup", type=Path)
    parser.add_argument("--writers-stopped", action="store_true")
    args = parser.parse_args()
    if args.backup and not args.writers_stopped:
        parser.error("Stop Server writers before applying; pass --writers-stopped")
    connection = pymysql.connect(**parse_mysql_dsn(ServerSettings.from_env().mysql_url))
    try:
        print(json.dumps(migrate(connection, backup=args.backup)))
    finally:
        connection.close()
