"""Compile explicit, pinned child revisions into an internal execution graph.

Public Packages contain one Agent. Only the compiled snapshot contains the
transitive graph; recovery reads that snapshot without consulting current Agents.
"""

import hashlib
import json

from sagents.v2.package.manifest.resolver import (
    CompositionResolver,
    ResolvedSageManifest,
)


def resolve_agent_graph(package, runtime, children):
    if isinstance(package, ResolvedSageManifest):
        if children:
            raise ValueError("resolved Packages cannot bind additional subagents")
        if package.runtime != runtime:
            raise ValueError("cannot override runtime on an already resolved package")
        return package.model_copy(deep=True)
    name, definition = next(iter(package.agents.items()))
    required = set(definition.subagents) | {
        node.agent
        for flow in package.flows.values()
        for node in flow.nodes
        if node.agent is not None and node.agent != name
    }
    if set(children) != required:
        raise ValueError(
            "subagents must bind exactly the Package's declared child names"
        )
    # Validate the single Agent before linking separately validated child graphs.
    standalone = package.model_copy(
        update={
            "runtime": runtime.model_copy(deep=True),
            "agents": {name: definition.model_copy(update={"subagents": ()})},
        }
    )
    resolved = CompositionResolver().resolve(standalone)
    agents = dict(resolved.agents)
    agents[name] = agents[name].model_copy(update={"subagents": definition.subagents})
    routes, credentials = dict(resolved.model_routes), dict(resolved.credentials)
    flows, ceilings = dict(resolved.flows), dict(resolved.policy_ceilings)
    plugins = {item.id: item for item in resolved.plugins}
    for alias, child in sorted(children.items()):
        if alias in agents:
            raise ValueError(f"subagent name collides with an Agent: {alias}")
        agent_names = {
            key: alias if key == child.entrypoint_agent else f"{alias}.{key}"
            for key in child.agents
        }
        credential_names = {}
        for key, value in child.credentials.items():
            target = (
                key
                if key not in credentials or credentials[key] == value
                else f"{alias}.{key}"
            )
            if target in credentials and credentials[target] != value:
                raise ValueError(f"credential collision: {target}")
            credentials[target] = value
            credential_names[key] = target
        route_names = {}
        for key, value in child.model_routes.items():
            value = dict(value)
            if value.get("credential") is not None:
                value["credential"] = credential_names[value["credential"]]
            target = (
                key if key not in routes or routes[key] == value else f"{alias}.{key}"
            )
            if target in routes and routes[target] != value:
                raise ValueError(f"model route collision: {target}")
            routes[target] = value
            route_names[key] = target
        flow_names = {key: f"{alias}.{key}" for key in child.flows}
        for key, value in child.agents.items():
            target = agent_names[key]
            if target in agents:
                raise ValueError(f"Agent collision: {target}")
            entrypoint = value.entrypoint
            if entrypoint.flow is not None:
                entrypoint = entrypoint.model_copy(
                    update={"flow": flow_names[entrypoint.flow]}
                )
            agents[target] = value.model_copy(
                update={
                    "model_bindings": {
                        slot: route_names[route]
                        for slot, route in value.model_bindings.items()
                    },
                    "delegation_model_bindings": {
                        slot: route_names[route]
                        for slot, route in value.delegation_model_bindings.items()
                    },
                    "subagents": tuple(agent_names[key] for key in value.subagents),
                    "entrypoint": entrypoint,
                }
            )
            policy = child.policy_ceilings[key]
            ceilings[target] = policy.model_copy(
                update={
                    "allowed_model_routes": frozenset(
                        route_names[key] for key in policy.allowed_model_routes
                    )
                }
            )
        for key, value in child.flows.items():
            target = flow_names[key]
            if target in flows:
                raise ValueError(f"flow collision: {target}")
            flows[target] = value.model_copy(
                update={
                    "nodes": tuple(
                        node.model_copy(
                            update={
                                "agent": agent_names[node.agent]
                                if node.agent is not None
                                else None,
                                "flow": flow_names[node.flow]
                                if node.flow is not None
                                else None,
                            }
                        )
                        for node in value.nodes
                    )
                }
            )
        for plugin in child.plugins:
            if plugin.id in plugins and plugins[plugin.id] != plugin:
                raise ValueError(f"conflicting plugin configuration: {plugin.id}")
            plugins[plugin.id] = plugin
    if not children:
        return resolved
    graph = resolved.model_copy(
        update={
            "agents": agents,
            "model_routes": routes,
            "credentials": credentials,
            "flows": flows,
            "policy_ceilings": ceilings,
            "plugins": tuple(plugins.values()),
        }
    )
    payload = graph.model_dump(mode="json", exclude={"manifest_hash"})
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return graph.model_copy(update={"manifest_hash": f"sha256:{digest}"})
