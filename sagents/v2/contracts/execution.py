"""Durable identity of the execution environment accepted for a Run."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Literal

from pydantic import model_validator

from .common import StrictModel


class ExecutionConfigurationSnapshot(StrictModel):
    schema_version: Literal["sage.execution/v1"] = "sage.execution/v1"
    configuration_id: str
    provider_id: str
    workspace_root: str
    private_workspace_root: str
    policy: dict[str, Any]
    tool_environment: dict[str, Any]
    workspace_policy: Literal["shared_parent", "private_child", "read_only_parent"] = "shared_parent"
    child_workspace_policy: Literal["shared_parent", "private_child", "read_only_parent"] = "shared_parent"

    @staticmethod
    def identity(values: dict) -> str:
        payload = {key: value for key, value in values.items() if key != "configuration_id"}
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return "sha256:" + hashlib.sha256(encoded.encode()).hexdigest()

    @model_validator(mode="after")
    def validate_identity(self):
        if self.configuration_id != self.identity(self.model_dump(mode="json")):
            raise ValueError("execution configuration identity does not match its contents")
        return self
