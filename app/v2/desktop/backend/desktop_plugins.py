"""Desktop plugin package validation and transactional, user-scoped registry."""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
import re
import sqlite3
import stat
import time
import uuid
import zipfile
from contextlib import closing, contextmanager
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

from jsonschema import Draft202012Validator
from PIL import Image
from sagents.v2.tool import SideEffectLevel, ToolInvocation, tool

MAX_PACKAGE = 8 * 1024 * 1024
MAX_ASSETS = 24 * 1024 * 1024
MAX_VALUE = 64 * 1024
PLUGIN_EDIT_TOOLS = ("list_desktop_plugins", "download_desktop_plugin")
ASSET_TYPES = {
    ".html": "text/html",
    ".css": "text/css",
    ".js": "text/javascript",
    ".mjs": "text/javascript",
    ".json": "application/json",
    ".txt": "text/plain",
    ".png": "image/png",
    ".jpeg": "image/jpeg",
    ".jpg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".svg": "image/svg+xml",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
}


def plugin_contract_root() -> Path:
    module = Path(__file__).resolve()
    for skills in (module.parents[3] / "skills", module.parents[4] / "skills"):
        root = skills / "sage-desktop-plugin-development" / "assets"
        if (root / "manifest.schema.json").is_file():
            return root
    raise FileNotFoundError("Desktop plugin protocol resources are missing")


def asset_path(value: str) -> PurePosixPath:
    parts = value.split("/")
    if len(value) > 240 or any(
        part in {".", ".."}
        or not re.fullmatch(r"[A-Za-z0-9_.-]+", part)
        or part.endswith(".")
        or part.split(".")[0].upper()
        in {
            "CON",
            "PRN",
            "AUX",
            "NUL",
            *(f"COM{i}" for i in range(1, 10)),
            *(f"LPT{i}" for i in range(1, 10)),
        }
        for part in parts
    ):
        raise ValueError(f"Invalid package path: {value!r}")
    return PurePosixPath(value)


def _json(value):
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


@dataclass(frozen=True)
class PluginPackage:
    manifest: dict
    assets: dict[str, bytes]
    digest: str
    archive: bytes


def validate_package(archive: bytes) -> PluginPackage:
    if len(archive) > MAX_PACKAGE:
        raise ValueError("Plugin package exceeds 8 MiB")
    try:
        with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
            entries = bundle.infolist()
            if (
                len(entries) > 256
                or sum(entry.file_size for entry in entries) > MAX_ASSETS
            ):
                raise ValueError("Plugin assets exceed package limits")
            assets = {}
            names = set()
            for entry in entries:
                name = (
                    entry.orig_filename.rstrip("/")
                    if entry.is_dir()
                    else entry.orig_filename
                )
                path = asset_path(name)
                mode = stat.S_IFMT(entry.external_attr >> 16)
                if mode not in {0, stat.S_IFDIR if entry.is_dir() else stat.S_IFREG}:
                    raise ValueError(f"Invalid package entry: {name}")
                if name.casefold() in names:
                    raise ValueError(f"Duplicate package entry: {name}")
                names.add(name.casefold())
                if entry.is_dir():
                    continue
                if path.suffix.lower() not in ASSET_TYPES or name.casefold().startswith("__sage/"):
                    raise ValueError(f"Unsupported plugin asset: {name}")
                assets[name] = bundle.read(entry)
    except (zipfile.BadZipFile, NotImplementedError, RuntimeError) as exc:
        raise ValueError("Invalid plugin ZIP package") from exc
    if (
        len(assets.get("manifest.json", b"")) > MAX_VALUE
        or "manifest.json" not in assets
    ):
        raise ValueError("Expected manifest.json at the package root")
    manifest = json.loads(assets["manifest.json"])
    schema = json.loads((plugin_contract_root() / "manifest.schema.json").read_bytes())
    error = next(Draft202012Validator(schema).iter_errors(manifest), None)
    if error:
        raise ValueError(
            f"Invalid plugin manifest at {error.json_path}: {error.message}"
        )
    if not manifest["name"].strip() or manifest["id"] != manifest["id"].strip():
        raise ValueError("Invalid plugin name or ID")
    entry = str(asset_path(manifest["entry"]))
    if entry not in assets:
        raise ValueError("Plugin entry is missing")
    assets[entry].decode("utf-8")
    if logo := manifest.get("logo"):
        logo = str(asset_path(logo))
        data = assets.get(logo, b"")
        if not data or len(data) > 256 * 1024:
            raise ValueError("Expected a bundled PNG logo of at most 256 KiB")
        try:
            with Image.open(io.BytesIO(data), formats=["PNG"]) as image:
                width, height = image.size
                if width != height or not 64 <= width <= 512 or image.is_animated:
                    raise ValueError("Plugin logo must be a static square PNG (64–512 px)")
                image.verify()
        except (OSError, SyntaxError, Image.DecompressionBombError) as exc:
            raise ValueError("Invalid plugin PNG logo") from exc
    endpoints = manifest.get("endpoints", {})
    if endpoints and "https" not in manifest.get("capabilities", []):
        raise ValueError("External endpoints require the https capability")
    for endpoint in endpoints.values():
        url = urlsplit(endpoint["url"])
        if (
            url.scheme != "https"
            or not url.hostname
            or url.username
            or url.password
            or url.port not in {None, 443}
            or url.fragment
            or any(ord(char) <= 32 for char in endpoint["url"])
        ):
            raise ValueError("Invalid HTTPS endpoint")
    digest = hashlib.sha256()
    for name, data in sorted(assets.items()):
        digest.update(_json([name, hashlib.sha256(data).hexdigest()]).encode())
    return PluginPackage(manifest, assets, digest.hexdigest(), archive)


class PluginConflict(ValueError):
    pass


class DesktopPluginStore:
    def __init__(self, path: Path, logger=None):
        self.path = path
        self.logger = logger
        self._endpoint_tokens: dict[tuple[str, str, str], str] = {}
        self._condition = asyncio.Condition()
        with closing(self._connect()) as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS revisions(owner TEXT PRIMARY KEY, revision INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS plugins(
                    owner TEXT NOT NULL, id TEXT NOT NULL, manifest TEXT NOT NULL,
                    digest TEXT NOT NULL, archive BLOB NOT NULL, enabled INTEGER NOT NULL,
                    pin INTEGER, revision INTEGER NOT NULL, PRIMARY KEY(owner, id));
                CREATE TABLE IF NOT EXISTS opens(
                    owner TEXT NOT NULL, client TEXT NOT NULL, request TEXT NOT NULL,
                    plugin TEXT NOT NULL, revision INTEGER NOT NULL, created REAL NOT NULL,
                    PRIMARY KEY(owner, client, request));
                CREATE TABLE IF NOT EXISTS plugin_storage(
                    owner TEXT NOT NULL, plugin TEXT NOT NULL, key TEXT NOT NULL, value TEXT NOT NULL,
                    PRIMARY KEY(owner, plugin, key));
                CREATE TABLE IF NOT EXISTS grants(
                    owner TEXT NOT NULL, plugin TEXT NOT NULL, capability TEXT NOT NULL, scope TEXT NOT NULL,
                    PRIMARY KEY(owner, plugin, capability, scope));
            """)

    def _connect(self):
        db = sqlite3.connect(self.path, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA busy_timeout=5000")
        return db

    @contextmanager
    def _transaction(self, *, write=True):
        with closing(self._connect()) as db, db:
            db.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            yield db

    @staticmethod
    def _revision(db, owner):
        row = db.execute(
            "SELECT revision FROM revisions WHERE owner=?", (owner,)
        ).fetchone()
        return row["revision"] if row else 0

    @staticmethod
    def _advance(db, owner):
        return db.execute(
            """INSERT INTO revisions VALUES (?,1)
            ON CONFLICT(owner) DO UPDATE SET revision=revision+1 RETURNING revision""",
            (owner,),
        ).fetchone()["revision"]

    @staticmethod
    def _row(db, owner, plugin_id, *, digest=None):
        row = db.execute(
            "SELECT * FROM plugins WHERE owner=? AND id=?", (owner, plugin_id)
        ).fetchone()
        if row is None:
            raise FileNotFoundError("Desktop plugin is not installed")
        if digest is not None and (not row["enabled"] or row["digest"] != digest):
            raise PluginConflict("Desktop plugin view is no longer active")
        return row

    def snapshot(self, owner, client):
        with self._transaction(write=False) as db:
            return {
                "revision": self._revision(db, owner),
                "plugins": [
                    {
                        **json.loads(row["manifest"]),
                        "digest": row["digest"],
                        "enabled": bool(row["enabled"]),
                        "pin": row["pin"],
                    }
                    for row in db.execute(
                        "SELECT id,manifest,digest,enabled,pin FROM plugins WHERE owner=? ORDER BY id",
                        (owner,),
                    )
                ],
                "opens": [
                    dict(row)
                    for row in db.execute(
                        """SELECT request, plugin, revision FROM opens
                    WHERE owner=? AND client=? AND created>? ORDER BY revision""",
                        (owner, client, time.time() - 86400),
                    )
                ],
            }

    def _register(self, owner, client, package):
        manifest = package.manifest
        plugin_id, version = manifest["id"], manifest["version"]
        with self._transaction() as db:
            old = db.execute(
                "SELECT * FROM plugins WHERE owner=? AND id=?", (owner, plugin_id)
            ).fetchone()
            if old:
                old_version = json.loads(old["manifest"])["version"]
                if old_version == version and old["digest"] == package.digest:
                    return {
                        "pluginId": plugin_id,
                        "version": version,
                        "revision": old["revision"],
                    }
                if tuple(map(int, version.split("."))) <= tuple(
                    map(int, old_version.split("."))
                ):
                    raise PluginConflict(
                        "Use a higher version to update an installed plugin"
                    )
            if not manifest.get("logo"):
                raise ValueError("Bundle a square PNG logo and declare its path in manifest.logo")
            revision = self._advance(db, owner)
            db.execute(
                """INSERT INTO plugins VALUES (?,?,?,?,?,1,NULL,?)
                ON CONFLICT(owner,id) DO UPDATE SET manifest=excluded.manifest,
                digest=excluded.digest, archive=excluded.archive, revision=excluded.revision""",
                (
                    owner,
                    plugin_id,
                    _json(manifest),
                    package.digest,
                    package.archive,
                    revision,
                ),
            )
            if old:
                previous = json.loads(old["manifest"])
                for capability in set(previous.get("capabilities", [])) - set(
                    manifest.get("capabilities", [])
                ):
                    db.execute(
                        "DELETE FROM grants WHERE owner=? AND plugin=? AND capability=?",
                        (owner, plugin_id, capability),
                    )
                endpoint_scopes = {
                    _json(endpoint)
                    for endpoint in manifest.get("endpoints", {}).values()
                }
                for (scope,) in db.execute(
                    "SELECT scope FROM grants WHERE owner=? AND plugin=? AND capability='https'",
                    (owner, plugin_id),
                ).fetchall():
                    if scope not in endpoint_scopes:
                        db.execute(
                            "DELETE FROM grants WHERE owner=? AND plugin=? AND capability='https' AND scope=?",
                            (owner, plugin_id, scope),
                        )
                for key in list(self._endpoint_tokens):
                    if key[:2] == (owner, plugin_id) and key[2] not in endpoint_scopes:
                        self._endpoint_tokens.pop(key, None)
            db.execute("DELETE FROM opens WHERE created<=?", (time.time() - 86400,))
            if client:
                db.execute(
                    "UPDATE plugins SET enabled=1 WHERE owner=? AND id=?",
                    (owner, plugin_id),
                )
                db.execute(
                    "DELETE FROM opens WHERE owner=? AND client=? AND plugin=?",
                    (owner, client, plugin_id),
                )
                db.execute(
                    "INSERT INTO opens VALUES (?,?,?,?,?,?)",
                    (owner, client, uuid.uuid4().hex, plugin_id, revision, time.time()),
                )
        return {"pluginId": plugin_id, "version": version, "revision": revision}

    async def register(self, owner, client, package):
        async with self._condition:
            result = self._register(owner, client, package)
            self._condition.notify_all()
        if self.logger is not None:
            self.logger.info(
                "desktop.plugin.registered",
                "Desktop plugin committed",
                attributes=result,
            )
        return result

    async def snapshots(self, owner, client):
        previous = None
        while True:
            async with self._condition:
                snapshot = await asyncio.to_thread(self.snapshot, owner, client)
                if snapshot == previous:
                    try:
                        await asyncio.wait_for(self._condition.wait(), timeout=15)
                    except TimeoutError:
                        heartbeat = True
                    else:
                        continue
                else:
                    heartbeat = False
                    previous = snapshot
            yield {} if heartbeat else snapshot

    async def acknowledge(self, owner, client, request):
        async with self._condition:
            with self._transaction() as db:
                db.execute(
                    "DELETE FROM opens WHERE owner=? AND client=? AND request=?",
                    (owner, client, request),
                )
            self._condition.notify_all()

    async def manage(self, owner, plugin_id, action):
        async with self._condition:
            with self._transaction() as db:
                row = self._row(db, owner, plugin_id)
                if action == "uninstall":
                    db.execute(
                        "DELETE FROM plugins WHERE owner=? AND id=?", (owner, plugin_id)
                    )
                    for table in ("plugin_storage", "grants"):
                        db.execute(
                            f"DELETE FROM {table} WHERE owner=? AND plugin=?",
                            (owner, plugin_id),
                        )
                elif action in {"enable", "disable"}:
                    db.execute(
                        "UPDATE plugins SET enabled=? WHERE owner=? AND id=?",
                        (action == "enable", owner, plugin_id),
                    )
                elif action == "pin" and row["pin"] is None:
                    db.execute(
                        """UPDATE plugins SET pin=(SELECT COALESCE(MAX(pin),0)+1 FROM plugins WHERE owner=?)
                        WHERE owner=? AND id=?""",
                        (owner, owner, plugin_id),
                    )
                elif action == "unpin":
                    db.execute(
                        "UPDATE plugins SET pin=NULL WHERE owner=? AND id=?",
                        (owner, plugin_id),
                    )
                elif action in {"up", "down"} and row["pin"] is not None:
                    pins = list(
                        db.execute(
                            "SELECT id,pin FROM plugins WHERE owner=? AND pin IS NOT NULL ORDER BY pin",
                            (owner,),
                        )
                    )
                    index = next(
                        i for i, pin in enumerate(pins) if pin["id"] == plugin_id
                    )
                    target = index + (-1 if action == "up" else 1)
                    if 0 <= target < len(pins):
                        neighbor = pins[target]
                        db.executemany(
                            "UPDATE plugins SET pin=? WHERE owner=? AND id=?",
                            [
                                (neighbor["pin"], owner, plugin_id),
                                (row["pin"], owner, neighbor["id"]),
                            ],
                        )
                if action in {"disable", "uninstall"}:
                    db.execute(
                        "DELETE FROM opens WHERE owner=? AND plugin=?",
                        (owner, plugin_id),
                    )
                if action == "revoke":
                    db.execute(
                        "DELETE FROM grants WHERE owner=? AND plugin=?",
                        (owner, plugin_id),
                    )
                self._advance(db, owner)
            if action in {"disable", "uninstall", "revoke"}:
                for key in list(self._endpoint_tokens):
                    if key[:2] == (owner, plugin_id):
                        self._endpoint_tokens.pop(key, None)
            self._condition.notify_all()

    def package(self, owner, plugin_id, digest):
        with closing(self._connect()) as db:
            return self._row(db, owner, plugin_id, digest=digest)["archive"]

    def installed_package(self, owner, plugin_id, *, digest=None):
        with closing(self._connect()) as db:
            row = self._row(db, owner, plugin_id)
            if digest is not None and row["digest"] != digest:
                raise PluginConflict("The installed plugin has been updated")
            return json.loads(row["manifest"]), row["archive"]

    def storage(self, owner, plugin_id, digest, operation, key, value):
        if not key or len(key) > 128:
            raise ValueError("Invalid storage key")
        with self._transaction(write=operation != "get") as db:
            self._row(db, owner, plugin_id, digest=digest)
            args = (owner, plugin_id, key)
            if operation == "get":
                row = db.execute(
                    "SELECT value FROM plugin_storage WHERE owner=? AND plugin=? AND key=?",
                    args,
                ).fetchone()
                return json.loads(row["value"]) if row else None
            if operation == "delete":
                db.execute(
                    "DELETE FROM plugin_storage WHERE owner=? AND plugin=? AND key=?",
                    args,
                )
                return None
            data = _json(value)
            used = db.execute(
                """SELECT COALESCE(SUM(length(CAST(value AS BLOB))+length(CAST(key AS BLOB))),0)
                FROM plugin_storage WHERE owner=? AND plugin=? AND key!=?""",
                args,
            ).fetchone()[0]
            if (
                len(data.encode()) > MAX_VALUE
                or used + len(data.encode()) + len(key.encode()) > 1024 * 1024
            ):
                raise ValueError("Plugin storage limit exceeded")
            db.execute(
                "INSERT OR REPLACE INTO plugin_storage VALUES (?,?,?,?)", (*args, data)
            )
            return None

    def permission(
        self, owner, plugin_id, digest, capability, endpoint=None, *, grant=False
    ):
        with self._transaction(write=grant) as db:
            manifest = json.loads(
                self._row(db, owner, plugin_id, digest=digest)["manifest"]
            )
            if capability not in manifest.get("capabilities", []):
                raise PermissionError("Capability is not declared")
            endpoint_config = (
                manifest.get("endpoints", {}).get(endpoint) if endpoint else None
            )
            if capability == "https" and not endpoint_config:
                raise PermissionError("HTTPS endpoint is not declared")
            scope = _json(endpoint_config) if endpoint_config else ""
            args = (owner, plugin_id, capability, scope)
            if grant:
                db.execute("INSERT OR IGNORE INTO grants VALUES (?,?,?,?)", args)
            allowed = db.execute(
                "SELECT 1 FROM grants WHERE owner=? AND plugin=? AND capability=? AND scope=?",
                args,
            ).fetchone()
            return bool(allowed), endpoint_config

    def endpoint_token(self, owner, plugin_id, endpoint_config):
        return self._endpoint_tokens.get((owner, plugin_id, _json(endpoint_config)))

    def set_endpoint_token(self, owner, plugin_id, endpoint_config, token):
        if endpoint_config.get("auth") != "bearer" or not re.fullmatch(
            r"[A-Za-z0-9._~+/=-]{1,2048}", token
        ):
            raise ValueError("Invalid endpoint bearer token")
        self._endpoint_tokens[owner, plugin_id, _json(endpoint_config)] = token


class DesktopPluginTools:
    def __init__(self, store, runtime, owner, client):
        self.store, self.runtime, self.owner, self.client = (
            store,
            runtime,
            owner,
            client,
        )

    async def _read(self, invocation, package_path):
        asset_path(package_path)
        info = await self.runtime.stat(package_path, invocation)
        if not info.is_file or info.size > MAX_PACKAGE:
            raise ValueError("Expected a ZIP file of at most 8 MiB in the workspace")
        return await asyncio.to_thread(
            validate_package, await self.runtime.read_bytes(package_path, invocation)
        )

    @tool(
        description="List the current user's installed Sage Desktop plugins, including disabled plugins.",
        side_effect_level=SideEffectLevel.READ,
        plan_safe=True,
    )
    async def list_desktop_plugins(self, invocation: ToolInvocation) -> dict:
        self._check_owner(invocation)
        snapshot = await asyncio.to_thread(self.store.snapshot, self.owner, "")
        return {"plugins": [
            {key: plugin[key] for key in ("id", "name", "version", "enabled")}
            for plugin in snapshot["plugins"]
        ]}

    @tool(
        description=(
            "Copy the installed Desktop plugin's original ZIP into a new workspace-relative ZIP file. "
            "Use its exact plugin ID and a destination path. Existing files are never overwritten."
        ),
        side_effect_level=SideEffectLevel.WRITE,
    )
    async def download_desktop_plugin(
        self, invocation: ToolInvocation, plugin_id: str, destination_path: str
    ) -> dict:
        self._check_owner(invocation)
        path = asset_path(destination_path)
        if path.suffix.lower() != ".zip":
            raise ValueError("Choose a workspace-relative ZIP path")
        manifest, archive = await asyncio.to_thread(
            self.store.installed_package, self.owner, plugin_id
        )
        saved = await self.runtime.write_bytes(str(path), archive, invocation, overwrite=False)
        return {"pluginId": plugin_id, "version": manifest["version"], "path": saved}

    def _check_owner(self, invocation):
        if invocation.request_context.actor.principal_id != self.owner:
            raise PermissionError("Desktop plugin access requires the current user")

    @tool(
        description=(
            "Validate a workspace-relative Sage Desktop plugin ZIP, install or update it, "
            "and open it in the requesting Desktop. Validation errors leave the installed "
            "plugin unchanged. Use when the user requests adding or updating a plugin."
        ),
        side_effect_level=SideEffectLevel.WRITE,
    )
    async def register_desktop_plugin(
        self, invocation: ToolInvocation, package_path: str
    ) -> dict:
        if (
            not self.client
            or invocation.request_context.actor.principal_id != self.owner
        ):
            raise PermissionError("Plugin registration requires a Desktop client")
        package = await self._read(invocation, package_path)
        return await self.store.register(self.owner, self.client, package)
