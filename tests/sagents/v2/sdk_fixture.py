"""Test data and setup using registration and the public build/load/run path."""
from pathlib import Path
from types import SimpleNamespace

from sagents.v2 import ApplicationConfiguration, SAgentBuilder
from sagents.v2.composition.defaults import default_runtime
from sagents.v2.package.manifest.runtime import CapabilitySelection, RuntimeConfig, merge_capability_selections
from sagents.v2.runtime.session.plugins import session_storage_providers
from sagents.v2.runtime.extensions import CapabilityOffer, ExtensionDescriptor, ExtensionRegistration, ExtensionScope


def fixture_configuration(root, *, model=None, models=None, runtime=None, registrations=(), resources=(), providers=None,
                          tools=None, skills=None, model_factory=None):
    effective = default_runtime(root) if runtime is None else RuntimeConfig.model_validate(runtime)
    if runtime is None:
        effective = effective.model_copy(update={"capabilities": {**effective.capabilities,
            "agent.continuation-policy": CapabilitySelection(plugin="sage.agent.continuation.deterministic"),
            "memory.recall-query": CapabilitySelection(plugin="sage.memory.recall-query.direct")}})
    choices = merge_capability_selections({"session.store": default_runtime(root).capabilities["session.store"]}, effective.capabilities)
    values = dict(providers or {})
    if model is not None:
        values["model.provider"] = model
    if tools is not None:
        values["tool.provider"] = SimpleNamespace(catalog=tools[0], executor=tools[1])
    if skills is not None:
        values["skill.provider"] = SimpleNamespace(list_skills=skills[0].list_skills, get_skill=skills[0].get_skill, fetch=skills[1].fetch, fetch_latest=getattr(skills[1], "fetch_latest", skills[1].fetch))
        if len(skills) > 2 and skills[2] is not None:
            values["skill.workspace"] = skills[2]
    registered = list(registrations)
    for capability, value in values.items():
        plugin_id = "test.fixture." + capability
        scope = ExtensionScope.AGENT if capability == "model.provider" else ExtensionScope.PROCESS
        names = (capability,)
        storage_ports = None
        if capability == "session.store":
            storage_ports = session_storage_providers(value)
            if "derived-state.store" in values or not all(callable(getattr(value, key, None)) for key in (
                "get_derived_state", "put_derived_state", "delete_derived_state",
            )):
                storage_ports.pop("derived-state.store")
            names = tuple(storage_ports)
        if storage_ports is not None:
            start = lambda instance, context, deps, ports=storage_ports: ports
        elif capability == "derived-state.store":
            start = lambda instance, context, deps, capability=capability: {capability: instance}
        else:
            start = None
        registered.append(ExtensionRegistration(
            descriptor=ExtensionDescriptor(plugin_id=plugin_id, name=capability, version="1",
                provides=tuple(CapabilityOffer(capability=name, api_version="2") for name in names),
                supported_scopes=frozenset({scope}), default_scope=scope,
                config_schema={"type": "object", "additionalProperties": False}),
            factory=lambda context, deps, value=value: value, ownership="borrowed",
            start=start,
        ))
        choices[capability] = CapabilitySelection(plugin=plugin_id, scope=scope)
    if model_factory is not None:
        plugin = "test.fixture.model-factory"
        registered.append(ExtensionRegistration(
            descriptor=ExtensionDescriptor(plugin_id=plugin, name=plugin, version="1",
                provides=(CapabilityOffer(capability="model.provider", api_version="2"),),
                supported_scopes=frozenset({ExtensionScope.AGENT}),
                config_schema={"type": "object", "additionalProperties": False}),
            factory=model_factory, ownership="borrowed",
        ))
        choices["model.provider"] = CapabilitySelection(plugin=plugin, scope="agent")
    for index, resource in reversed(tuple(enumerate(resources))):
        capability = f"test.resource.{index}"
        registered.append(ExtensionRegistration(
            descriptor=ExtensionDescriptor(plugin_id=capability, name=capability, version="1",
                provides=(CapabilityOffer(capability=capability, api_version="2"),),
                supported_scopes=frozenset({ExtensionScope.PROCESS}),
                config_schema={"type": "object", "additionalProperties": False}),
            factory=lambda context, deps, resource=resource: resource,
            start=lambda instance, context, deps, capability=capability: {capability: instance},
        ))
        choices[capability] = CapabilitySelection(plugin=capability)
    return ApplicationConfiguration(tuple(registered), effective.model_copy(update={
        "capabilities": choices, "state_root": str(Path(root).resolve()),
    }), models)


def app_configuration(root, **kwargs):
    config = fixture_configuration(root, **kwargs)
    builder = SAgentBuilder()
    for registration in config.registrations:
        builder.register(registration)
    return builder, config.runtime


async def build_registered_app(root=None, *, configuration=None, tenant_id=None, models_config_text=None, **kwargs):
    if configuration is not None:
        from dataclasses import replace
        overrides = {key: kwargs.pop(key) for key in ("runtime", "models") if key in kwargs}
        if "runtime" in overrides:
            selected = RuntimeConfig.model_validate(overrides.pop("runtime"))
            overrides["runtime"] = selected.model_copy(update={"capabilities": {
                **configuration.runtime.capabilities, **selected.capabilities}})
        config = replace(configuration, **overrides)
        if kwargs:
            raise TypeError(f"unexpected configuration overrides: {sorted(kwargs)}")
    else:
        config = fixture_configuration(root, **kwargs)
    builder = SAgentBuilder()
    for registration in config.registrations:
        builder.register(registration)
    return await builder.build(runtime=config.runtime, models=config.models,
        models_config_text=models_config_text, tenant_id=tenant_id)


async def build_registered_package(root=None, package=None, *, configuration=None, runtime=None, **kwargs):
    """Run the actual SDK standard sequence; no facade or custom execution object."""
    from sagents.v2.composition.inputs import package_input
    selected = package_input(package)
    config = configuration or fixture_configuration(root, runtime=runtime if runtime is not None else selected.runtime, **kwargs)
    app = await build_registered_app(configuration=config, **({"runtime": runtime} if configuration is not None and runtime is not None else {}))
    try:
        await app.load_agent(selected)
    except BaseException:
        await app.close()
        raise
    return app
