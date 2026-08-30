"""SAgents V2 module for contracts/common.py."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints


class StrictModel(BaseModel):
    """Base model for every public v2 wire contract."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        populate_by_name=True,
        str_strip_whitespace=True,
        use_enum_values=False,
    )


Identifier = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=192,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:@/-]*$",
    ),
]

# Tool names are sent to model providers and used as unambiguous dispatch keys.
# Keep the established Sage convention: letters, digits and underscores only.
# Plugin IDs and other protocol identifiers may still contain dots.
ToolName = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=192,
        pattern=r"^[A-Za-z][A-Za-z0-9_]*$",
    ),
]

# Skill registry names are user-facing identities, not protocol object
# identifiers. Keep spaces for compatibility while excluding path separators.
SkillName = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=192,
        pattern=r"^[^\\/\x00]+$",
    ),
]

# Text streamed from a model is a lossless transport payload. Leading spaces
# and newlines may be Markdown syntax split into their own delta, so it must
# opt out of StrictModel's identifier-oriented whitespace normalization.
VerbatimText = Annotated[str, StringConstraints(strip_whitespace=False)]

NonNegativeInt = Annotated[int, Field(ge=0)]
PositiveInt = Annotated[int, Field(gt=0)]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def new_sortable_id(prefix: str, *, created_at: datetime | None = None) -> str:
    """Return a unique ID whose lexical order starts with its creation time."""

    timestamp = created_at or utc_now()
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError("created_at must be timezone-aware")
    utc_timestamp = timestamp.astimezone(timezone.utc)
    sortable_timestamp = utc_timestamp.strftime("%Y%m%dT%H%M%S%fZ")
    return f"{prefix}_{sortable_timestamp}_{uuid.uuid4().hex}"
