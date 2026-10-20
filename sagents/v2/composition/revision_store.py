"""Local immutable recovery snapshots, colocated with the App's durable state."""

import hashlib
import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile

from sagents.v2.package.manifest.resolver import ResolvedSageManifest


class AgentRevisionStore:
    def __init__(self, root):
        self.root = Path(root) / "agent-revisions"

    def _path(self, spec_hash):
        return self.root / (hashlib.sha256(spec_hash.encode()).hexdigest() + ".json")

    def save(self, resolved, spec_hash):
        self.root.mkdir(parents=True, exist_ok=True)
        content = json.dumps(
            {"spec_hash": spec_hash, "package": resolved.model_dump(mode="json")}
        )
        temporary = None
        try:
            with NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=self.root, delete=False
            ) as stream:
                temporary = Path(stream.name)
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self._path(spec_hash))
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def contains(self, spec_hash):
        return self._path(spec_hash).is_file()

    def read(self, spec_hash):
        path = self._path(spec_hash)
        if not path.is_file():
            return None
        raw = json.loads(path.read_text(encoding="utf-8"))
        if raw["spec_hash"] != spec_hash:
            raise ValueError("Agent revision snapshot identity mismatch")
        return ResolvedSageManifest.model_validate(raw["package"])
