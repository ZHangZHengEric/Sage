# Sage SDK integration

The application owns execution assembly. Hosts register implementations, select
capabilities in serializable runtime configuration, and use the same public Run
API for built-in and custom plugins.

```python
"""Set MODEL_API_KEY and replace your-model below; no sage.yaml file is needed."""

import asyncio
from uuid import uuid4

from sagents.v2 import ActorRef, RequestContext, SAgentBuilder, StartRun
from sagents.v2.contracts.commands import InputItem
from sagents.v2.contracts.items import TextBlock
from sagents.v2.contracts.principals import PrincipalType
from sagents.v2.package.manifest import SageManifestLoader

AGENT_YAML = """
schema_version: sage/v2
kind: application
metadata: {id: example.assistant, version: 1.0.0, name: Assistant}
agents:
  main:
    name: Assistant
    instructions: {inline: "Be helpful and concise."}
    models: {primary: primary}
entrypoint: {agent: main}
"""

MODELS_YAML = """
credentials:
  api-key: {source: env, key: MODEL_API_KEY}
models:
  primary:
    provider: openai-responses
    base_url: https://api.openai.com/v1
    credential: api-key
    model: your-model
"""


async def main(*, runtime=None, registrations=()):
    from sagents.v2.composition.defaults import default_runtime
    manifest = SageManifestLoader().loads(AGENT_YAML)
    builder = SAgentBuilder()
    for registration in registrations:
        builder.register(registration)
    app = await builder.build(runtime=runtime or default_runtime("runtime"), models_config_text=MODELS_YAML)
    try:
        agent = await app.load_agent(manifest)
        context = RequestContext(actor=ActorRef(
            principal_id="user-1", principal_type=PrincipalType.USER,
        ))
        stream = await app.entrypoint().run_stream(StartRun(
            agent_id=agent.id,
            input=(InputItem(role="user", content=(TextBlock(text="Say hello!"),)),),
            resolved_spec_hash=agent.composition_hash,
            idempotency_key=str(uuid4()),
        ), context, agent=agent)
        async for event in stream.events:
            print(event.model_dump_json())
        print((await stream.wait()).state)
    finally:
        await app.close()


if __name__ == "__main__":
    asyncio.run(main())
```

`package`, `command`, `context`, configuration and event handling belong to the
host. `subagents` maps declared direct member names to loaded Agent handles.
Load each dependency package separately. An Agent package has one Agent; nested
Teams are explicit package relationships. A delegated ordinary leaf does not
gain a Team roster through its parent.

`SAgent` and `SAgentApplication` are created by the Builder. Direct construction
with execution components or a custom Driver is rejected. Hosts use `load_agent`
and the public Run APIs for execution and recovery.

## Registration and selection

A registration describes a capability protocol and executable factory. The
factory implements that capability, rather than reconstructing the Run Driver,
Agent loop, official runtime or child executor.

```python
from sagents.v2.runtime.extensions import (
    CapabilityOffer, ExtensionDependency, ExtensionDescriptor,
    ExtensionRegistration, ExtensionScope,
)

registration = ExtensionRegistration(
    descriptor=ExtensionDescriptor(
        plugin_id="example.run.model",
        name="Example Run model",
        version="1.0.0",
        api_version="2",
        provides=(CapabilityOffer(capability="model.provider", api_version="2"),),
        dependencies=(ExtensionDependency(capability="session.store"),),
        supported_scopes=frozenset({ExtensionScope.RUN}),
        default_scope=ExtensionScope.RUN,
        config_schema={"type": "object", "properties": {
            "profile": {"type": "string"}}, "additionalProperties": False},
    ),
    factory=lambda scope, dependencies: ExampleModel(
        profile=scope.config.get("profile", "default"),
        store=dependencies.require("session.store"),
        run_id=scope.run_id,
    ),
    ownership="owned",
)
builder.register(registration)
```

Select the registration separately:

```yaml
capabilities:
  model.provider:
    plugin: example.run.model
    scope: run
    config:
      profile: media
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

Startup isolates unavailable, corrupt or incompatible historical Agent revisions.
Other revisions and new conversations remain usable. `app.recovery_issues` returns
an immutable host-level snapshot of affected Run/Session IDs, revision hashes and
reasons from the latest restore pass. Blocked Runs retain their original state,
checkpoints and tool receipts; they are not silently rerouted or replayed. Process
store/bootstrap failures and startup cancellation still abort construction.

User cancellation is terminal and excluded from startup restoration. When a
cancelled Run has a tool call without a result, Session history supplies a
synthetic tool message stating that no result was received and the external
outcome is unknown. This closes the model protocol pair for subsequent turns
without claiming an execution receipt or continuing the cancelled Run.

```python
agent = await app.agent_for_run(run_id, context)
task = await app.entrypoint().continue_run(run_id, context, agent=agent)
result = await task
snapshot = await app.execution_configuration(run_id, context)
facts = await app.execution_diagnostics(run_id, context)
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

## Tools, Skill, continuation and budgets

Select `tool.provider` once per registered plugin. The provider owns both
its catalog and executor. Sage
assembles official file, Shell, Skill and task tools using the actual execution
environment. A Run tool plugin can declare `execution.environment` to obtain its
trusted request context, command and sandbox. Paired ports must use the same
registration, name, parameters and scope.

`tool.provider` may select multiple named providers. `grant_tools: true` is an
explicit trusted runtime grant for a dynamic catalog; a provider must still
filter tools using the Run's accepted product authorization. Otherwise the Agent
and command's static tool grants apply. A catalog registration alone is not a
grant to expose every tool.

Register one `skill.provider` for discovery and bundle reads, with an optional
workspace capability. Standard
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

Run `examples.v2.standard_host` for actual media dependencies, FFmpeg,
MCP, Skill, nested Team and reopening persisted Runs. Its README documents native
and packaging requirements. `examples.v2.host` demonstrates a smaller host
and custom context plugin. Desktop and Server product adapters register their
corresponding capabilities; no host-defined Driver is required.

SDK integration tests live in `tests/sagents/v2`; host tests live under
`tests/app/v2`. Native isolation tests need platform sandbox support and process
accounting permissions. Frozen-build evidence must be produced from the current
sources.

## Direct child Run recovery

A suspended child can be resumed while its ancestors remain suspended. Use
`agent_for_run`, the standard suspension/interaction APIs, and `continue_run`.
Sage restores resource-only ancestor leases from accepted snapshots and selects
the child's actual definition from the original execution graph. It does not
execute ancestor Agents or create replacement Runs. Dependency handles close
with the child without cancelling independent ancestor handles.

See the [tree recovery contract and example](../../docs/zh/architecture/sagents-v2-run-tree-recovery.md).

## Settings tool metadata without a Run

```python
from sagents.v2.tool import builtin_tool_definitions

rows = [
    {"name": tool.name, "description": tool.description,
     "inputSchema": tool.input_schema}
    for tool in builtin_tool_definitions(agent_mode="all", language="zh")
]
```

This synchronous query returns detached `ToolDefinition` values from the same
implementation definitions used by execution. It creates no App, Run, model,
coordinator, sandbox or connection. Modes are `simple`, `team`, `fibre`, `flow`,
and `all`; unknown values raise `ValueError`. Every mode includes official base
and Skill metadata. Team adds `sys_team_delegate_task`; Fibre adds
`sys_spawn_agent` and `sys_delegate_task`; `all` is their union. Omit `language`
for canonical implementation text, or select the standard localized projection.

This is the standard built-in Agent catalog, not a Run's authorized tools.
Keep the host's Agent grants and external/custom tool metadata separate; querying
or displaying a definition does not enable it. Mode alone cannot determine a
particular delegation leaf's permissions. Optional host management tools also
belong to their configured provider, not this standard catalog. Hosts do not
import private method owners or reflect on implementation classes.

Runnable JSON example: `python -m examples.v2.tool_catalog --agent-mode all`.
