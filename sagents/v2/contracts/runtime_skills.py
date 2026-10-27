"""Serializable host Skill authorization and Run attachment contracts."""
from __future__ import annotations

import base64
from typing import Literal, Self

from pydantic import Field, model_validator

from sagents.v2.contracts.common import Identifier, StrictModel
from sagents.v2.contracts.skill_payload import SkillBundle, SkillDescriptor, files_digest


class RuntimeSkillAttachment(StrictModel):
    """Self-contained immutable source snapshot; never an execution permission.

    Lifetime is one Run tree, including suspension and process recovery. A new
    conversational Run must explicitly attach its Skills again.
    """

    descriptor: SkillDescriptor
    content_hash: str
    files_base64: dict[str, str]
    target_agent_id: Identifier | None = None
    lifetime: Literal["run_tree"] = "run_tree"
    preload: bool = False

    @classmethod
    def from_bundle(
        cls, bundle: SkillBundle, *, target_agent_id: str | None = None,
        preload: bool = False,
    ) -> Self:
        return cls(
            descriptor=bundle.descriptor, content_hash=bundle.content_hash,
            files_base64={path: base64.b64encode(data).decode("ascii")
                          for path, data in bundle.files.items()},
            target_agent_id=target_agent_id, preload=preload,
        )

    def bundle(self) -> SkillBundle:
        files = {path: base64.b64decode(data, validate=True)
                 for path, data in self.files_base64.items()}
        if files_digest(files) != self.content_hash:
            raise ValueError("runtime Skill content hash mismatch")
        return SkillBundle(descriptor=self.descriptor, content_hash=self.content_hash, files=files)

    @model_validator(mode="after")
    def validate_bundle(self):
        if self.descriptor.name in {".", ".."}:
            raise ValueError("unsafe runtime Skill name")
        self.bundle()
        return self


class RuntimeSkillAuthorization(StrictModel):
    """Host ceiling admitting this exact source, name and content identity.

    Empty target_agent_ids allows any attachment root in this App. Otherwise
    only the listed canonical Agent IDs can be attachment roots.
    """

    descriptor: SkillDescriptor
    content_hash: str
    target_agent_ids: tuple[Identifier, ...] = ()
    max_bytes: int = Field(default=1024 * 1024, gt=0)

    @classmethod
    def from_bundle(
        cls, bundle: SkillBundle, *, target_agent_ids: tuple[str, ...] = (),
        max_bytes: int = 1024 * 1024,
    ) -> Self:
        return cls(
            descriptor=bundle.descriptor, content_hash=bundle.content_hash,
            target_agent_ids=target_agent_ids, max_bytes=max_bytes,
        )


class RuntimeSkillAuthority:
    """One App's current host ceiling, shared by every kernel and revision.

    Admission, delegation and each execution or resume read ``grants`` at
    check time, so a replacement applies to them without rebuilding the App.
    """

    def __init__(self, grants=()) -> None:
        self.grants: tuple[RuntimeSkillAuthorization, ...] = tuple(grants)
