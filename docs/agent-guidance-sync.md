# Agent guidance sync

Sage exposes `PUT /api/agents/{agent_id}/guidance` for a machine credential bound to that Agent with the `agent:guidance:write` scope. Create the key through the existing `/api/keys` owner endpoint. The request uses `Authorization: Bearer <api_key>` and `multipart/form-data`:

- `prompt`: the Agent prompt text.
- `files`: one or more Skill ZIP packages, each containing a `SKILL.md` and any references, scripts, or other Skill files. A single upload accepts at most 32 ZIP packages.

This follows the ZIP package model used by Sage V1's single and batch Skill upload APIs. Each ZIP is validated and reported independently. The response includes `prompt_changed`, `success_count`, `failed_count`, and an item in `results` for each uploaded ZIP. One invalid Skill does not prevent valid packages in the same request from being published.

Sage maps `prompt` to the existing Agent instructions field. For each valid ZIP, it updates the Skill catalog version only when the complete package changes, binds that Skill to the Agent, and replaces its complete directory in existing Agent workspaces. Old workspace directories are retained in the operational runtime backup directory. It preserves the Agent's model, tools and execution policy, leaves other Skills intact, and rejects a Skill bound to another Agent. It does not install or manage application-specific project runtimes.

MCP records also accept `timeout_seconds` greater than 0 and at most 900 seconds (default 30). A caller sets this on its own MCP record; Sage does not infer timeout from the server name or URL.
