"""Normalize model request diagnostics consistently across local adapters."""

from collections.abc import Mapping
from typing import Any
from sagents.v2.model.contracts import ModelRequest


def model_request_payload(
    request: ModelRequest, wire_request: Mapping[str, Any] | None
) -> dict[str, Any]:
    if wire_request is not None:
        return dict(wire_request)
    return request.model_dump(
        mode="json",
        exclude={"request_id", "run_id", "metadata"},
        exclude_none=True,
    )
