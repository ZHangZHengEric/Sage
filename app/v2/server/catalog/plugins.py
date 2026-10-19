"""Host-selected defaults and safe per-Agent capability configuration."""

from copy import deepcopy
from jsonschema import validate, ValidationError
from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo, SageV2Error
from sagents.v2.runtime.extensions.official import builtin_extension_registry

AGENT_DEFAULTS = {
    "context.summarizer": "sage.context.summarizer.model",
    "context.reducer": "sage.context.reducer.persistent-summary",
    "agent.continuation-policy": "sage.agent.continuation.llm-judge",
    "tool.selection-policy": "sage.tool-selection.llm",
    "tool.result-processor": "sage.tool.result-processor.file",
    "context.unit-compactor": "sage.context.unit-compactor.reference",
    "skill.loading": "sage.skill.loading.lazy",
    "memory.recall-query": "sage.memory.recall-query.llm",
}
DEFAULT_CONFIG = {
    "context.summarizer": {"model_binding": "primary"},
    "agent.continuation-policy": {"model_binding": "fast"},
}
INJECTED = {
    "model",
    "store",
    "estimator",
    "summarizer",
    "unit_compactor",
    "derived_state",
    "session_store",
}


def configuration_schema(descriptor):
    schema = deepcopy(descriptor.config_schema or {"type": "object", "properties": {}})
    for field in INJECTED:
        schema.get("properties", {}).pop(field, None)
    schema["required"] = [
        key for key in schema.get("required", []) if key not in INJECTED
    ]
    return schema


def plugin_options(registry=None):
    registry = registry if registry is not None else builtin_extension_registry()
    return [
        dict(
            id=d.plugin_id,
            name=d.name,
            capabilities=[o.capability for o in d.provides],
            schema=configuration_schema(d),
            scopes=[scope.value for scope in d.supported_scopes],
            configurable_capabilities=[
                o.capability for o in d.provides if o.capability in AGENT_DEFAULTS
            ],
            available=d.availability.available,
        )
        for registration in registry.registrations()
        for d in [registration.descriptor]
    ]


def validate_agent_plugins(selections, *, registry=None):
    if selections is None:
        return
    registry = registry if registry is not None else builtin_extension_registry()
    for capability, selection in selections.items():
        value = (
            selection.model_dump(mode="json")
            if hasattr(selection, "model_dump")
            else selection
        )
        try:
            if isinstance(selection, (tuple, list)):
                raise ValueError(f"{capability} 只允许一个默认绑定")
            if not isinstance(value, dict):
                raise ValueError("插件配置必须是对象")
            if capability not in AGENT_DEFAULTS:
                raise ValueError(
                    f"{capability} 由 Server 管理，不允许在 Agent Package 中修改"
                )
            if value.get("name", "default") != "default":
                raise ValueError("Agent 插件只支持 default 绑定")
            if value.get("scope") not in (None, "agent", "run"):
                raise ValueError("Web Agent plugins require agent or run scope")
            descriptor = registry.get(value["plugin"]).descriptor
            if not descriptor.availability.available:
                raise ValueError("plugin is unavailable")
            if not any(o.capability == capability for o in descriptor.provides):
                raise ValueError("plugin does not provide this capability")
            if INJECTED.intersection(value.get("config", {})):
                raise ValueError("host-injected dependencies cannot be configured")
            validate(value.get("config", {}), configuration_schema(descriptor))
        except (ValueError, ValidationError, KeyError) as exc:
            raise SageV2Error(
                RuntimeErrorInfo(
                    code="server.catalog.validation",
                    category=ErrorCategory.VALIDATION,
                    message=f"Invalid plugin configuration for {capability}: {exc}",
                    safe_to_resume=True,
                )
            ) from exc
