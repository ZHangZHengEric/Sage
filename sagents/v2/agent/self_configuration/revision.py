"""Apply a self-configuration change to the Run and Agent revisions."""


def apply_revision(current, future, expected_revision, skills, servers, system_prompt):
    if current["revision"] != expected_revision:
        raise ValueError(
            "self configuration revision changed; read and submit again"
        )
    current["skills"].update(skills)
    current["mcp_servers"].update(servers)
    current["revision"] += 1
    # Concurrent Runs may add disjoint capabilities, never erase them.
    for key, additions in (("skills", skills), ("mcp_servers", servers)):
        for name, value in additions.items():
            if name in future[key] and future[key][name] != value:
                raise ValueError(
                    f"capability {name!r} already has a different saved definition"
                )
        future[key].update(additions)
    if system_prompt is not None:
        # A stale Run must not silently replace a newer Run's prompt.
        if (
            future.get("system_prompt", "")
            != current.get("system_prompt", "")
            and future.get("system_prompt", "") != system_prompt
        ):
            raise ValueError(
                "Agent instructions changed in another Run; start a fresh Run before replacing them"
            )
        current["system_prompt"] = system_prompt
        future["system_prompt"] = system_prompt
    future["revision"] += 1
    result = {
        "revision": current["revision"],
        "added_skills": sorted(skills),
        "added_mcp_servers": sorted(servers),
        "effective": "next_model_step",
        "persistent": True,
        "system_prompt_updated": system_prompt is not None,
    }
    return result
