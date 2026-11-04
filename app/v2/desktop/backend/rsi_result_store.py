"""Indexed RSI results. The overview contains grades and case references."""
from __future__ import annotations

import filecmp
import gzip
import hashlib
import json
import os
import posixpath
import shutil
import tempfile
from pathlib import Path

import ijson
from ijson.common import ObjectBuilder

_INDEX = "result-index-v1"
_REF = "$rsi_result_part"
_CALL_EVIDENCE = "$rsi_call_evidence"
_OBJECTS = {"report", "baseline", "selected", "evaluation", "final_verification", "candidate", "incumbent"}
_COLLECTIONS = {"rounds", "iterations", "agent_calls", "cases", "stability_checks"}
_LEGACY_STREAMS = {"report.agent_calls.item", "report.rounds.item", "iterations.item"}


def _read(path):
    with path.open(encoding="utf-8") as stream:
        return json.load(stream)


def _write(path, value):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, separators=(",", ":"))


def _digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()


def _journal_evidence(root):
    """Index exact report fields in the durable audit without retaining their payloads."""
    locations = {}
    for path in sorted(root.glob("audit*.jsonl")):
        with path.open("rb") as stream:
            while True:
                offset = stream.tell()
                line = stream.readline()
                if not line:
                    break
                prefix = line[:512]
                if b"agent_call_" not in prefix and b"test_design_call_completed" not in prefix:
                    continue
                try:
                    record = json.loads(line)
                except (ValueError, UnicodeError):
                    continue
                event = record.get("event")
                if event == "agent_call_started":
                    fields = [("request",)]
                elif event == "agent_call_completed":
                    fields = [("observation",)]
                elif event in {"test_design_call_completed", "final_test_design_call_completed"}:
                    fields = [("call", "request"), ("call", "observation")]
                else:
                    continue
                for field in fields:
                    value = _journal_field(record, field)
                    if value:
                        digest = _digest(value)
                        locations.setdefault(digest, [path.name, offset, list(field), digest])
    return locations


def _journal_field(record, field):
    value = record.get("data")
    for key in field:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def _link_call(call, locations):
    if not isinstance(call, dict) or _CALL_EVIDENCE in call:
        return call
    inline = dict(call)
    references = {}
    for key in ("request", "observation"):
        if key in call and (location := locations.get(_digest(call[key]))) is not None:
            references[key] = location
            inline.pop(key)
    return {_CALL_EVIDENCE: references, "call": inline} if references else call


def _read_call(root, value):
    if not isinstance(value, dict) or set(value) != {_CALL_EVIDENCE, "call"}:
        return value
    call = dict(value["call"])
    for key, (name, offset, field, digest) in value[_CALL_EVIDENCE].items():
        if Path(name).name != name or not name.startswith("audit") or not name.endswith(".jsonl"):
            raise ValueError("Invalid RSI audit evidence reference")
        with (root / name).open("rb") as stream:
            stream.seek(offset)
            evidence = _journal_field(json.loads(stream.readline()), field)
        if _digest(evidence) != digest:
            raise ValueError("RSI audit evidence differs from the indexed result")
        call[key] = evidence
    return call


class _Writer:
    def __init__(self, path, root):
        self.path = path
        self.root = root
        self.evidence = None
        self.parts = {}

    def call(self, value):
        if self.evidence is None:
            self.evidence = _journal_evidence(self.root)
        return self.part(_link_call(value, self.evidence))

    def part(self, value):
        data = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()
        digest = hashlib.sha256(data).digest()
        if digest not in self.parts:
            number = len(self.parts) + 1
            fd = os.open(self.path / f"{number}.json.gz", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as stream:
                stream.write(gzip.compress(data, compresslevel=3, mtime=0))
            self.parts[digest] = number
        return {_REF: self.parts[digest]}

    def split(self, value):
        if not isinstance(value, dict):
            return value, value
        # These objects contain arbitrary user data and must remain literal.
        if {"case", "observation", "grade"} <= value.keys():
            ref = self.part(value)
            from .rsi_presentation import summarize_grade

            overview = {"case": value["case"], "grade": summarize_grade(value["grade"])}
            overview["trials"] = [{"grade": summarize_grade(item["grade"])} for item in value.get("trials", [])]
            overview["result_part"] = ref[_REF]
            return ref, overview
        index, overview = {}, {}
        for key, item in value.items():
            if key in _COLLECTIONS and isinstance(item, (tuple, list)):
                refs, summaries = [], []
                for entry in item:
                    if key == "agent_calls":
                        refs.append(self.call(entry))
                        continue
                    ref, summary = self.split(entry)
                    refs.append(ref if _is_ref(ref) else self.part(ref))
                    summaries.append(summary)
                index[key] = refs
                if key != "agent_calls":
                    overview[key] = summaries
            elif key in _OBJECTS and isinstance(item, dict):
                index[key], overview[key] = self.split(item)
            else:
                index[key] = item
                if key == "comparison" and isinstance(item, dict):
                    overview[key] = {k: item[k] for k in ("reference_package_hash", "splits") if k in item}
                elif key == "patch" and isinstance(item, dict):
                    overview[key] = {"rationale": item.get("rationale")}
                elif key not in {"agent_calls", "internal_agents", "tuning_experience", "regressions"}:
                    overview[key] = item
        return index, overview


def _is_ref(value):
    return isinstance(value, dict) and set(value) == {_REF} and type(value[_REF]) is int


def _publish(root, build):
    target = root / _INDEX
    if target.exists():
        return
    temporary = Path(tempfile.mkdtemp(prefix=".result-index-", dir=root))
    try:
        writer = _Writer(temporary, root)
        index, overview = build(writer)
        _write(temporary / "index.json", index)
        _write(temporary / "overview.json", overview)
        _organize_parts(temporary)
        try:
            temporary.rename(target)
        except OSError:
            if not target.is_dir():
                raise
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)


def write_result(root, result):
    # Serialize model sections separately so even saving avoids a full JSON string.
    def build(writer):
        index, overview = {"report": {}}, {"report": {}}
        for key in type(result.report).model_fields:
            if key not in {"agent_calls", "rounds"}:
                full, summary = writer.split(result.report.model_dump(mode="json", include={key}))
                index["report"].update(full)
                overview["report"].update(summary)
        for key, entries, full, summary in (
            ("agent_calls", result.report.agent_calls, index["report"], None),
            ("rounds", result.report.rounds, index["report"], overview["report"]),
            ("iterations", result.iterations, index, overview),
        ):
            full[key] = []
            if summary is not None:
                summary[key] = []
            for entry in entries:
                data = entry.model_dump(mode="json")
                if summary is None:
                    full[key].append(writer.call(data))
                else:
                    ref, small = writer.split(data)
                    full[key].append(writer.part(ref))
                    summary[key].append(small)
        index["candidate_package"] = result.candidate_package.model_dump(mode="json")
        return index, overview

    _publish(root, build)


def index_legacy_result(root):
    """Read the old file in one pass, materializing at most one large entry at a time."""
    legacy = root / "result.json"

    def build(writer):
        outer = ObjectBuilder()
        streamed = {prefix: ([], []) for prefix in _LEGACY_STREAMS}
        entry = prefix = None
        with legacy.open("rb") as stream:
            for path, event, value in ijson.parse(stream, use_float=True):
                if entry is None and path in streamed and event == "start_map":
                    entry, prefix = ObjectBuilder(), path
                if entry is None:
                    outer.event(event, value)
                    continue
                entry.event(event, value)
                if path == prefix and event == "end_map":
                    refs, summaries = streamed[prefix]
                    if prefix == "report.agent_calls.item":
                        refs.append(writer.call(entry.value))
                    else:
                        ref, small = writer.split(entry.value)
                        refs.append(writer.part(ref))
                        summaries.append(small)
                    entry = None
        index, overview = writer.split(outer.value)
        overview.pop("candidate_package", None)
        for path, (refs, summaries) in streamed.items():
            if not refs:
                continue
            if path.startswith("report."):
                key = path.split(".")[1]
                index["report"][key] = refs
                if key != "agent_calls":
                    overview["report"][key] = summaries
            else:
                index["iterations"], overview["iterations"] = refs, summaries
        return index, overview

    if legacy.is_file():
        _publish(root, build)


def _slug(value):
    text = "".join(char if char.isalnum() or char in "-_" else "-" for char in str(value))
    return text.strip("-_")[:80] or "unknown"


def _number(value, fallback):
    return f"{value:03d}" if type(value) is int and value >= 0 else f"{fallback:03d}"


def _organize_parts(directory):
    """Publish a browsable hierarchy before retiring the flat compatibility paths."""
    target = directory / "records"
    if not target.is_dir():
        with tempfile.TemporaryDirectory(prefix=".rsi-records-", dir=directory) as temporary:
            staging = Path(temporary) / "records"
            staging.mkdir()
            paths = {}
            claimed = set()

            def unique(folder):
                candidate = folder
                number = 2
                while candidate.as_posix().casefold() in claimed:
                    candidate = folder.with_name(f"{folder.name}-{number}")
                    number += 1
                claimed.add(candidate.as_posix().casefold())
                return candidate

            def load(ref):
                number = ref[_REF]
                with gzip.open(directory / f"{number}.json.gz", "rt", encoding="utf-8") as stream:
                    return json.load(stream)

            def place(ref, folder, filename):
                number = ref[_REF]
                location = staging / folder
                location.mkdir(parents=True, exist_ok=True)
                relative = (folder / filename).as_posix()
                if number in paths:
                    _write(location / "reference.json", {
                        "path": posixpath.relpath(paths[number], folder.as_posix()),
                    })
                    return
                source = directory / f"{number}.json.gz"
                destination = staging / relative
                try:
                    os.link(source, destination)
                except OSError:
                    shutil.copyfile(source, destination)
                    destination.chmod(0o600)
                paths[number] = relative

            def visit(value, folder):
                if not isinstance(value, dict):
                    return
                for key in sorted(_OBJECTS):
                    if key in value:
                        visit(value[key], folder / key.replace("_", "-"))
                for key in sorted(_COLLECTIONS):
                    items = value.get(key)
                    if not isinstance(items, list):
                        continue
                    for position, ref in enumerate(items, 1):
                        if not _is_ref(ref):
                            continue
                        if key == "agent_calls":
                            entry = load(ref)
                            call = entry.get("call", entry)
                            role = _slug(call.get("role", "unknown"))
                            round_ = _number(call.get("round"), 0)
                            group = folder / "agent-calls" / role / f"round-{round_}"
                            place(ref, unique(group / f"call-{position:03d}"), "record.json.gz")
                            continue
                        entry = load(ref)
                        if key == "cases":
                            from .rsi_presentation import summarize_grade

                            case = entry.get("case", {})
                            split = _slug(case.get("split", "unknown"))
                            group = unique(folder / split / f"case-{_slug(case.get('id', position))}")
                            place(ref, group, "evidence.json.gz")
                            _write(staging / group / "summary.json", {
                                "case": case, "grade": summarize_grade(entry.get("grade")),
                            })
                            continue
                        label, field = {
                            "rounds": ("round", "round"),
                            "iterations": ("version", "iteration"),
                            "stability_checks": ("attempt", "attempt"),
                        }[key]
                        group = unique(folder / key.replace("_", "-") /
                                       f"{label}-{_number(entry.get(field), position)}")
                        place(ref, group, "record.json.gz")
                        _write(staging / group / "summary.json", {
                            k: entry[k] for k in (field, "reason", "accepted", "recommended",
                                                  "evaluation_reused", "parent_hash") if k in entry
                        })
                        visit(entry, group)

            index = _read(directory / "index.json")
            # Prefer round and baseline paths as the canonical home for shared evidence.
            report = index.get("report", {})
            visit({"rounds": report.get("rounds")}, Path("."))
            visit({key: value for key, value in report.items() if key != "rounds"}, Path("."))
            visit({"iterations": index.get("iterations")}, Path("."))
            # Retain any older record types that the semantic view does not recognize.
            for source in sorted(directory.glob("*.json.gz")):
                number = int(source.name.split(".", 1)[0])
                if number not in paths:
                    place({_REF: number}, Path("additional-records") / str(number), "record.json.gz")
            _write(staging / "paths.json", paths)
            (staging / "README.md").write_text(
                "# RSI 实验详情\n\n"
                "- 从上一级 overview.json 查看评分和结论。\n"
                "- rounds 按轮次组织，evaluation 下按数据集和用例查证据。\n"
                "- baseline、selected、final-verification 对应基线、保留版本和最终验证。\n"
                "- iterations 保存版本记录，agent-calls 按角色和轮次组织。\n"
                "- reference.json 的 path 相对于所在目录，共享证据只保存一份。\n"
                "- 调用证据可能引用实验根目录的 audit*.jsonl。\n",
                encoding="utf-8",
            )
            try:
                staging.rename(target)
            except OSError:
                if not target.is_dir():
                    raise
    for part, relative in _read(target / "paths.json").items():
        old = directory / f"{part}.json.gz"
        try:
            new = target / relative
            if os.path.samefile(old, new) or filecmp.cmp(old, new, shallow=False):
                old.unlink()
        except FileNotFoundError:
            pass


def organize_result(root):
    _organize_parts(root / _INDEX)


def _part_path(directory, part):
    records = directory / "records"
    try:
        paths = _read(records / "paths.json")
    except FileNotFoundError:
        return directory / f"{part}.json.gz"
    relative = paths.get(str(part))
    return records / relative if relative is not None else directory / f"{part}.json.gz"


def deduplicate_legacy_call_parts(root):
    """Reclaim redundant call shards in a legacy cache, leaving its source intact."""
    if not (root / "result.json").is_file():
        raise ValueError("Expected a legacy RSI result")
    directory = root / _INDEX
    index = _read(directory / "index.json")
    parts = {part[_REF] for part in index["report"].get("agent_calls", []) if _is_ref(part)}
    locations = _journal_evidence(root) if parts else {}
    savings = 0
    with tempfile.TemporaryDirectory(prefix=".rsi-call-parts-", dir=directory) as temporary:
        for part in sorted(parts):
            value = read_part(root, part)
            linked = _link_call(value, locations)
            if linked is value or _read_call(root, linked) != value:
                continue
            original = _part_path(directory, part)
            replacement = Path(temporary) / original.name
            with replacement.open("xb") as stream:
                os.fchmod(stream.fileno(), 0o600)
                stream.write(gzip.compress(
                    json.dumps(linked, ensure_ascii=False, separators=(",", ":")).encode(),
                    compresslevel=3, mtime=0,
                ))
            difference = original.stat().st_size - replacement.stat().st_size
            if difference > 0:
                replacement.replace(original)
                savings += difference
            else:
                replacement.unlink()
    return savings


def overview_exists(root):
    return (root / _INDEX / "overview.json").is_file()


def usage_snapshot_key(root, revision):
    files = [
        *root.glob("audit*.jsonl"),
        *(root / name for name in ("token-usage.jsonl", "scorer-model-calls.jsonl",
                                    "user-simulator-model-calls.jsonl")),
    ]
    stamps = []
    for path in sorted(files):
        try:
            stat = path.stat()
        except FileNotFoundError:
            continue
        stamps.append([path.name, stat.st_size, stat.st_mtime_ns])
    return [list(revision), stamps]


def read_measurement_overview(root, signature):
    try:
        value = _read(root / "measurement-overview-v1.json")
    except (OSError, ValueError):
        return None
    return (value["tests"], value["usage"]) if value.get("signature") == signature else None


def save_measurement_overview(root, signature, tests, usage):
    with tempfile.TemporaryDirectory(prefix=".rsi-measurements-", dir=root) as temporary:
        path = Path(temporary) / "overview.json"
        _write(path, {"signature": signature, "tests": tests, "usage": usage})
        path.replace(root / "measurement-overview-v1.json")


def read_overview(root):
    path = root / _INDEX / "overview.json"
    return _read(path) if path.is_file() else None


def read_part(root, part, *, case_only=False):
    if part < 1:
        raise ValueError("RSI result part not found")
    directory = root / _INDEX
    path = _part_path(directory, part)
    try:
        with gzip.open(path, "rt", encoding="utf-8") as stream:
            value = json.load(stream)
    except FileNotFoundError:
        # A legacy flat part can move while a desktop request is in flight.
        updated = _part_path(directory, part)
        if updated == path or not updated.is_file():
            raise ValueError("RSI result part not found") from None
        with gzip.open(updated, "rt", encoding="utf-8") as stream:
            value = json.load(stream)
    if case_only and not (isinstance(value, dict) and {"case", "observation", "grade"} <= value.keys()):
        raise ValueError("RSI result case not found")
    return value


def result_exists(root):
    return (root / _INDEX / "index.json").is_file() or (root / "result.json").is_file()


def result_chunks(root):
    """Reassemble full JSON for export without materializing the whole result."""
    index = root / _INDEX / "index.json"
    if (root / "result.json").is_file() or not index.is_file():
        with (root / "result.json").open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                yield chunk
        return

    def encode(value, *, structured=True):
        if structured and _is_ref(value):
            yield from encode(read_part(root, value[_REF]))
        elif structured and isinstance(value, dict) and not {"case", "observation", "grade"} <= value.keys():
            yield b"{"
            for number, (key, item) in enumerate(value.items()):
                if number:
                    yield b","
                yield json.dumps(key).encode() + b":"
                if key in _COLLECTIONS and isinstance(item, list):
                    yield b"["
                    for position, part in enumerate(item):
                        if position:
                            yield b","
                        if key == "agent_calls" and _is_ref(part):
                            yield from encode(_read_call(root, read_part(root, part[_REF])), structured=False)
                        else:
                            yield from encode(part)
                    yield b"]"
                else:
                    yield from encode(item, structured=key in _OBJECTS)
            yield b"}"
        else:
            for chunk in json.JSONEncoder(ensure_ascii=False, separators=(",", ":")).iterencode(value):
                yield chunk.encode()

    buffer = bytearray()
    for chunk in encode(_read(index)):
        buffer.extend(chunk)
        if len(buffer) >= 256 * 1024:
            yield bytes(buffer)
            buffer.clear()
    if buffer:
        yield bytes(buffer)


def read_result(root):
    legacy = root / "result.json"
    if legacy.is_file():
        return _read(legacy)

    def expand(value):
        if _is_ref(value):
            return expand(read_part(root, value[_REF]))
        if not isinstance(value, dict) or {"case", "observation", "grade"} <= value.keys():
            return value
        return {
            key: [
                _read_call(root, read_part(root, part[_REF])) if key == "agent_calls" and _is_ref(part) else expand(part)
                for part in item
            ] if key in _COLLECTIONS and isinstance(item, list)
            else expand(item) if key in _OBJECTS else item
            for key, item in value.items()
        }

    return expand(_read(root / _INDEX / "index.json"))
