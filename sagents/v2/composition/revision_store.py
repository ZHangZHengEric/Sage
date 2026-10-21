"""Local immutable recovery snapshots, colocated with the App's durable state."""

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile
from pydantic import PrivateAttr

from sagents.v2.package.manifest.resolver import ResolvedSageManifest


@dataclass
class RecoveryIdentity:
    admitted_hash: str
    assembly_hash: str | None = None

    def bind(self, assembly_hash: str) -> str:
        if self.assembly_hash is not None and self.assembly_hash != assembly_hash:
            raise ValueError(
                "saved Agent revision no longer matches the runtime composition"
            )
        self.assembly_hash = assembly_hash
        return self.admitted_hash


class MigratedAgentRevision(ResolvedSageManifest):
    """Store-issued recovery provenance, never accepted from package JSON."""

    _recovery_identity: RecoveryIdentity = PrivateAttr()


class AgentRevisionStore:
    def __init__(self, root):
        self.root = Path(root) / "agent-revisions"

    def _path(self, spec_hash):
        return self.root / (hashlib.sha256(spec_hash.encode()).hexdigest() + ".json")

    def save(self, resolved, spec_hash):
        self.root.mkdir(parents=True, exist_ok=True)
        payload = {"spec_hash": spec_hash, "package": resolved.model_dump(mode="json")}
        if isinstance(resolved, MigratedAgentRevision):
            identity = resolved._recovery_identity
            if identity.admitted_hash != spec_hash or identity.assembly_hash is None:
                raise ValueError("migrated Agent revision identity is not bound")
            payload["recovery"] = {
                "version": 1,
                "assembly_hash": identity.assembly_hash,
            }
        content = json.dumps(payload)
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
        return self._decode(raw)

    def _decode(self, raw):
        if recovery := raw.get("recovery"):
            if recovery.get("version") != 1 or not isinstance(
                recovery.get("assembly_hash"), str
            ):
                raise ValueError("unsupported Agent revision recovery identity")
            resolved = MigratedAgentRevision.model_validate(raw["package"])
            resolved._recovery_identity = RecoveryIdentity(
                raw["spec_hash"], recovery["assembly_hash"]
            )
            return resolved
        return ResolvedSageManifest.model_validate(raw["package"])
