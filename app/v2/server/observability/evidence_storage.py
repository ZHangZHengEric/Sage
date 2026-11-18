"""Immutable compressed model evidence on the Server's shared data volume."""

from hashlib import sha256
import gzip
import json
import os
from pathlib import Path
import re
import tempfile


PARTS = frozenset({"request", "response", "stream", "error", "request_metadata", "metadata"})
FORMAT = "sage.diagnostic-parts/v1"


class EvidenceStorage:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)

    def directory(self, key):
        identity = sha256(json.dumps(list(key), ensure_ascii=False).encode()).hexdigest()
        return self.root / identity[:2] / identity

    def path(self, key, digest):
        if not isinstance(digest, str) or not re.fullmatch(r"[a-f0-9]{64}", digest):
            raise ValueError("Invalid diagnostic evidence reference")
        return self.directory(key) / (digest + ".json.gz")

    def put(self, key, value):
        raw = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()
        if len(raw) > 32 * 1024 * 1024:
            raise ValueError("Diagnostic evidence part exceeds the size limit")
        digest = sha256(raw).hexdigest()
        path = self.path(key, digest)
        if path.exists():
            # A collector leaves recently used files alone until the SQL pointer
            # is published. Verify existing content before reusing a reference.
            if self.get(key, digest) != value:
                raise ValueError("Diagnostic evidence hash collision")
            os.utime(path, None)
            return digest
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".pending-")
        try:
            with os.fdopen(fd, "wb") as output:
                output.write(gzip.compress(raw, compresslevel=3, mtime=0))
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, path)
            directory_fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        return digest

    def get(self, key, digest):
        with gzip.open(self.path(key, digest), "rb") as source:
            raw = source.read(32 * 1024 * 1024 + 1)
        if len(raw) > 32 * 1024 * 1024 or sha256(raw).hexdigest() != digest:
            raise ValueError("Invalid diagnostic evidence content")
        return json.loads(raw)

    def pack(self, key, record):
        result = dict(record)
        references = dict(result.pop("_parts", {}))
        if result.get("evidence_expired"):
            return result
        for name in PARTS:
            if name in result:
                references[name] = self.put(key, result.pop(name))
        result["_storage"] = FORMAT
        result["_parts"] = references
        return result

    def unpack(self, key, record):
        result = dict(record)
        references = result.pop("_parts", {}) if result.pop("_storage", None) == FORMAT else {}
        for name, digest in references.items():
            if name not in PARTS:
                raise ValueError("Invalid diagnostic evidence part")
            try:
                result[name] = self.get(key, digest)
            except (OSError, ValueError, EOFError):
                result["evidence_unavailable"] = True
                result.setdefault("evidence_unavailable_parts", []).append(name)
        return result
