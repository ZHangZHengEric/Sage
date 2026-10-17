# Developing a host with SAgents v2

[中文完整指南](../../zh/architecture/sagents-host-development.md) · [Code map](code-reading-guide.md) · [Runnable starter](../../../examples/sagents_v2_host/)

Use one composition root, one Agent manifest, and common Run correlation IDs.
Product UI, authentication and workspace policy belong to each host. Plugin
loading, context budgets, Session history and recovery belong to the runtime.

## Entry points

```text
SAgentBuilder.build(runtime=..., models=...) → App
  → app.load_agent(package) → reusable LoadedAgent
  → app.entrypoint().run_stream(command, context, agent=agent)
  → stream.events / stream.wait() → app.close()
```

The starter separates manifest configuration (`sage.yaml`), process composition
(`bootstrap.py`) and CLI/Run handling (`__main__.py`). Long-lived services build
one process application at startup and reuse it in request handlers.

From the repository root, with Python 3.12+:

```bash
.venv/bin/python -m examples.sagents_v2_host --offline --inspect
.venv/bin/python -m examples.sagents_v2_host --offline
.venv/bin/python -m examples.sagents_v2_host --offline --log-level debug --runtime-root /tmp/my-sagents-debug
```

These flags are starter conventions, not SDK-wide configuration switches.
For a real model, edit provider/base_url/model in the starter manifest, supply
`MODEL_API_KEY` through the environment and omit `--offline`. Never use the
scripted provider to resume a Run admitted against a real model.
`--inspect` builds and closes an application and opens configured services; it
is not an I/O-free YAML validator. Offline replaces the model port only; the
provided manifest contains no network tools.

## Loading and updating

One new Package defines exactly one Agent. Load it once and reuse the returned
handle. `app.update_agent(agent=old, package=source)` publishes a new immutable
revision; existing handles and admitted Runs retain their original revision.
Identical loads reuse handles, invalid updates preserve the current version,
and stale concurrent updates are rejected.

`load_agent` accepts a file/directory path, manifest or dictionary. Use
`config_text=` explicitly for YAML/JSON text; file references require `base_path`
and cannot escape it. `build(runtime=...)` accepts RuntimeConfig, dictionaries
or paths; text uses `runtime_config_text=`. Object/path and text inputs are
mutually exclusive. A directory Package uses `sage.yaml`.

Without runtime configuration, the SDK uses the same shared component defaults
as Desktop, excluding personal settings and credentials. Explicit runtime
replaces defaults; use `sagents.v2.default_runtime()` to
start with the shared profile and customize selected capabilities. Resources
open lazily when the first Agent loads. Commands use the loaded handle's `id`
and `composition_hash`; the run entrypoint validates them.

All revisions share a dispatcher and durable stores. Revisions remain alive
until App shutdown, so frequent updates consume additional memory. Local SDK
recovery snapshots are saved under `agent-revisions/` in the runtime data root.
Use `await app.agent_for_run(run_id, context)` to authorize and retrieve the
original revision before manually continuing a suspended Run.
Keep snapshots with Session data; missing/incompatible revisions cannot be replaced
with the latest version during recovery. This is local persistence, not a
distributed package registry.

Desktop and Server inject `HostAgentExecution` for their existing admission and
frozen recovery contracts. Per-Run resources are still acquired and closed per
Run. `build(package)` is removed and public loading rejects multi-Agent Packages.
All hosts use build → load_agent → explicit Agent execution.

Load child Packages independently and bind immutable handles:

```python
reviewer = await app.load_agent("./agents/reviewer")
coder = await app.load_agent("./agents/coder", subagents={"reviewer": reviewer})
```

Updating reviewer does not change coder. Explicitly update coder with the new
child handle to adopt it. Private recovery snapshots preserve the full compiled
graph. Managed `AgentPackageBundle.dependencies` persists the individual child
Packages; each is loaded through the same App API. CLI presets follow this
pattern, and TUI uses the same CLI through `sage v2 chat --json`.

## Delegated task Sessions

Default delegation passes only the task message. Without `child_session_id`, it creates an independent serial Session whose first `user` message is the parent's task. With an existing child Session, it appends a new `user` task and retains that child's own history. `parent_run_id`, `parent_tool_call_id` and Session ancestry support tracing, result routing and storage layout; they do not implicitly copy parent messages or attachments. Put necessary background and resource references in content; original_task is tracing metadata and is not automatically sent as a child message. Explicit low-level `FORK` requests retain their snapshot semantics and are separate from default delegation.

## Configuration boundaries

| Input | Owner |
| --- | --- |
| Instructions, model routes, tool/Skill allowlists, budgets | Agent manifest |
| Capability plugin IDs, scopes and plugin parameters | Manifest runtime/plugins |
| Data paths, log level, manifest location | Host settings |
| SessionStore, execution bindings, shared model budget, sinks | Bootstrap `Builder.with_*()` injections |
| Input, Session, idempotency and admitted identity | `StartRun` |
| Authenticated principal/tenant | Host-created `RequestContext` |
| Secrets | Credential providers referenced by manifest; never committed plaintext |

Loader environment overlays may override only `runtime`, `policies`, and
`interfaces`. There is no universal environment-variable-over-YAML rule.
Explicit host injections select their corresponding ports; trusted locked
runtime dependencies cannot be replaced by plugin config. Inspect
`agent.resolved_plan` for a standard SDK revision; `app.resolved_plan` is the
initial process view. Host-injected execution reports its full component plan
when the admitted Run is composed, not in the loaded definition.
`with_shared_runtime()` borrows its documented services, not every host setting.

## Common debugging contract

The starter writes events/final state to stdout and structured `sage.log/v1`
logs to stderr. `FilesystemDiagnosticSink` writes model evidence under the
owning Session/Run in `runtime_root/sessions`. Diagnostics can contain business
data and should remain private even after credential redaction.

1. Inspect `app.resolved_plan`: capability, plugin ID, scope, source and composition hash.
2. Use `with_readiness_check()` and inspect `app.resource_readiness`. Readiness is not live execution acceptance.
3. Correlate Session, Run, step, model request and tool-call IDs where available.
4. Treat Session events/state/checkpoints as authoritative; diagnostics never drive recovery.
5. Inject `ScriptedModelProvider` for offline tests while retaining the same bootstrap and event path.

Do not dump raw provider configs or change an admitted hash to bypass recovery
validation. Preserve admitted snapshots and reconcile unknown tool outcomes
instead of replaying effects.

## One entry point, explicit host parameters

Desktop, Server and third-party projects use `SAgentBuilder.build()` and the
same `AgentCompositionFactory.create_loop()` loop assembly. Hosts supply their
authentication, approval and workspace policies through parameters and existing
ports. Internal assemblers/materializers remain implementation details.

App owns model routes, credentials, request defaults, limits and capabilities.
Pass these as `models="./models.yaml"` (or a dictionary / ModelCatalogConfig).
Use `models_config_text=` for YAML/JSON text. Runtime components remain a separate
`runtime` input. Packages only map model slots to App model IDs.

Use `app.update_models(...)` to atomically replace the catalog, or
`app.update_model(id, complete_route)` to replace one route. Reload an unchanged
Package to adopt updated models; edit the Package with `update_agent`.
Existing handles and admitted Runs keep their frozen configuration.
Builder configuration only affects applications built afterwards.

```python
from sagents.v2 import SAgentBuilder
from examples.sagents_v2_host.plugins import compactor_registration

builder = SAgentBuilder().with_defaults(session_root="./runtime")
builder.register(compactor_registration())
app = await builder.build(models="examples/sagents_v2_host/models.yaml", runtime={
    "capabilities": {
        "context.unit-compactor": {
            "plugin": "example.context.reference-compactor",
            "scope": "agent",
            "config": {"minimum_characters": 4},
        },
    },
})
agent = await app.load_agent("examples/sagents_v2_host/sage.yaml")
# Supply model credentials and close the application after use.
```

The starter's `plugins.py` implements an independent plugin with a parameter
model, JSON Schema and registration factory. Its byte heuristic demonstrates
integration, not a production tokenizer. Register first, then select using
`CapabilitySelection` fields `plugin / name / scope / config`. Schema validation
runs before the factory. Unknown fields are governed by each plugin's schema;
the example rejects them. Trusted dependencies are separate from user config.
Plugin implementations never need to import sibling implementations.

Both hosts accept `extensions=(registration,)` at construction:
`DesktopV2Service(...)` and `ServerHost(...)`. The old `package_extensions` argument is removed. Registration supplies implementations; runtime
configuration selects them and supplies parameters.

Hosts that admit Runs themselves use the same existing integration interfaces:

- `application.compose_run(callback)` owns rollback and Run resources, not admission.
- `materialize_agent(..., runtime=...)` resolves scoped ports on an existing application.
- `with_shared_runtime()` borrows process services for a package application.
- `AgentCompositionFactory.create_loop()` accepts explicit `context_providers`,
  `developer_instructions`, `context_agent_id`, `completion_gates` and
  `automatic_memory_recall`. Omitted arguments preserve defaults. Desktop keeps
  its prompt order, root context budget and root-only plan/goal gates here.
- `application.process_provider(capability, selection, dependencies=...)` opens
  registered process providers through the same validation/cache/lifecycle path.
  The application owns these providers. Desktop uses this for sandbox providers;
  custom constructor parameters go in its sandbox `provider_config`, separately
  from per-sandbox execution specifications. Legacy constructor fields still work.

These host parameters do not authorize changes to admitted recovery inputs.
Keep frozen snapshots and durable sandbox lifecycle handling unchanged.

Server examples are `bootstrap.py`, `packages/builder.py`, and `runtime/loop.py`.
Desktop examples are `backend/composition.py`, `run_composition.py`,
`component_plan.py`, and `model_providers.py`. Product policies stay separate.
Plugin implementations stay independent; duplication is allowed.

Injected resources are borrowed unless explicitly transferred. After successful
`compose_run()`, the host closes the returned `ComposedRun`; register only newly
owned resources with `resources.own()`. Dependencies can be registered with
`dependency=True`. Runtime cleanup is distinct from durable sandbox lifecycle.
Closing an observer does not cancel a Run. Admission retries reuse idempotency
keys; new operations use new keys. The starter defaults to a new key per launch
and is not a production request-deduplication store.

Built-in demo defaults do not establish multi-process or distributed recovery.
Test configuration, offline execution, resource failure/cleanup, idempotency,
approval/resume, frozen recovery inputs and unknown-effect reconciliation.
Add child-Run isolation/recovery coverage for delegation.

```bash
.venv/bin/pytest -q tests/sagents/v2/test_host_starter_example.py tests/sagents/v2/test_unified_host_configuration.py
.venv/bin/pytest -q tests/sagents/v2/test_builder_matrix.py tests/sagents/v2/test_run_composition_lifecycle.py
```

Tests have a default 30-second hang guard; use explicit assertions for performance
contracts and test-specific timeout markers when needed.

Desktop and Server both acquire sandbox providers through application-owned plugin lifecycles. Server configuration and Agent validation use the host registration registry.


## Verification

Run the Python suites under `tests/sagents/v2`, `tests/app/v2/server`,
`tests/app/v2/desktop`, and `tests/app/clients/cli` (excluding optional live suites).
Run `flutter test` in `app/v2/desktop`, and `cargo test --offline` in
`app/clients/terminal`.

For an opt-in real-model Desktop test, run
`SAGE_DESKTOP_LIVE_CATALOG="$HOME/sage/runtime/desktop-catalog.json" flutter test test/unified_sidecar_test.dart`.
It uses the first Agent's configured model, or the explicit provider ID in
`SAGE_DESKTOP_LIVE_MODEL`. It starts the real Python sidecar with isolated data,
checks two turns and history recall, and incurs real model request costs.

Internal assembly regression tests use private `_build_package` to inspect
compiled execution graphs. Applications and public API tests use `build()` and
`load_agent()`; private assembly methods are not integration entrypoints.
