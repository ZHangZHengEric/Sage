"""Bounded native trace content and reconstruction of historical diagnostics."""

from __future__ import annotations

from itertools import chain
from collections.abc import Mapping
import hashlib
import json
import sys
from datetime import datetime, date, time, timedelta
from decimal import Decimal
from enum import Enum
from uuid import UUID

from pydantic import BaseModel
from pydantic_core import to_jsonable_python


_JSON_SCALARS = (datetime, date, time, timedelta, Decimal, UUID)


def retained_size(value, limit, seen=None):
    """Conservative heap reservation, stopping traversal as soon as over budget."""
    seen = seen if seen is not None else set()
    if id(value) in seen:
        return 0
    seen.add(id(value))
    size = sys.getsizeof(value)
    if size > limit:
        return size
    if isinstance(value, BaseModel):
        # Include SDK extension fields without calling a serializer or
        # materializing a copy before its dictionaries pass admission.
        size += retained_size(value.__dict__, limit - size, seen)
        if size <= limit:
            size += retained_size(value.__pydantic_extra__, limit - size, seen)
        return size
    if isinstance(value, Mapping):
        items = (item for pair in value.items() for item in pair)
    elif isinstance(value, (tuple, list, set)):
        items = iter(value)
    else:
        return size
    for item in items:
        size += retained_size(item, limit - size, seen)
        if size > limit:
            break
    return size


def json_working_size(value, limit, ancestors=None):
    """Bound JSON escape expansion without building an encoded string.

    Unknown objects are rejected rather than invoking arbitrary __str__ or
    model_dump methods before admission. Pydantic field dictionaries are read
    directly; values that cannot be represented as JSON are best effort loss.
    """
    if isinstance(value, str):
        chars = len(value) + value.count('"') + value.count("\\")
        if not value.isprintable():
            for code in range(32):
                chars += value.count(chr(code)) * (
                    1 if code in {8, 9, 10, 12, 13} else 5
                )
        return chars * (1 if value.isascii() else 4) + 2
    if value is None or isinstance(value, (bool, int, float)):
        return sys.getsizeof(value) * 3
    if isinstance(value, _JSON_SCALARS):
        # Only known scalar types are admitted here. Their JSON conversion runs
        # in the worker, after both heap and encoding reservations succeed.
        return sys.getsizeof(value) * 8 + 128
    if isinstance(value, Enum):
        return json_working_size(value.value, limit, ancestors)
    ancestors = ancestors if ancestors is not None else set()
    if id(value) in ancestors or len(ancestors) >= 64:
        return limit + 1
    identity = id(value)
    ancestors.add(identity)
    try:
        if isinstance(value, BaseModel):
            # Preflight iterates stored fields and SDK extras without merging
            # their dictionaries. Conversion is allowed only after admission.
            pairs = chain(
                value.__dict__.items(), (value.__pydantic_extra__ or {}).items()
            )
            items = (item for pair in pairs for item in pair)
        elif isinstance(value, Mapping):
            if any(
                not isinstance(key, (str, int, float, bool, type(None)))
                for key in value
            ):
                return limit + 1
            items = (item for pair in value.items() for item in pair)
        elif isinstance(value, (list, tuple)):
            items = iter(value)
        else:
            return limit + 1
        total = 2
        for item in items:
            total += json_working_size(item, limit - total, ancestors) + 2
            if total > limit:
                break
        return total
    finally:
        ancestors.remove(identity)


def _model_fields(value):
    return {**value.__dict__, **(value.__pydantic_extra__ or {})}


def raw_trace_value(value):
    """Normalize JSON values without a whole-payload dumps/loads round trip."""
    if isinstance(value, BaseModel):
        value = _model_fields(value)
    if isinstance(value, Mapping):
        return {_json_key(key): raw_trace_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [raw_trace_value(item) for item in value]
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    if isinstance(value, _JSON_SCALARS):
        return to_jsonable_python(value)
    if isinstance(value, Enum):
        return raw_trace_value(value.value)
    # This branch is normally refused by json_working_size before admission.
    raise TypeError("raw trace content must contain JSON values")


def _json_key(value):
    if isinstance(value, str):
        return value
    if value is None or isinstance(value, (int, float, bool)):
        return json.dumps(value)
    raise TypeError("raw trace object keys must be JSON scalar values")


def reconstruct(spans):
    """Return valid records and explicit gaps, even if the manifest was lost."""
    records, gaps = {}, []
    for span in spans:
        attrs = span.get("attributes", {})
        if attrs.get("sage.diagnostic.format") != "chunks/v1":
            continue
        record = records.setdefault(
            (attrs["run_id"], attrs["sage.diagnostic.record_id"]),
            {"chunks": {}, "manifest": None, "attrs": attrs, "at": span["start_time"]},
        )
        if span["name"] == "sage.diagnostic.chunk":
            record["chunks"][int(attrs["sage.diagnostic.sequence"])] = attrs[
                "sage.diagnostic.text"
            ]
        elif span["name"] == "sage.diagnostic.record":
            record["manifest"] = attrs
    restored = []
    for record in records.values():
        attrs, marker, chunks = record["attrs"], record["manifest"], record["chunks"]
        count = int(marker["sage.diagnostic.chunks"]) if marker else -1
        text = "".join(chunks[key] for key in sorted(chunks))
        complete = (
            len(chunks) == count
            and set(chunks) == set(range(count))
            and hashlib.sha256(text.encode()).hexdigest()
            == marker["sage.diagnostic.sha256"]
        )
        if not complete:
            gaps.append(
                {
                    "run_id": attrs["run_id"],
                    "request_id": attrs.get("request_id"),
                    "record_id": attrs["sage.diagnostic.record_id"],
                    "kind": attrs["sage.diagnostic.kind"],
                    "expected_chunks": count if marker else None,
                    "received_chunks": len(chunks),
                }
            )
            continue
        event = {
            "sage.diagnostic.kind": attrs["sage.diagnostic.kind"],
            "sage.diagnostic.data": text,
            "run_id": attrs["run_id"],
            "session_id": attrs["session_id"],
        }
        restored.append((record["at"], event))
    return restored, gaps
