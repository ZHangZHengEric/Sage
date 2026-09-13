"""Resource discovery checks; no model generation or tool execution."""

from __future__ import annotations


async def resource_readiness(
    definition, catalog, *, skill_provider=None, management=None, deferred_tools=False
):
    missing_tools = []
    missing_skills = []
    unverified = []
    tools = set(definition.tools)
    if management is not None:
        tools -= {
            item.name
            for item in await management.catalog.list_tools(run_id="readiness")
        }
    if definition.skills and skill_provider is not None:
        tools.discard("load_skill")
    if tools:
        if deferred_tools:
            unverified.append("tools require an actual Run binding")
        else:
            try:
                available = {
                    item.name for item in await catalog.list_tools(run_id="readiness")
                }
                missing_tools = sorted(tools - available)
            except Exception as exc:
                unverified.append(f"tool discovery failed: {type(exc).__name__}")
    if definition.skills:
        if skill_provider is None:
            missing_skills = sorted(definition.skills)
        else:
            try:
                available = {
                    item.name
                    for item in await skill_provider[0].list_skills(run_id="readiness")
                }
                missing_skills = sorted(set(definition.skills) - available)
            except Exception as exc:
                unverified.append(f"skill discovery failed: {type(exc).__name__}")
    return {
        "ready": not (missing_tools or missing_skills or unverified),
        "missing_tools": missing_tools,
        "missing_skills": missing_skills,
        "unverified": unverified,
        "scope": "resource discovery only; no credential, model generation or skill materialization test",
    }
