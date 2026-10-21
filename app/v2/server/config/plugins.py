"""Admin-owned plugin selections, persisted independently of the active host.

Writes never mutate running applications. Startup takes one immutable-in-practice
snapshot for both the host and all subsequently materialized catalog Runs.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path

from jsonschema import ValidationError, validate

from app.v2.server.catalog.plugins import AGENT_DEFAULTS, configuration_schema
from sagents.v2.package.manifest.runtime import CapabilitySelection
from sagents.v2.contracts.errors import SageV2Error
from sagents.v2.runtime.extensions.official import builtin_extension_registry

# Other process services are injected by ServerHost, or bound to host storage,
# execution grants and tenant catalogs. A saved choice there would be ignored.
SERVER_CONFIGURABLE = frozenset(AGENT_DEFAULTS) | {
    "memory.provider",
    "session-memory.provider",
    "context.summary-store",
    "observability.provider",
    "workspace.initializer",
    "package.registry",
}
SERVER_DEFAULTS = {
    **AGENT_DEFAULTS,
    "memory.provider": "sage.memory.filesystem-bm25",
    "session-memory.provider": "sage.session-memory.sqlite-bm25",
    "context.summary-store": "sage.context.summary-store.session-derived",
    "observability.provider": "sage.observability.local",
    "workspace.initializer": "sage.workspace.initializer.claw",
    "package.registry": "sage.package-registry.ephemeral",
}


def validate_selections(selections: dict, *, registry=None) -> dict:
    registry = registry if registry is not None else builtin_extension_registry()
    result = {}
    for capability, raw in selections.items():
        if capability not in SERVER_CONFIGURABLE:
            raise ValueError(f"{capability} 由 Server 部署管理，不能在页面覆盖")
        selection = CapabilitySelection.model_validate(raw)
        try:
            descriptor = registry.get(selection.plugin).descriptor
        except SageV2Error as exc:
            raise ValueError(f"插件 {selection.plugin} 未注册") from exc
        if not descriptor.availability.available:
            raise ValueError(f"插件 {selection.plugin} 当前不可用")
        if not any(offer.capability == capability for offer in descriptor.provides):
            raise ValueError(f"插件 {selection.plugin} 不支持 {capability}")
        if selection.name != "default":
            raise ValueError("Server 插件只支持默认绑定")
        if selection.scope is not None:
            raise ValueError("Server 插件作用域由运行时管理")
        try:
            validate(selection.config, configuration_schema(descriptor))
        except ValidationError as exc:
            # Do not echo configuration values (which may contain credentials).
            field = ".".join(str(part) for part in exc.absolute_path) or "参数"
            raise ValueError(f"{capability} 的 {field} 不符合插件配置要求") from exc
        result[capability] = selection.model_dump(mode="json", exclude_none=True)
    return result


def revision(selections: dict) -> str:
    return hashlib.sha256(json.dumps(selections, sort_keys=True).encode()).hexdigest()


class ServerPluginConfig:
    def __init__(self, data_root: Path, *, registry=None):
        self.registry = registry
        self.path = data_root / "config" / "plugins.json"

    def read(self) -> dict:
        if not self.path.exists():
            return {}
        value = json.loads(self.path.read_text())
        if not isinstance(value, dict):
            raise ValueError("Server 插件配置格式错误")
        value.pop("context.token-estimator", None)
        return validate_selections(value, registry=self.registry)

    def save(self, changes: dict, expected_revision: str) -> dict:
        # Serialize host-local maintenance as well as HTTP writes. Lock around
        # the revision check AND atomic rename, even across local processes.
        import fcntl

        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.with_suffix(".lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            current = self.read()
            if revision(current) != expected_revision:
                raise FileExistsError("配置已被其他管理员修改，请重新加载后再保存")
            candidate = dict(current)
            for capability, selection in changes.items():
                if capability not in SERVER_CONFIGURABLE:
                    raise ValueError(f"{capability} 由 Server 部署管理")
                if selection is None:
                    candidate.pop(capability, None)
                else:
                    candidate[capability] = selection
            candidate = validate_selections(candidate, registry=self.registry)
            descriptor, name = tempfile.mkstemp(
                dir=self.path.parent, prefix=".plugins-"
            )
            try:
                with os.fdopen(descriptor, "w") as output:
                    json.dump(candidate, output, ensure_ascii=False, indent=2)
                    output.flush()
                    os.fsync(output.fileno())
                os.replace(name, self.path)
            finally:
                Path(name).unlink(missing_ok=True)
            return candidate
