"""Public definitions used by Agent editors, cached for a running host."""

from sagents.v2.package.manifest.runtime import CapabilitySelection
from sagents.v2.runtime.extensions.capability_contracts import module_contract_inventory

def build_plugin_catalog(host):
    from app.v2.server.catalog.plugins import (
        plugin_options,
        AGENT_DEFAULTS,
        DEFAULT_CONFIG,
    )

    from app.v2.server.runtime.sdk_plugins import server_registrations

    defaults = {
        provider.capability: provider.plugin_id
        for provider in host.application.resolved_plan.providers
        if provider.plugin_id
    }
    options = plugin_options(host.extensions)
    for option in options:
        for capability in option["capabilities"]:
            try:
                implementation = host.application.service(capability)
            except KeyError:
                continue
            plugin_id = getattr(implementation, "plugin_id", None)
            if plugin_id:
                defaults[capability] = plugin_id
    for capability, plugin in AGENT_DEFAULTS.items():
        defaults.setdefault(capability, plugin)
    from app.v2.server.config.manifest import server_v2_manifest
    default_config = dict(DEFAULT_CONFIG)
    for key, selection in server_v2_manifest(host.settings).runtime.capabilities.items():
        if not isinstance(selection, CapabilitySelection):
            continue
        defaults[key] = selection.plugin
        if key in AGENT_DEFAULTS:
            default_config[key] = selection.config
    return {
        "plugins": options,
        "contracts": module_contract_inventory(
            host.extensions, host_registrations=server_registrations(host)
        ),
        "defaults": defaults,
        "configurable": list(AGENT_DEFAULTS),
        "default_config": default_config,
    }
