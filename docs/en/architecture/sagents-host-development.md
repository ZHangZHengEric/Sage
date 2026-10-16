# Developing a host with SAgents v2

[中文完整指南](../../zh/architecture/sagents-host-development.md) · [Code map](code-reading-guide.md) · [Runnable starter](../../../examples/sagents_v2_host/)

Use one composition root, one Agent manifest, and common Run correlation IDs.
Product UI, authentication and workspace policy belong to each host. Plugin
loading, context budgets, Session history and recovery belong to the runtime.

## Entry points

```text
sage.yaml → bootstrap.build_application() → SAgentBuilder.build()
          → SAgentApplication.entrypoint() → SAgent.run_stream(command, context)
          → events / wait() → application.close() at host shutdown
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
`app.resolved_plan` for the effective binding and its source.
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

Agent definitions live in an Agent Package. Its `sage.yaml` describes Agents,
models, tools, Skills and policies, and can include runtime selections. Optional
`build(package, runtime=...)` accepts the same `RuntimeConfig` (or a dictionary),
not a separate configuration language. This replaces the entire package runtime;
omitting it preserves the package configuration. It is applied before resolution,
so equivalent effective configurations have identical composition identities.
An already resolved package cannot receive a different runtime. Server retains
its existing deployment/package merge in its adapter before calling this entry.

```python
from sagents.v2 import SAgentBuilder
from examples.sagents_v2_host.plugins import estimator_registration

builder = SAgentBuilder().with_defaults(session_root="./runtime")
builder.register(estimator_registration())
app = await builder.build("examples/sagents_v2_host/sage.yaml", runtime={
    "capabilities": {
        "context.token-estimator": {
            "plugin": "example.context.byte-estimator",
            "scope": "agent",
            "config": {"bytes_per_token": 4.0},
        },
    },
})
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
`DesktopV2Service(...)` and `ServerHost(...)`. Server also retains the legacy
`package_extensions` argument. Registration supplies implementations; runtime
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
