---
layout: default
title: Host Development
parent: Architecture
nav_order: 13
lang: en
ref: v2-detail-sagents-host-development
---

{% include lang_switcher.html %}

# Sage v2 SDK integration

The application owns execution assembly. Hosts register implementations, select
capabilities in serializable runtime configuration, and use the same public Run
API for built-in and custom plugins.

```python
from sagents.v2 import SAgentBuilder

builder = SAgentBuilder()
for registration in host_registrations:
    builder.register(registration)
app = await builder.build(runtime=runtime_config, models=model_config)
try:
    agent = await app.load_agent(package, subagents=subagents)
    command = command.model_copy(update={
        "agent_id": agent.id,
        "resolved_spec_hash": agent.composition_hash,
    })
    stream = await app.entrypoint().run_stream(command, context, agent=agent)
    async for event in stream.events:
        handle_event(event)
    result = await stream.wait()
finally:
    await app.close()
```

`package`, `command`, `context`, configuration and event handling belong to the
host. `subagents` maps declared direct member names to loaded Agent handles.
Load each dependency package separately. An Agent package has one Agent; nested
Teams are explicit package relationships. A delegated ordinary leaf does not
gain a Team roster through its parent.

## Registration and selection

A registration describes a capability protocol and executable factory. The
factory implements that capability, rather than reconstructing the Run Driver,
Agent loop, official runtime or child executor.

```python
from sagents.v2.runtime.extensions import (
    CapabilityOffer, ExtensionDependency, ExtensionDescriptor,
    ExtensionRegistration, ExtensionScope,
)

builder.register(ExtensionRegistration(
    descriptor=ExtensionDescriptor(
        plugin_id="example.model", name="Example model", version="1.0.0",
        provides=(CapabilityOffer(capability="model.provider", api_version="2"),),
        dependencies=(ExtensionDependency(capability="session.store"),),
        supported_scopes=frozenset({ExtensionScope.RUN}),
        default_scope=ExtensionScope.RUN,
        config_schema={"type": "object", "additionalProperties": False},
    ),
    factory=lambda scope, deps: ExampleModel(
        run_id=scope.run_id, store=deps.require("session.store")),
    ownership="owned",
))
```

Select the registration separately:

```yaml
capabilities:
  model.provider:
    plugin: example.model
    scope: run
    config: {}
```

`ExampleModel` implements Sage's model provider protocol. Registration does not
select or instantiate it. A host-created object uses the same factory mechanism:
return the existing object and declare `ownership="borrowed"`. The creator then
closes it. Owned instances use their close method or the registration's stop hook;
borrowed registrations cannot transfer a stop hook.

Process, tenant, Agent and Run lifetimes are checked against declared scopes and
dependencies. Longer-lived consumers cannot capture shorter-lived dependencies.
Run factories receive the allocated Run identity. Agent and Run contexts expose
SDK-resolved Agent configuration; process contexts do not carry an arbitrary
Run's identity. Authorization must use the supplied request context or standard
`session.access`, not model-supplied Project or Session ownership arguments.

Duplicate registrations, unavailable protocols, unknown selections, invalid
parameters and incompatible scopes fail explicitly. Plugins are registered
explicitly; a package declaration does not authorize importing arbitrary code.
Use `builder.inventory()` and `agent.resolved_plan` to inspect registration and
selection. Plan provider records include implementation version and source
digest when provided by a source plugin.

## Configuration ownership and recovery

Runtime configuration contains serializable plugin identities, scopes and
parameters. Connections, locks and shared services remain in factories and
explicit dependencies. Model credentials use the App model catalog and Sage
credential references/providers, rather than opaque model routing wrappers.

`app.update_runtime(runtime)` and `app.update_models(models)` affect subsequent
Agent revisions. Load or update the Agent to use those selections. The App's
store, queue and security profile are process identities; changing them requires
a new App. Different Apps may independently select plugins and parameters.

Accepted Runs keep their original Agent revision and execution snapshot. Child
policies inherit the parent snapshot and may narrow its authorization. Current
App settings do not replace an accepted Run's policy. Incompatible or missing
registrations/configuration during restore fail rather than silently selecting
current defaults.

```python
agent = await app.agent_for_run(run_id, context)
task = await app.entrypoint().continue_run(run_id, context, agent=agent)
result = await task
snapshot = await app.execution_configuration(run_id, context)
diagnostics = await app.execution_diagnostics(run_id, context)
configuration = await app.run_configuration(run_id, context)
```

These queries authorize access to the Run and return detached data. A Run waiting
for an interaction must receive its normal reply before continuation. Uncertain
external effects require their reconciliation contract; recovery is not a promise
to repeat a side effect safely.

## Local media execution

Select `sage.execution.binding.local-workspace`; Sage accepts policy and creates
the sandbox after assigning the actual Run ID. A host does not call `provision()`
or emulate Sage's isolation command.

```yaml
capabilities:
  execution.binding:
    plugin: sage.execution.binding.local-workspace
    scope: process
    config:
      workspace: /absolute/workspace
      private_workspace_root: /absolute/private-workspaces
      child_workspace_policy: shared_parent
      isolation_python: /absolute/trusted/python3
      command_path: /absolute/media/bin:/usr/bin:/bin
      read_paths: [/absolute/media/runtime]
      policy:
        filesystem:
          max_file_bytes: 536870912
          allowed_operations: [read, list, write, create, delete, rename]
        process:
          enabled: true
          allow_shell: true
          allowed_executables: [bash, sh, python3, ffmpeg]
          max_wall_time_seconds: 7200
          max_output_bytes: 8388608
        resources:
          disk_mb: 32768
          require_hard_limits: false
        network:
          mode: none
          deny_private_networks: true
```

Use an actual configuration schema/inventory to check platform-specific resource
fields. File total capacity inherits an explicitly selected disk quota when no
smaller file-total ceiling is supplied. Read-only child workspaces restrict file
and process writes. Private workspaces live outside the shared workspace. Shared
sandboxes have Run-owned leases; releasing a child does not destroy a parent's
remaining lease.

The isolation helper interpreter is trusted CPython and can be packaged separately
from a frozen host. It is distinct from the Python resolved through the Agent's
Shell command path. Sage checks the interpreter, authorizes runtime directories
and launches the helper. Diagnostics report actual interpreter, sandbox identity
and enforcement capabilities; metered limits are not reported as kernel limits.

See the complete configuration in the [SDK guide](../../../sagents/v2/README.md).

## Tools, Skill, continuation and budgets

Select paired tool catalog/executor offers through registered plugins. Sage
assembles official file, Shell, Skill and task tools using the actual execution
environment. A Run tool plugin can declare `execution.environment` to obtain its
trusted request context, command and sandbox. Paired ports must use the same
registration, name, parameters and scope.

`tool.catalog` may select multiple named providers. `grant_tools: true` is an
explicit trusted runtime grant for a dynamic catalog; a provider must still
filter tools using the Run's accepted product authorization. Otherwise the Agent
and command's static tool grants apply. A catalog registration alone is not a
grant to expose every tool.

Register Skill catalog/source pairs and optional workspace capability. Standard
loading, preloading, activation budget and recovery remain SDK-owned. Configure
context reducers, summarizers and `agent.continuation-policy` as corresponding
capability plugins. Do not replace loop fields after construction.

A shared model budget is an `execution.model-budget` registration selected in
runtime. Returning the same borrowed budget from multiple App registrations
shares its process object and leaves shutdown with its creator. Durable run-tree
budgets are separate from the per-call transport timeout.

External MCP calls default to 7,200 seconds, configurable per MCP server. Timeout
is delivered as a tool result for the Agent. It does not impose a two-hour limit
on internal delegation, Team tasks or the lifetime of a Run.

## Runnable host and validation

The [standard media host](../../../examples/v2/standard_host/README.md) exercises media tools, Skills, Teams and recovery.

Run `examples.v2.standard_host` for actual media dependencies, FFmpeg,
MCP, Skill, nested Team and reopening persisted Runs. Its README documents native
and packaging requirements. `examples.v2.host` demonstrates a smaller host
and custom context plugin. Desktop and Server product adapters register their
corresponding capabilities; no host-defined Driver is required.

SDK integration tests live in `tests/sagents/v2`; host tests live under
`tests/app/v2`. Native isolation tests need platform sandbox support and process
accounting permissions. Frozen-build evidence must be produced from the current
sources.

## Settings metadata without execution resources

```python
from sagents.v2.tool import builtin_tool_definitions

catalog = [
    {"name": value.name, "description": value.description,
     "inputSchema": value.input_schema}
    for value in builtin_tool_definitions(agent_mode="all", language="en")
]
```

The synchronous public query returns detached, name-sorted `ToolDefinition`
values from the actual execution declarations. It creates no App, Run, model,
coordinator, Driver, sandbox or connection. Hosts do not import private method
owners or reflect on implementation classes. Omit `language` for canonical
metadata, or select the standard localized projection.

`agent_mode` accepts the SDK `AgentMode` enum or `simple`, `flow`, `team`,
`fibre`, `all`. Unknown values raise `ValueError` without a fallback. Every mode
includes official base tools and `load_skill`. Team adds
`sys_team_delegate_task`; Fibre adds `sys_spawn_agent` and `sys_delegate_task`.
`all` is their union without duplicates. `official_tool_definitions()` retains
its base-only contract. Product mode names such as Single need an explicit host
mapping to SDK mode names.

Static metadata is not a Run's authorization. Preserve the host's existing Agent
grants when displaying tool/Agent associations; viewing the catalog does not
enable tools or grant delegation to ordinary leaves. MCP, custom tools and
optional host management tools retain their own provider metadata. Hosts can
use this query to replace private reflection while retaining MCP metadata and
Agent authorization display filtering.

Run `python -m examples.v2.tool_catalog --agent-mode all` for JSON output.
`tests/sagents/v2/test_builtin_tool_metadata.py` verifies execution-provider
schema parity, actual standard Run grants, detached metadata and resource-free
import/query behavior.

## Approval, pause, cancellation and publication

Use explicit public `app.runtime` commands: `reply_interaction`, `pause_run`, `cancel_run`, and `resume_run`. Accept `ResumeRun` for a plain suspension or `ReplyInteraction` for an interaction before restoring the original Agent and calling `continue_run`. A duplicate continuation observes existing execution; a terminal Run returns its existing result.

Use `app.entrypoint().propose_session_commit`, `publish_session_commit`, and `reject_session_commit` for snapshot publication. These select the source Run's admitted Agent and retain post-publication memory processing. Server currently has no standalone manual-pause or Session-commit HTTP endpoint; Desktop exposes both. SDK support does not imply every host exposes an HTTP/UI control.

See the [Desktop / Server audit](sagents-v2-host-controls.md) for routes, ownership and validation boundaries.

## Plugin identity and validation scope

`ExtensionScopeContext.agent_id` is the complete source-package Agent identity. `execution_agent_id` is the member alias in the frozen graph; `package_id` and definition source fields retain provenance. Dynamically created members have independent scope identities. Different execution aliases or frozen configurations cannot borrow an Agent configured for another identity. Tenant instances reuse App, tenant and configuration; process scope carries no arbitrary task identity.

For child Runs, `run_configuration()` reports execution alias, source package, source Agent, version and parent Run. Its composition hash identifies the complete accepted graph. Replay and protocol selection retain that graph's original Agent version even when another Agent is loaded concurrently.

`tests/sagents/v2/test_standard_capability_scopes.py` covers actual Runs across scopes, Skill restrictions, factory rollback and custom continuation settings. These replace materializer-only tests. Native media and frozen-host validation run separately.

## Desktop integration boundaries

Desktop models, MCP/Studio tools, Skills, context, self-configuration and continuation are registered capabilities selected by runtime configuration. Agent `preload_skills` passes `sage-openui` to the standard loader, respecting authorization, budgets and activation recovery. Hosts do not inject Skill source directly.

Studio calls validate accepted Agent, Session and user identities. A Studio Session missing its Studio identity fails preflight without a replacement Run. Workspace initialization uses the currently selected registered capability.

`sage.execution.binding.ephemeral` provides an independent in-memory filesystem, without host Python, FFmpeg or network. It uses `workspace_root` and independent child workspaces. Paused content survives only within the same App; restart reports `execution.configuration_incompatible`. Long tasks and media use `sage.execution.binding.local-workspace`. Diagnostics expose `recovery: same_process`, isolation and actual capabilities.

Tests include `tests/app/v2/desktop`, `test_standard_execution_configuration.py`, `test_standard_capability_scopes.py`, `test_builder_nested_teams.py`, `test_ephemeral_execution_binding.py` and the development/frozen media reference `test_standard_host_reference.py`.

## Server integration boundaries

Server uses the same App, Agent loading and execution entrypoints. Capabilities obtain identity, tool authorization and resources from `execution.environment` and accepted product configuration. Product catalog and execution identities are checked separately. Child tool scope follows declarations and cannot expand through dependency packages.

Scheduler registrations declare model-pool dependencies and retain concurrency/queue settings. App stops execution and scheduling before closing dependencies. Runtime configuration selects public protocols such as `ag-ui` and `a2a`. `tests/app/v2/server` covers both entrypoints, recovery, concurrency, authorization, media and cleanup.
