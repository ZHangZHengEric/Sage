---
layout: default
title: Code Reading Guide
parent: Architecture
nav_order: 12
lang: en
ref: v2-detail-code-reading-guide
---

{% include lang_switcher.html %}

# Sage v2 code reading guide

For a new host, start with the [development, configuration and debugging guide](sagents-host-development.md). Consult the [Runtime reference](sagents-runtime-reference.md) and [sage.yaml reference](sagents-manifest-reference.md) for fields.

Sage consists of an embeddable runtime and Desktop/Server product hosts. Trace one Run first; understanding `app/v1` or the largest file is unnecessary.

## First reading path

1. Start with the [Python example](../../../examples/sagents_v2_quickstart.py), following `build → load_agent → entrypoint → run_stream → wait → close`.
2. Read [commands](../../../sagents/v2/contracts/commands.py), [Run states](../../../sagents/v2/contracts/run_state.py) and [events](../../../sagents/v2/contracts/events.py) to understand input, state and output.
3. [Builder](../../../sagents/v2/builder.py) is the configuration entrypoint; [Application](../../../sagents/v2/application.py) defines composition and lifetime.
4. [SAgent](../../../sagents/v2/sagent.py) owns execution tasks and observation; [Kernel](../../../sagents/v2/runtime/kernel.py) handles durable commands. Disconnecting an observer does not cancel a Run.
5. Finally, read [AgentLoopEngine](../../../sagents/v2/agent/engine.py) for model steps, tools, checkpoints and recovery. The composition refactor did not rewrite this state machine.

## Find code by the change you want to make

| Change | Start here | Tests |
| --- | --- | --- |
| Composition and plugin selection | [Composition map](../../../sagents/v2/composition/README.md) | `tests/sagents/v2/test_builder_matrix.py` |
| Run ownership and cleanup | `sagents/v2/application.py`, `composition/resources.py` | `test_run_composition_lifecycle.py` |
| Tool execution and uncertain effects | `sagents/v2/agent/engine.py`, `runtime/execution/lifecycle.py` | Recovery and execution-binding tests |
| Session persistence | `runtime/session/contracts.py`, then `state.py` | Session-store, transaction and fencing tests |
| Model, tool or storage plugins | Domain contract, then a `plugins/` implementation | Plugin tests and `test_source_boundary_matrix.py` |
| Server admission and authorization | `app/v2/server/conversations/admission.py`, `identity/` | `tests/app/v2/server` |
| Desktop backend | `app/v2/desktop/backend/service.py`, `run_service.py` | `tests/app/v2/desktop` |
| Desktop state and rendering | `lib/src/state/workspace_controller.dart`, `ui/` | `app/v2/desktop/test` |

## Reading composition code

`SAgentBuilder` collects explicit `BuildOptions` and passes them to `ApplicationAssembler`, which resolves configuration, creates process services, composes Agents/Flows, validates capabilities and starts the dispatcher. `AgentMaterializer` resolves tenant, Agent and Run components on an existing App. Both paths use ExtensionHost through `providers.py`.

Continue through these boundaries:

- `composition/agent_components.py` defines named Agent dependency results, replacing positional tuples. App still owns scopes.
- `composition/bound_tools.py` wires validated bindings into workspaces, tools and runtime services; drivers still own acquisition, rollback and recovery.
- `agent/factory.py` exposes shared `create_loop()` with explicit prompt order, completion gates and budgets while preserving common authorization and history rules.

`application.compose_run()` owns Run composition and resources. Its callback registers only newly created Run-owned objects; failures roll back and success transfers cleanup responsibility to the caller. It neither creates Runs nor replaces scheduling or recovery.

Services close before their dependencies. A failed service close preserves its sandbox for retry; only failed resources are retried. Composition failure retains existing rollback rules and App retains residual cleanup failures until shutdown.

## Host call chains

**Server:** `bootstrap.py` creates process services; admission freezes configuration and grants. `runtime/loop.py` calls `application.compose_run()`. `packages/builder.py` borrows process services through `with_shared_runtime()`. `runtime/driver.py::CatalogRunDriver` drives and closes the Package application. Skill catalog/workspace adapters remain in `skills/runtime.py`.

**Desktop:** `backend/service.py` owns process services. `run_service.py` admits and observes Runs. `run_composition.py::_build_loop` calls the same `application.compose_run()` and obtains scoped components through `materialize_agent()`, preserving Desktop approvals and workspace wiring. `run_lifecycle.py` handles suspension, deferred release and sandbox lifetime.

`component_plan.py` translates frozen Desktop settings into selections, locks and cache identities. `model_providers.py` translates model routes and caches providers under the shared host budget. `run_composition.py` connects them without duplicating routing or budgeting. Members retain root Agent context budgets and existing plan/goal policies.

Hosts still contain substantial product wiring. Their policies remain independent, and not every large method has been split.

## Boundaries to preserve

- Runtime does not import applications; Desktop and Server do not import each other.
- Plugins remain independent and do not import sibling implementations.
- Recovery uses admitted identity and grants without broadening them from live settings.
- Session state, events and checkpoints retain one atomic commit boundary.
- Uncertain external effects suspend or reconcile rather than replaying tools.
- Closing a Run application does not close borrowed process services.
- Memory cleanup differs from durable sandbox release and reconciliation.

## Local verification

From the repository root with Python 3.12+:

```bash
.venv/bin/pytest -q tests/sagents/v2/test_builder_matrix.py tests/sagents/v2/test_run_composition_lifecycle.py tests/sagents/v2/test_source_boundary_matrix.py tests/sagents/v2/test_composition_source_boundaries.py
.venv/bin/pytest -q tests/app/v2/server tests/app/v2/desktop
```

Real model, database and external sandbox tests require configured services. A local pass does not establish distributed readiness.

Current entrypoint: `builder.build(runtime=..., models=...)` → `app.load_agent()` → `app.entrypoint().run_stream(..., agent=agent)` → `app.close()`.

Loading, revision publication and snapshots live in `sagents/v2/composition/loaded_agents.py`, `inputs.py` and `revision_store.py`; `defaults.py` supplies shared SDK/Desktop defaults.

Read `sagents/v2/builder.py` for App creation, `composition/loaded_agents.py` for revisions, `composition/agent_graph.py` for child bindings and `agent/management/loading.py` for persisted dependency trees. CLI composition lives in `app/v2/cli/host.py`; TUI reuses CLI v2.

See [App model configuration](sagents-runtime-reference.md#app-模型配置): App owns connections, request options and capabilities; Packages reference model IDs. Runtime updates publish a new catalog before loading Agents, while admitted Runs retain their model snapshots.
