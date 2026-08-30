"""Strict YAML loader for Sage manifests."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo, SageV2Error
from sagents.v2.package.manifest.root import SageManifest


class _UniqueKeyLoader(yaml.SafeLoader):
    pass


def _construct_mapping(loader: _UniqueKeyLoader, node, deep: bool = False):
    mapping: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            raise yaml.constructor.ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                f"found duplicate key {key!r}",
                key_node.start_mark,
            )
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_mapping
)


class SageManifestLoader:
    def load(self, path: str | Path, *, environment: str | None = None) -> SageManifest:
        source = Path(path)
        if source.name != "sage.yaml":
            raise _error(
                "manifest.invalid_filename", "manifest filename must be sage.yaml"
            )
        manifest = self.loads(
            source.read_text(encoding="utf-8"),
            environment=environment,
        )
        agents = {}
        package_root = source.parent.resolve()
        for agent_id, agent in manifest.agents.items():
            instructions = agent.instructions
            if instructions.path is None:
                agents[agent_id] = agent
                continue
            resource = (package_root / instructions.path).resolve()
            if package_root not in resource.parents or not resource.is_file():
                raise _error(
                    "manifest.resource_outside_package",
                    "instruction resource must be a file inside the package",
                )
            agents[agent_id] = agent.model_copy(
                update={
                    "instructions": instructions.model_copy(
                        update={
                            "inline": resource.read_text(encoding="utf-8"),
                            "path": None,
                        }
                    )
                }
            )
        return manifest.model_copy(update={"agents": agents})

    def loads(self, content: str, *, environment: str | None = None) -> SageManifest:
        try:
            raw = yaml.load(content, Loader=_UniqueKeyLoader)
        except yaml.YAMLError as exc:
            raise _error("manifest.yaml_invalid", str(exc)) from exc
        if not isinstance(raw, dict):
            raise _error("manifest.schema_invalid", "manifest root must be a mapping")
        raw = deepcopy(raw)
        if environment is not None:
            overlays = raw.get("environments") or {}
            overlay = overlays.get(environment)
            if overlay is None:
                raise _error(
                    "manifest.environment_not_found",
                    f"manifest environment {environment!r} was not found",
                )
            forbidden = sorted(set(overlay) - {"runtime", "policies", "interfaces"})
            if forbidden:
                raise _error(
                    "manifest.environment_forbidden_override",
                    f"environment cannot override: {', '.join(forbidden)}",
                )
            _deep_merge(raw, overlay)
        try:
            return SageManifest.model_validate(raw)
        except ValidationError as exc:
            raise _error("manifest.schema_invalid", str(exc)) from exc


def _deep_merge(target: dict[str, Any], overlay: dict[str, Any]) -> None:
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            _deep_merge(target[key], value)
        else:
            target[key] = deepcopy(value)


def _error(code: str, message: str) -> SageV2Error:
    return SageV2Error(
        RuntimeErrorInfo(
            code=code,
            category=ErrorCategory.VALIDATION,
            message=message,
        )
    )
