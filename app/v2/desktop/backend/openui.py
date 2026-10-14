"""Desktop-owned OpenUI surfaces. UI source is data, never executable code."""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
import hashlib
import ipaddress
import json
import math
import os
import re
from pathlib import Path
import shutil
import sqlite3
import sys
from datetime import date
from urllib.parse import urlsplit
from typing import Any

from jsonschema import Draft202012Validator, ValidationError

from sagents.v2.context import ContextSegment, ContextStability

RUNTIME = Path(__file__).with_name("openui_runtime")
SCHEMA_VERSION = "sage.openui/1"
FIELD_COMPONENTS = {
    "Input",
    "Select",
    "Toggle",
    "NumberInput",
    "Slider",
    "DateInput",
    "CheckboxGroup",
    "RadioGroup",
}
CONTAINER_COMPONENTS = {
    "Stack",
    "Row",
    "Card",
    "Tabs",
    "Tab",
    "Accordion",
    "Section",
    "Deck",
    "Slide",
}


def validate_image_url(value: str):
    url = urlsplit(value)
    host = (url.hostname or "").lower()
    if (
        url.scheme != "https"
        or not host
        or url.username
        or url.password
        or url.port not in {None, 443}
    ):
        raise ValueError("Images require a public HTTPS URL")
    if "." not in host or host.endswith((".local", ".localhost", ".internal", ".test")):
        raise ValueError("Private image hosts are unsupported")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return
    if not address.is_global:
        raise ValueError("Private image addresses are unsupported")


def validate_field_value(field, value):
    component = field["component"]
    if component == "Toggle":
        if not isinstance(value, bool):
            raise ValueError(f"{field['name']} must be boolean")
    elif component in {"NumberInput", "Slider"}:
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or not field["min"] <= value <= field["max"]
        ):
            raise ValueError(f"Invalid number for {field['label']}")
    elif component == "CheckboxGroup":
        if (
            not isinstance(value, list)
            or any(
                not isinstance(item, str) or item not in field["options"]
                for item in value
            )
            or len(value) != len(set(value))
        ):
            raise ValueError(f"Invalid selection for {field['label']}")
        if field.get("required") and not value:
            raise ValueError(f"{field['label']} is required")
    else:
        if not isinstance(value, str) or len(value) > 8000:
            raise ValueError(
                f"{field['name']} must be a string of at most 8000 characters"
            )
        if field.get("required") and not value.strip():
            raise ValueError(f"{field['label']} is required")
        if (
            component in {"Select", "RadioGroup"}
            and value
            and value not in field["options"]
        ):
            raise ValueError(f"Invalid selection for {field['label']}")
        if component == "DateInput" and value:
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
                raise ValueError("Dates must use YYYY-MM-DD")
            date.fromisoformat(value)


def _digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def node_executable() -> str:
    # Installed Python lives at sage-runtime/python/{bin|python.exe}.
    for root in (
        Path(sys.executable).resolve().parent,
        *Path(sys.executable).resolve().parents[:4],
    ):
        if (root / "sage-runtime.json").is_file():
            binary = root / "node" / ("node.exe" if os.name == "nt" else "node")
            if binary.is_file():
                return str(binary)
            raise RuntimeError("The bundled OpenUI Node runtime is missing")
    binary = shutil.which("node")
    if binary is None:
        raise RuntimeError(
            "OpenUI source mode requires Node.js 22+; desktop installers include it"
        )
    return binary


class OpenUiParser:
    """One bounded local parser process; serial IPC prevents crossed responses."""

    def __init__(self):
        self.process = None
        self.lock = asyncio.Lock()

    async def parse(self, code: str, *, complete: bool, stream_id: str = "default"):
        if not code.strip() or len(code.encode()) > 65536:
            raise ValueError("OpenUI code must contain 1–65536 UTF-8 bytes")
        async with self.lock:
            if self.process is None or self.process.returncode is not None:
                self.process = await asyncio.create_subprocess_exec(
                    node_executable(),
                    "--max-old-space-size=96",
                    str(RUNTIME / "worker.cjs"),
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.DEVNULL,
                    limit=1024 * 1024,
                    env={
                        k: v
                        for k, v in os.environ.items()
                        if k not in {"NODE_OPTIONS", "NODE_PATH"}
                    },
                )
            try:
                self.process.stdin.write(
                    (
                        json.dumps(
                            {"code": code, "complete": complete, "stream_id": stream_id}
                        )
                        + "\n"
                    ).encode()
                )
                await self.process.stdin.drain()
                stdout = await asyncio.wait_for(self.process.stdout.readline(), 5)
                result = json.loads(stdout)
                if "error" in result:
                    raise ValueError(str(result["error"])[:2000])
                if complete:
                    validate_tree(result["tree"])
                return result["tree"]
            except ValueError:
                raise
            except BaseException:
                await self.close()
                raise

    async def close(self):
        if self.process is not None:
            if self.process.returncode is None:
                self.process.kill()
            await self.process.wait()
            self.process = None


def openui_blocks(text):
    """Recognize only standalone openui fences, ignoring other fenced code."""
    blocks = []
    fence = None
    start = 0
    code = []
    offset = 0
    for line in text.splitlines(keepends=True):
        match = re.fullmatch(r"(`{3,})([^\r\n]*)[\r\n]*", line)
        if fence is None:
            if match:
                fence = (len(match[1]), match[2].strip() == "openui")
                start = offset
                code = []
        elif match and len(match[1]) >= fence[0] and not match[2].strip():
            if fence[1]:
                blocks.append(
                    {
                        "code": "".join(code),
                        "closed": True,
                        "start": start,
                        "end": offset + len(line),
                    }
                )
            fence = None
        elif fence[1]:
            code.append(line)
        offset += len(line)
    if fence and fence[1]:
        blocks.append(
            {"code": "".join(code), "closed": False, "start": start, "end": len(text)}
        )
    return blocks


def validate_tree(tree: dict[str, Any]) -> tuple[dict[str, dict], dict[str, str]]:
    schema = json.loads((RUNTIME / "schema.json").read_text())
    fields: dict[str, dict] = {}
    actions: dict[str, str] = {}
    count = 0
    calculations = []
    chart_references = []
    bindings = {}
    referenced_fields = []

    def visit(node, depth=0, parent=None, operand=False):
        nonlocal count
        count += 1
        if count > 300 or depth > 12 or not isinstance(node, dict):
            raise ValueError("Invalid or oversized UI tree")
        if (
            set(node) - {"component", "props", "id"}
            or not {"component", "props"} <= set(node)
            or node["component"] not in schema["$defs"]
        ):
            raise ValueError("Unknown UI component")
        name, props = node["component"], node["props"]
        if operand and name not in {
            "NumberInput",
            "Slider",
            "Computed",
            "CheckboxGroup",
        }:
            raise ValueError("Calculation references must be numeric")
        if "id" in node:
            identifier = node["id"]
            if not isinstance(identifier, str) or not re.fullmatch(
                r"[A-Za-z][A-Za-z0-9_-]{0,63}", identifier
            ):
                raise ValueError("Invalid numeric binding identifier")
            if name not in {"NumberInput", "Slider", "Computed", "CheckboxGroup"}:
                raise ValueError("Only numeric components can define bindings")
            if identifier in bindings and bindings[identifier] != node:
                raise ValueError("Conflicting numeric bindings")
            bindings[identifier] = node
        if name == "Deck" and depth != 0 or name == "Slide" and parent != "Deck":
            raise ValueError("Deck must be the root and Slide belongs directly to Deck")
        try:
            properties_schema = schema["$defs"][name]
            if name in CONTAINER_COMPONENTS:
                # Official .ref slots describe parser component calls. The native
                # tree wraps each child in {component, props}, so validate its
                # own properties recursively below, retaining array size limits.
                properties_schema = {
                    **properties_schema,
                    "properties": {
                        **properties_schema["properties"],
                        "children": {
                            **properties_schema["properties"]["children"],
                            "items": {},
                        },
                    },
                }
            Draft202012Validator(properties_schema).validate(props)
        except ValidationError as exc:
            raise ValueError(f"Invalid {name} properties: {exc.message}") from exc
        if name in CONTAINER_COMPONENTS:
            expected = {"Tabs": "Tab", "Accordion": "Section", "Deck": "Slide"}.get(
                name
            )
            if name == "Slide":
                from .openui_slides import validate_slide

                validate_slide(props)
            for child in props["children"]:
                if expected and child.get("component") != expected:
                    raise ValueError(f"{name} children must be {expected}")
                visit(child, depth + 1, name)
        elif name == "Table":
            if any(len(row) != len(props["columns"]) for row in props["rows"]):
                raise ValueError("Table rows must match the columns")
        elif name in FIELD_COMPONENTS:
            key = props["name"]
            if operand:
                referenced_fields.append({"component": name, **props})
                return
            if key in fields:
                raise ValueError("Field names must be unique")
            if name in {"NumberInput", "Slider"} and props["min"] >= props["max"]:
                raise ValueError("Numeric field min must be below max")
            if name in {"Select", "CheckboxGroup", "RadioGroup"} and len(
                set(props["options"])
            ) != len(props["options"]):
                raise ValueError("Field options must be unique")
            fields[key] = {"component": name, **props}
            # Empty required defaults are valid until the user fills them.
            validate_field_value({**fields[key], "required": False}, props["value"])
        elif name == "Button":
            if props["action"] in actions:
                raise ValueError("Action identifiers must be unique")
            actions[props["action"]] = props["label"]
        elif name == "Image":
            validate_image_url(props["url"])
        elif name == "Chart":
            if any(
                len(series["values"]) != len(props["labels"])
                for series in props["series"]
            ):
                raise ValueError("Chart values must match labels")
            chart_references.extend(
                (value, props["type"])
                for series in props["series"]
                for value in series["values"]
                if isinstance(value, (str, dict))
            )
            for series in props["series"]:
                for value in series["values"]:
                    if isinstance(value, dict):
                        visit(value, depth + 1, operand=True)
            if props["type"] == "pie" and (
                len(props["series"]) != 1
                or any(
                    v < 0
                    for v in props["series"][0]["values"]
                    if isinstance(v, (int, float))
                )
            ):
                raise ValueError("Pie charts need one nonnegative series")
        elif name == "Progress":
            value = props["value"]
            if isinstance(value, (int, float)) and not 0 <= value <= 100:
                raise ValueError("Progress literals must be between 0 and 100")
            if isinstance(value, dict):
                visit(value, depth + 1, operand=True)
            chart_references.append((value, "progress"))
        elif name == "Computed":
            calculations.append(props)
            for value in props["inputs"]:
                if isinstance(value, dict):
                    visit(value, depth + 1, operand=True)
            size = {
                "difference": 2,
                "divide": 2,
                "percent": 2,
                "ratioPercent": 2,
                "compoundGrowth": 3,
                "loanPayment": 3,
            }.get(props["operation"])
            if size and len(props["inputs"]) != size:
                raise ValueError("Invalid calculation argument count")
        elif name == "Diagram":
            ids = [item["id"] for item in props["nodes"]]
            if len(set(ids)) != len(ids) or any(
                endpoint not in ids for edge in props["edges"] for endpoint in edge
            ):
                raise ValueError("Diagram nodes and edges must be consistent")

    visit(tree)
    for field in referenced_fields:
        if fields.get(field["name"]) != field:
            raise ValueError(
                "Calculation inputs must reference rendered numeric fields"
            )
    for identifier, node in bindings.items():
        if identifier in fields and (
            node["component"] not in {"NumberInput", "Slider", "CheckboxGroup"}
            or node["props"]["name"] != identifier
        ):
            raise ValueError("Ambiguous numeric binding")

    numeric_visits = 0

    def numeric(value, path=(), selection=False):
        nonlocal numeric_visits
        numeric_visits += 1
        if numeric_visits > 2048:
            raise ValueError("Calculation dependency graph exceeds limits")
        if len(path) > 12:
            raise ValueError("Calculation dependency depth exceeds limits")
        if isinstance(value, str):
            if value in path:
                raise ValueError("Cyclic calculation dependency")
            if value in fields:
                if fields[value]["component"] not in (
                    {"CheckboxGroup"} if selection else {"NumberInput", "Slider"}
                ):
                    raise ValueError("Calculations require numeric fields")
                return
            if value not in bindings:
                raise ValueError("Unknown numeric binding")
            numeric(bindings[value], (*path, value), selection)
        elif isinstance(value, dict):
            if value["component"] == "Computed" and not selection:
                for item in value["props"]["inputs"]:
                    numeric(item, (*path, None), value["props"]["operation"] == "count")
            elif value["component"] not in (
                {"CheckboxGroup"} if selection else {"NumberInput", "Slider"}
            ):
                raise ValueError("Calculation references must be numeric")

        elif selection:
            raise ValueError("Count requires checkbox selections")

    for reference, chart_type in chart_references:
        numeric(reference)
        if (
            isinstance(reference, str)
            and reference in fields
            and chart_type == "pie"
            and fields[reference]["min"] < 0
        ):
            raise ValueError("Chart bindings require compatible numeric fields")
    for calculation in calculations:
        for value in calculation["inputs"]:
            numeric(value, selection=calculation["operation"] == "count")
    return fields, actions


class OpenUiStore:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        with self.connection() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS openui_surfaces(id TEXT PRIMARY KEY, owner TEXT NOT NULL, session TEXT NOT NULL, data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS openui_publications(operation TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS openui_submissions(id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, run_id TEXT);
                CREATE INDEX IF NOT EXISTS openui_session ON openui_surfaces(owner,session);
            """)

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def publish(
        self,
        *,
        owner,
        session,
        agent,
        run,
        operation,
        key,
        code,
        tree,
        fallback,
        message_text="",
    ):
        fingerprint = _digest([owner, session, agent, run, key, code, fallback])
        operation = _digest([owner, run, operation])
        sid = "openui_" + _digest([owner, session, agent, key])[:32]
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute(
                "SELECT * FROM openui_publications WHERE operation=?", (operation,)
            ).fetchone()
            if old:
                if old["fingerprint"] != fingerprint:
                    raise ValueError(
                        "UI publication identity already has different content"
                    )
                return json.loads(old["data"])
            old = db.execute(
                "SELECT data FROM openui_surfaces WHERE id=?", (sid,)
            ).fetchone()
            revision = json.loads(old["data"])["revision"] + 1 if old else 1
            data = dict(
                schema_version=SCHEMA_VERSION,
                surface_id=sid,
                revision=revision,
                session_id=session,
                agent_id=agent,
                run_id=run,
                surface_key=key,
                library_version="sage-desktop/5;lang-core/1.0.0",
                code=code,
                tree=tree,
                fallback=fallback,
                submitted=False,
                message_text=message_text,
            )
            encoded = json.dumps(data, ensure_ascii=False)
            db.execute(
                "INSERT INTO openui_surfaces VALUES(?,?,?,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data",
                (sid, owner, session, encoded),
            )
            db.execute(
                "INSERT INTO openui_publications VALUES(?,?,?)",
                (operation, fingerprint, encoded),
            )
            return data

    def list(self, owner, session):
        with self.connection() as db:
            values = []
            for row in db.execute(
                "SELECT data FROM openui_surfaces WHERE owner=? AND session=? ORDER BY rowid",
                (owner, session),
            ):
                data = json.loads(row["data"])
                submission = db.execute(
                    "SELECT run_id FROM openui_submissions WHERE id=?",
                    (self.submission_id(data),),
                ).fetchone()
                if submission:
                    data["submitted"] = True
                    data["submission_run_id"] = submission["run_id"]
                values.append(data)
            return values

    @staticmethod
    def submission_id(surface):
        return f"{surface['surface_id']}:{surface['revision']}"

    def get(self, owner, session, sid):
        return next(
            (
                value
                for value in self.list(owner, session)
                if value["surface_id"] == sid
            ),
            None,
        )

    def claim(self, surface, action, values):
        fields, actions = validate_tree(surface["tree"])
        if action not in actions or set(values) - fields.keys():
            raise ValueError("Unknown UI action or field")
        normalized = {}
        for key, field in fields.items():
            value = values.get(key, field["value"])
            validate_field_value(field, value)
            normalized[key] = (
                [option for option in field["options"] if option in value]
                if field["component"] == "CheckboxGroup"
                else value
            )
        fingerprint = _digest([action, normalized])
        sid = self.submission_id(surface)
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            # Recheck the revision inside the claim transaction.
            current = db.execute(
                "SELECT data FROM openui_surfaces WHERE id=?", (surface["surface_id"],)
            ).fetchone()
            if (
                current is None
                or json.loads(current["data"])["revision"] != surface["revision"]
            ):
                raise ValueError("This UI has been replaced; use the latest version")
            existing = db.execute(
                "SELECT * FROM openui_submissions WHERE id=?", (sid,)
            ).fetchone()
            if existing:
                if existing["fingerprint"] != fingerprint:
                    raise ValueError("This UI has already been submitted")
                if not existing["run_id"]:
                    raise ValueError(
                        "Submission is pending reconciliation; do not submit again"
                    )
                return normalized, existing["run_id"]
            db.execute(
                "INSERT INTO openui_submissions VALUES(?,?,NULL)", (sid, fingerprint)
            )
        return normalized, None

    def accepted(self, surface, run_id):
        with self.connection() as db:
            db.execute(
                "UPDATE openui_submissions SET run_id=? WHERE id=?",
                (run_id, self.submission_id(surface)),
            )


class OpenUiContextProvider:
    async def segments(self, command, *, run_id=None):
        interactive = command.config.metadata.get("ui_preference") == "interactive"
        routing = (
            "The user enabled Prefer interactive UI for this chat. Prefer native UI for structured answers, comparisons, dashboards, calculators, forms and presentations. Keep ordinary prose minimal. Respect an explicit request for plain text; do not force UI for greetings or simple facts. "
            if interactive
            else "Choose the presentation automatically from the user's natural request: use native UI for structured comparisons, dashboards, calculators, forms and presentations when useful, and prose for ordinary questions. The user never needs to mention OpenUI or its protocol. "
        )
        routing += (
            "Native interactive UI is a built-in answer format. Rendering has no tool-loading prerequisite. "
            "Use tools only for operations independently required by the user's task, not to enable presentation. "
            "Do not infer a file-development workflow from an interactive presentation request or older conversation patterns. "
            "The system-provided component contract is ready to use; when preloaded, the Skill needs no further loading. "
        )
        segments = [
            ContextSegment(
                segment_id="desktop_openui_preference",
                stability=ContextStability.SEMI_STABLE,
                priority=-42,
                content=routing,
            ),
            ContextSegment(
                segment_id="desktop_openui",
                stability=ContextStability.STABLE,
                priority=-40,
                content=(RUNTIME / "prompt.txt").read_text(),
            ),
        ]
        if interactive:
            skill = RUNTIME.parents[3] / "skills" / "sage-openui" / "SKILL.md"
            if not skill.is_file():
                # Frozen installers keep built-in Skills next to the app package.
                skill = RUNTIME.parents[4] / "skills" / "sage-openui" / "SKILL.md"
            segments.append(
                ContextSegment(
                    segment_id="desktop_openui_skill",
                    stability=ContextStability.SEMI_STABLE,
                    priority=-41,
                    content="The sage-openui Skill is already preloaded by the Desktop host; no load_skill tool call is needed.\n\n"
                    + skill.read_text(),
                )
            )
        return tuple(segments)


class OpenUiProjector:
    """Presentation projection of authoritative message events, outside the kernel."""

    def __init__(self, service, owner):
        self.service = service
        self.owner = owner
        self.texts = {}
        self.previews = {}

    def remember(self, event):
        if event.type == "message.delta" and isinstance(event.data.delta, str):
            key = event.item_id
            self.texts[key] = self.texts.get(key, "") + event.data.delta
        elif event.type == "message.completed" and event.data.item is not None:
            item = event.data.item
            if item.data.kind == "message" and item.data.role == "assistant":
                self.texts[item.item_id] = "".join(
                    block.text for block in item.data.content if block.kind == "text"
                )

    async def project(self, event):
        self.remember(event)
        if event.type not in {"message.delta", "message.completed"}:
            return []
        key = (
            event.data.item.item_id
            if event.type == "message.completed" and event.data.item
            else event.item_id
        )
        text = self.texts.get(key, "")
        blocks = openui_blocks(text)
        if not blocks:
            return []
        final = event.type == "message.completed"
        frames = []
        for index, block in enumerate(blocks):
            surface = {
                "schema_version": SCHEMA_VERSION,
                "message_id": key,
                "block_index": index,
                "run_id": event.run_id,
                "session_id": event.session_id,
                "revision": 1,
                "source_sequence": event.run_sequence,
                "complete": False,
                "tree": None,
                "fallback": "",
                "submitted": False,
            }
            try:
                complete = final and block["closed"]
                if final and not complete:
                    raise ValueError("OpenUI fence was not closed")
                tree = await self.service.openui_parser.parse(
                    block["code"],
                    complete=complete,
                    stream_id=f"{event.run_id}:{key}:{index}",
                )
                surface["tree"] = tree
                if tree is not None:
                    self.previews[(key, index)] = tree
                surface["complete"] = complete
                if complete:
                    command = await self.service.session_access.get_start_command(
                        event.run_id, self.service._context(self.owner)
                    )
                    saved = self.service.openui_store.publish(
                        owner=self.owner,
                        session=event.session_id,
                        agent=command.agent_id,
                        run=event.run_id,
                        operation=f"{key}:{index}",
                        key=f"{key}:{index}",
                        code=block["code"],
                        tree=tree,
                        fallback="",
                        message_text=text,
                    )
                    surface.update(saved)
                    surface["message_id"] = key
                    surface["block_index"] = index
            except Exception as exc:
                # A bad UI must not terminate the ordinary text stream.
                surface["error"] = str(exc)[:2000] if final else ""
                surface["tree"] = self.previews.get((key, index))
            frames.append({"kind": "openui.updated", "surface": surface})
        return frames
