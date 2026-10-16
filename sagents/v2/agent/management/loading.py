"""Load independently versioned bundle dependencies through the public App API."""


async def load_bundle_agents(application, bundle):
    children = {
        name: await load_bundle_agents(application, child)
        for name, child in bundle.dependencies.items()
    }
    return await application.load_agent(bundle.resolved_manifest(), subagents=children)


def resolve_bundle(bundle, runtime, *, models):
    from sagents.v2.composition.agent_graph import resolve_agent_graph

    return resolve_agent_graph(
        bundle.resolved_manifest(),
        runtime,
        {
            name: resolve_bundle(child, runtime, models=models)
            for name, child in bundle.dependencies.items()
        },
        models=models,
    )


def bundle_agent_definitions(bundle):
    """Names used by the compiled graph, including the public root identity."""
    root = bundle.manifest.entrypoint.agent
    result = dict(bundle.manifest.agents)
    result[bundle.manifest.metadata.id] = result[root]
    for alias, child in bundle.dependencies.items():
        child_root = child.manifest.entrypoint.agent
        for name, definition in bundle_agent_definitions(child).items():
            if name == child.manifest.metadata.id:
                continue
            target = alias if name == child_root else f"{alias}.{name}"
            if target in result:
                raise ValueError(f"Agent alias collision: {target}")
            result[target] = definition
    return result
