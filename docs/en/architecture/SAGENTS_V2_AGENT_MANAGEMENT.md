---
layout: default
title: Agent Package Management
parent: Architecture
nav_order: 3
lang: en
ref: v2-detail-SAGENTS_V2_AGENT_MANAGEMENT
---

{% include lang_switcher.html %}

# v2 Agent Package Management

## Definitions and public interfaces

`AgentManagementService` creates, validates, saves, and runs packages using native `SageManifest`, not a simplified configuration format. Packages can select Simple / Fibre / Team modes, members, Flow, tools, Skills, memory, models, budgets, and instruction files; actual capabilities still require host-bound providers. A created Agent can create other Agents only when granted management tools and host authorization. This does not change the leaf-worker semantics of Fibre's lightweight `sys_spawn_agent`.

Import from `sagents.v2`:

- `AgentPackageBundle`: `manifest: SageManifest` and `files: dict[str, str]`.
- `AgentManagementService`: validation, save, read, fork, activation, and Native Run execution.
- `AgentPackageStore`: default SQLite version inventory and operation index; Server uses its own MySQL repository.

Configuration and file contents determine an immutable ref. Runs bind an exact ref; changing the active pointer does not change existing tasks. Save and activation do not certify task competence or implement automatic scoring or learning promotion.

## Management tools

Inject with `SAgentBuilder.with_agent_management(service)` and explicitly select tools in the Agent's `tools`. Injection alone does not authorize every Agent.

| Tool | Purpose |
| --- | --- |
| `agent_package_schema` | Full bundle Schema and host plugin inventory |
| `agent_package_list` | Paginated version inventory and active markers |
| `agent_package_get` | Read complete definitions and files |
| `agent_package_validate` | Schema, references, composition, and optional readiness checks |
| `agent_package_save` | Save an immutable version |
| `agent_package_fork` | Copy to a new package ID / version |
| `agent_package_activate` | Switch or roll back the active version using expected_ref |
| `agent_package_run` | Start work or continue a Session for that version |
| `agent_package_status` | Status, results, and pending interactions |
| `agent_package_reply` | Answer user_input / elicitation with interaction_id, never host approval or credential interactions |
| `agent_package_cancel` | Cancel through Native Runtime |

## Host integration and lifecycle

```python
service = AgentManagementService(
    root="runtime/managed-agents",
    builder_factory=build_managed_agent,
    authorize=authorize_package,
    inventory=plugin_inventory,
    max_applications=32,
    max_concurrent_builds=4,
    auto_release_idle_seconds=300,
)
```

This is an integration fragment; the host implements the callbacks. Async `authorize(action, bundle, context)` returns None on success and raises on denial. It checks models, credential references, plugins, tools, budgets, paths, and external connections before loading plugins and again for execution, control, and activation. Authorization need not ask a human each time; ToolPolicy still selects interaction behavior.

`builder_factory(bundle, session_root, context)` returns a new Builder synchronously or asynchronously. Configure the persistent session_root partitioned by user/package/Agent, inject models, memory, tools, and real Run sandbox bindings, and register admitted plugins. Skill integration uses `with_skill_provider(catalog, source, workspace)` and requires Agent Skill selection, load_skill authorization, and caller scope `skill.load`. Explicitly inject management and its tools when recursive Agent creation is allowed.

The service calls `builder.build(..., agent_id=...)`. Do not share mutable Builders or clients with unclear ownership. Validation composes in a separate temporary directory. Failed cleanup retains the Application and directory, enters draining, and rejects new work so close can retry cleanup.

The host owns and closes the service; a child Application must not close it. `max_applications` limits resident instances plus build reservations. `max_concurrent_builds` defaults to 4; validation holds its slot until resources close. At capacity, the default attempts to reclaim instances idle for 300 seconds that have durable recovery and no nonterminal work. Set `auto_release_idle_seconds=None` to disable this. There is no periodic background eviction. See [resource management](SAGENTS_V2_RESOURCE_MANAGEMENT.md).

## Plugins and Flow

Standard [ExtensionRegistration](https://github.com/ZHangZHengEric/Sage/blob/main/sagents/v2/runtime/extensions/contracts.py) declares ID, version, API, configuration Schema, dependencies, scope, factory, and lifecycle hooks. Discover explicitly through `sage.extensions` or register with `builder.register(registration)`. Missing declarations, version conflicts, invalid configuration, and unbound nodes fail explicitly.

Select standard nodes through `runtime.capabilities["flow.node"]` or bind host `RunnableNode` objects with `with_flow_tool_nodes`. The interface is `RunnableNode.run(FlowNodeContext) -> FlowNodeResult`. Builder supports process / tenant / agent-scoped nodes; Run scope requires a dedicated driver. Agent `entrypoint.type: flow` connects to FlowRuntime.

Flow agent nodes use Native child Runs and pass earlier outputs as later task data; use subflow for nested flows. Builder rejects recursive Flow agents and unimplemented custom loops. Interaction nodes can select user_input and default to approval, with distinct authorization boundaries. Completed output is stored in `flow.completed.output` and returned as `flow_results` by management.

Source plugins live in `files["extensions/<plugin_id>.py"]`, must be declared in manifest.plugins, and must export a standard registration object named registration (API version 2). Source participates in the version hash and cannot impersonate built-ins or replace host registrations. The host must set `allow_source_plugins=True` and approve `authorize("load_source_plugin", bundle, context)`. The built_in_only policy rejects loading.

Source executes in the host Python process, including validation and module initialization. Syntax and interface checks do not isolate code. Automatic dependency installation, isolated builds, and untrusted-code sandboxes are not provided. Applications own modules, removing them after plugin shutdown; failed loads clean up.

## Versions, idempotency, and recovery

- Inventory is partitioned by tenant ID and principal ID; user-supplied file paths do not locate packages.
- An ID / version accepts only identical content. Normal repeated saves return `reused=True`, recheck authorization, and reuse validation. Strict `require_readiness=True` mode revalidates host resources.
- Activation requires matching expected_ref, empty on first activation. A run's operation key is unique within the caller scope; retries must preserve ref, agent, input, and Session.
- Persist intent before Native idempotent admission; retry an interrupted call with the same operation. Continuation requires the same caller, ref, Agent, and Session; there is no implicit cross-version migration.
- Suspension returns interactions rather than claiming completion. Replies require interaction_id. Identical ID, decision, and payload can be retried idempotently, without applying old answers to new questions. Unaccepted replies rejected by revision conflict may reread the revision and retry.
- Save and validation snapshot inputs and preserve whitespace in files and prompts. Bundles allow 256 text files and 4 MiB total serialized size, rejecting absolute paths, traversal, backslashes, and replacement of sage.yaml.
- Archived terminal results can be read without rebuilding an Application, while checking current read_run authorization. Built-in file storage supports read-only cold recovery; nonterminal work and stores without offline reading still require recovery composition.

Execution management is single-process. SQLite or MySQL transactions do not establish distributed worker scheduling. Cross-tenant sharing, cross-version Session migration, and business-quality acceptance remain host design decisions.

## Examples and validation

Run in the project's Python 3.12+ environment:

```bash
python -m examples.sagents_v2_agent_management
python -m examples.sagents_v2_source_plugin
python -m pytest tests/sagents/v2/test_agent_management_matrix.py
```

Examples use scripted models through tool calls, save, Builder composition, and Native Run. They do not call model APIs or establish model quality. Tests cover version conflicts, isolation, idempotency, continuation, Flow, Skills, interactions, and cleanup failures. Native-platform and real-model tests still need separate execution.

Server exposes the full package platform through `/studio` and `/api/agent-packages`. Desktop's ordinary Agent editing and multi-member Studio are not full package-version management.
