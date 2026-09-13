"""Versioned agent packages authored through the same schema as host packages."""

from __future__ import annotations

import hashlib
import json
from pathlib import PurePosixPath

from pydantic import Field, model_validator

from sagents.v2.contracts.common import StrictModel, VerbatimText
from sagents.v2.package.manifest import SageManifest


class AgentPackageBundle(StrictModel):
    manifest: SageManifest
    files: dict[VerbatimText, VerbatimText] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_files(self):
        for name in self.files:
            path = PurePosixPath(name)
            if (
                not name
                or path.is_absolute()
                or "\\" in name
                or any(part in {"", ".", ".."} for part in name.split("/"))
                or name == "sage.yaml"
            ):
                raise ValueError(f"invalid package resource: {name!r}")
        if (
            len(self.files) > 256
            or len(self.model_dump_json().encode()) > 4 * 1024 * 1024
        ):
            raise ValueError("package exceeds 256 files or 4 MiB")
        return self

    def resolved_manifest(self) -> SageManifest:
        """Resolve instructions from the bundle, never from the host filesystem."""
        data = self.manifest.model_dump(mode="json")
        for agent in data["agents"].values():
            path = agent["instructions"].get("path")
            if path is not None:
                if path not in self.files:
                    raise ValueError(f"missing bundled instruction resource: {path!r}")
                agent["instructions"] = {"inline": self.files[path]}
        return SageManifest.model_validate(data)

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(
            json.dumps(
                self.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
            ).encode()
        ).hexdigest()
