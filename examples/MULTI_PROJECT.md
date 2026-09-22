# Single-process multi-project integration

Run the offline Core example from the repository root:

```sh
.venv/bin/python -m examples.sagents_v2_multi_project
```

Expected result: `{'sessions': 3, 'concurrent_runs': 3, 'artifacts': 9}`.

The example uses one `SAgentBuilder` Application, one host-owned filesystem
SessionStore, one agent definition, two project directories, and three Sessions
(two in project A). A barrier requires all three Runs to reach the model before
any can finish. Each Run makes three calls to the same MCP tool name, with its
directory selected from durable Run metadata. Artifacts contain the actual Run
and Session identities. The regression also cancels A1 while B1 and A2 finish.

Only public `sagents/v2` interfaces are imported. The scripted model and
in-process MCP session factory are test doubles: this is not a real-provider,
stdio-process, distributed-storage, or security-sandbox certification. The host
tool router is intentionally included to show the integration responsibility:
metadata alone does not change a tool's directory or bind its resources.

Hosts should resolve authorized project directories and model routes before
creating StartRun, narrow tools with CompositionResolver, and route tool calls
by durable owner_run_id. Do not set process-global cwd/environment or update a
shared agent definition between Runs. Native file/shell tools require a
Run-owned ExecutionBindingProvider as well; a prompt directory is not a sandbox.

The example's parent lookup supports inherited project bindings, but its
end-to-end scenario does not exercise delegated agents or restart recovery.
Do not interpret the root-Run test as evidence for those additional scenarios.

## Desktop service API

Desktop now supports the same concurrency shape without creating a service per
project. Register static catalog providers/agents/MCP servers once; register
project directories with `add_project`; pass per-invocation changes in
`DesktopRunRequest.run_context`:

```python
from app.desktop_v2.backend.schemas import (
    DesktopMcpBinding, DesktopRunContext, DesktopRunRequest, RunMessage,
)

request = DesktopRunRequest(
    agent_id="shared-agent",
    session_id="project-a-session-1",
    workspace_id=project_a.id,
    messages=[RunMessage(role="user", text="Continue this project")],
    run_context=DesktopRunContext(
        model_provider_id="provider-a",
        fast_model_provider_id="provider-a-fast",
        system_context={"project_id": "a", "ownership_session_id": "project-a-session-1"},
        tools=["mcp_project_write"],
        mcp_bindings=[DesktopMcpBinding(
            name="project", env={"PROJECT_DIRECTORY": project_a.path},
        )],
    ),
)
# Consume independent requests concurrently with asyncio tasks/gather.
async for event in service.run_events(request, user_id):
    handle_event(event)
```

Semantics:

- `workspace_id` selects a registered, validated project. Its resolved path is
  frozen for the Run; changing/removing the registration does not redirect it.
- `system_context` merges into copied agent defaults. Explicit model selections
  apply to the captured roster (including children); omitted model fields retain
  each agent's defaults. `tools` narrows the root agent's grant; it cannot expand
  an explicit catalog grant. An explicit list without `load_skill` also disables
  root Skills so composition cannot implicitly expand that list. Child agents
  retain their own tool grants.
- Omitted `mcp_bindings` preserves enabled catalog servers as optional bindings;
  `[]` binds none. Explicit bindings default to required. Names are unique within
  one invocation. `env` overrides are supported for stdio only.
- MCP bindings get separate plugins per root Run; children of that Run share its
  captured plugin. The standard MCP transport still opens a short-lived session
  for discovery/call, not a cross-project connection pool. Host-supplied pools
  must isolate all project/identity-dependent state themselves.
- Credentials belong in catalog/credential providers. `run_context` (including
  env overrides and system context) is persisted: supply non-secret values there.
  Catalog MCP env and API keys are not copied into the new environment snapshot;
  only their configuration fingerprint is stored.
- Model routes, agent roster, workspace path and runtime settings are snapshotted
  before admission. Lazy driver construction and child composition use that
  snapshot. In-process suspension/resume retains the captured credentials and MCP
  configurations. Explicit "approve and remember" shell authorizations remain
  effective on continuation without adopting unrelated catalog changes.
  After restart, model credentials are looked up by their original
  provider ID; MCP configuration must match the persisted fingerprint. Missing or
  changed MCP configuration fails closed, requiring restoration of the original
  catalog binding. Old persisted Runs without snapshots keep legacy behavior.
- Different Sessions can run concurrently, including within one project. The
  default SERIAL policy still excludes simultaneous active Runs in the same
  Session. Scheduler and model concurrency limits still apply; no global
  configuration lease is held for the duration of a Run.

Host-owned storage can be passed directly without subclassing DesktopV2Service:

```python
store = FilesystemSessionStore(storage_root)
service = DesktopV2Service(
    desktop_root, session_store=store, derived_state_store=store,
)
try:
    ...
finally:
    await service.close()
    await store.close()
```

An injected SessionStore is borrowed and is not opened or closed by Desktop.
An omitted derived-state store defaults to the Core builder's in-memory derived
state when the authoritative store is injected. Inject durable derived state
explicitly when needed. Default Desktop construction still owns its filesystem
store. Use one service/scheduler for the shared store; this change does not grant
multi-process write guarantees or coordinate independent schedulers.

## Validation

```sh
.venv/bin/pytest -q tests/sagents/v2/test_multi_project_example.py \
  tests/app/desktop_v2/test_run_isolation.py
```

Desktop tests use its actual dispatcher, loops, event streams and filesystem
store with offline model/MCP transports. They cover cross-project and
same-project Sessions, changes between admission and lazy composition, model
and context isolation, file destinations, cancellation, snapshot restoration
through a child command's parent lineage after reopening the service/store,
approval suspension and driver recomposition while another Session completes,
rejection of changed MCP bindings,
tool-grant narrowing and borrowed-store ownership. Snapshot restoration tests
do not certify replay of uncertain external tool effects.
