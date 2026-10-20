"""Best-effort raw evidence in byte-bounded, independently exported chunks.

Only this process queue is retained. No diagnostic business storage is created.
A record manifest and SHA256 make backend loss detectable during reconstruction.
"""
from __future__ import annotations

import copy
from collections import deque
from itertools import chain
from collections.abc import Mapping
import hashlib
import json
import sys
import threading
from uuid import uuid4

from pydantic import BaseModel

from sagents.v2.contracts.common import utc_now
from sagents.v2.runtime.observability.contracts import TraceSpan


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
        chars = len(value) + value.count('"') + value.count('\\')
        if not value.isprintable():
            for code in range(32):
                chars += value.count(chr(code)) * (1 if code in {8, 9, 10, 12, 13} else 5)
        return chars * (1 if value.isascii() else 4) + 2
    if value is None or isinstance(value, (bool, int, float)):
        return sys.getsizeof(value) * 3
    ancestors = ancestors if ancestors is not None else set()
    if id(value) in ancestors or len(ancestors) >= 64:
        return limit + 1
    identity = id(value)
    ancestors.add(identity)
    try:
        if isinstance(value, BaseModel):
            # Preflight iterates stored fields and SDK extras without merging
            # their dictionaries. Conversion is allowed only after admission.
            pairs = chain(value.__dict__.items(), (value.__pydantic_extra__ or {}).items())
            items = (item for pair in pairs for item in pair)
        elif isinstance(value, Mapping):
            if any(not isinstance(key, (str, int, float, bool, type(None))) for key in value):
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
        return {_json_key(key):raw_trace_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [raw_trace_value(item) for item in value]
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    # This branch is normally refused by json_working_size before admission.
    raise TypeError("raw trace content must contain JSON values")


def _json_key(value):
    if isinstance(value, str):
        return value
    if value is None or isinstance(value, (int, float, bool)):
        return json.dumps(value)
    raise TypeError("raw trace object keys must be JSON scalar values")


def _json_fragments(value, chunk_chars):
    """Serialize large strings in bounded pieces, including escaped text."""
    if isinstance(value, BaseModel):
        value = _model_fields(value)
    if isinstance(value, str):
        yield '"'
        for offset in range(0, len(value), chunk_chars):
            yield json.dumps(value[offset:offset + chunk_chars], ensure_ascii=False)[1:-1]
        yield '"'
    elif isinstance(value, Mapping):
        yield '{'
        for index, (key, item) in enumerate(value.items()):
            if index:
                yield ','
            yield from _json_fragments(_json_key(key), chunk_chars)
            yield ':'
            yield from _json_fragments(item, chunk_chars)
        yield '}'
    elif isinstance(value, (list, tuple)):
        yield '['
        for index, item in enumerate(value):
            if index:
                yield ','
            yield from _json_fragments(item, chunk_chars)
        yield ']'
    elif value is None or isinstance(value, (int, float, bool)):
        yield json.dumps(value)
    else:
        raise TypeError("raw evidence must contain JSON values")


class RawEvidencePipeline:
    def __init__(self, *, max_bytes=16 * 1024 * 1024, chunk_chars=16 * 1024):
        if max_bytes < 4096 or chunk_chars < 1:
            raise ValueError("invalid raw evidence byte or chunk limit")
        self.max_bytes, self.chunk_chars = max_bytes, chunk_chars
        self._condition = threading.Condition(threading.RLock())
        self._queue = deque()
        self._bytes = self.dropped_records = self.failed_records = 0
        self._closed = False
        self._worker = None

    def submit(self, sink, trace_id, parent_id, session_id, run_id, kind, payload, at):
        with self._condition:
            available = self.max_bytes - self._bytes
            size = retained_size(payload, available // 2) * 2 + 1024
            if (self._closed or size > available or
                    json_working_size(payload, self.max_bytes) > self.max_bytes):
                self.dropped_records += 1
                return False
            self._bytes += size
            try:
                payload = copy.deepcopy(payload)
            except Exception:
                self._bytes -= size
                self.failed_records += 1
                return False
            self._queue.append((size, sink, trace_id, parent_id, session_id, run_id, kind, payload, at))
            if self._worker is None:
                self._worker = threading.Thread(target=self._run, name='sage-raw-evidence', daemon=True)
                self._worker.start()
            self._condition.notify_all()
            return True

    def statistics(self):
        with self._condition:
            return dict(retained_bytes=self._bytes, max_bytes=self.max_bytes,
                        dropped_records=self.dropped_records, failed_records=self.failed_records,
                        queued_records=len(self._queue))

    def _run(self):
        while True:
            with self._condition:
                while not self._queue and not self._closed:
                    self._condition.wait()
                if not self._queue:
                    return
                item = self._queue.popleft()
            try:
                self._export(*item[1:])
            except Exception:
                with self._condition:
                    self.failed_records += 1
            finally:
                with self._condition:
                    self._bytes -= item[0]
                    self._condition.notify_all()

    def _export(self, sink, trace_id, parent_id, session_id, run_id, kind, payload, at):
        record_id, digest = uuid4().hex, hashlib.sha256()
        count = 0
        def emit(name, values):
            attrs = {'session_id':session_id, 'run_id':run_id, 'request_id':payload.get('request_id'),
                     'sage.diagnostic.format':'chunks/v1', 'sage.diagnostic.kind':kind,
                     'sage.diagnostic.record_id':record_id, **values}
            span = TraceSpan(trace_id=trace_id, span_id=uuid4().hex[:16], parent_span_id=parent_id,
                             name=name, session_id=session_id, run_id=run_id,
                             request_id=payload.get('request_id'), start_time=at, end_time=utc_now(),
                             attributes=attrs)
            sink.start_span(span)
            sink.end_span(span)
        # Avoid retaining a second complete serialized record. Even individual
        # oversized provider strings are split without modifying their content.
        buffer = ''
        for fragment in _json_fragments(payload, self.chunk_chars):
            for offset in range(0, len(fragment), self.chunk_chars):
                buffer += fragment[offset:offset + self.chunk_chars]
                while len(buffer) >= self.chunk_chars:
                    text, buffer = buffer[:self.chunk_chars], buffer[self.chunk_chars:]
                    digest.update(text.encode())
                    emit('sage.diagnostic.chunk', {'sage.diagnostic.sequence':count, 'sage.diagnostic.text':text})
                    count += 1
        if buffer:
            digest.update(buffer.encode())
            emit('sage.diagnostic.chunk', {'sage.diagnostic.sequence':count, 'sage.diagnostic.text':buffer})
            count += 1
        emit('sage.diagnostic.record', {'sage.diagnostic.chunks':count, 'sage.diagnostic.sha256':digest.hexdigest()})

    def flush(self, timeout=5):
        import time
        deadline = time.monotonic() + timeout
        with self._condition:
            while self._bytes:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._condition.wait(remaining)
            return True

    def close(self, timeout=5):
        import time
        deadline = time.monotonic() + timeout
        with self._condition:
            self._closed = True
            self._condition.notify_all()
        drained = self.flush(timeout)
        with self._condition:
            # An unavailable exporter must not retain queued payloads after the
            # host stops. Its single in-flight item remains bounded until the
            # exporter's own timeout expires.
            if not drained:
                self.dropped_records += len(self._queue)
                self._bytes -= sum(item[0] for item in self._queue)
                self._queue.clear()
                self._condition.notify_all()
            worker = self._worker
        if worker is not None:
            worker.join(max(0, deadline - time.monotonic()))
        return drained


def reconstruct(spans):
    """Return valid records and explicit gaps, even if the manifest was lost."""
    records, gaps = {}, []
    for span in spans:
        attrs = span.get('attributes', {})
        if attrs.get('sage.diagnostic.format') != 'chunks/v1':
            continue
        record = records.setdefault((attrs['run_id'], attrs['sage.diagnostic.record_id']),
                                    {'chunks':{}, 'manifest':None, 'attrs':attrs, 'at':span['start_time']})
        if span['name'] == 'sage.diagnostic.chunk':
            record['chunks'][int(attrs['sage.diagnostic.sequence'])] = attrs['sage.diagnostic.text']
        elif span['name'] == 'sage.diagnostic.record':
            record['manifest'] = attrs
    restored = []
    for record in records.values():
        attrs, marker, chunks = record['attrs'], record['manifest'], record['chunks']
        count = int(marker['sage.diagnostic.chunks']) if marker else -1
        text = ''.join(chunks[key] for key in sorted(chunks))
        complete = (len(chunks) == count and set(chunks) == set(range(count)) and
                    hashlib.sha256(text.encode()).hexdigest() == marker['sage.diagnostic.sha256'])
        if not complete:
            gaps.append({'run_id':attrs['run_id'], 'request_id':attrs.get('request_id'),
                         'record_id':attrs['sage.diagnostic.record_id'], 'kind':attrs['sage.diagnostic.kind'],
                         'expected_chunks':count if marker else None, 'received_chunks':len(chunks)})
            continue
        event = {'sage.diagnostic.kind':attrs['sage.diagnostic.kind'], 'sage.diagnostic.data':text,
                 'run_id':attrs['run_id'], 'session_id':attrs['session_id']}
        restored.append((record['at'], event))
    return restored, gaps
