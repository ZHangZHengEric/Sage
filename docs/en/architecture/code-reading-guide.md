# Sage v2 code reading guide

For a new host project, start with the [configuration and debugging guide](sagents-host-development.md).

[中文](../../zh/architecture/code-reading-guide.md)

Sage has an embeddable runtime and two product hosts. Start with a single Run,
not the largest file. Legacy code under `app/v1` is not required to understand v2.

## First reading path

1. Run or read [the Python quickstart](../../../examples/sagents_v2_quickstart.py).
   Follow `build → entrypoint → run_stream → wait → close`.
2. Read [commands](../../../sagents/v2/contracts/commands.py),
   [Run state](../../../sagents/v2/contracts/run_state.py), and
   [events](../../../sagents/v2/contracts/events.py) for the vocabulary.
3. Read [Builder](../../../sagents/v2/builder.py) for configuration and
   [Application](../../../sagents/v2/application.py) for public lifetime boundaries.
4. Read [SAgent](../../../sagents/v2/sagent.py) for execution-task ownership and
   observation, then [Kernel](../../../sagents/v2/runtime/kernel.py) for durable
   commands. Closing an observer does not cancel a Run.
5. Only then follow [AgentLoopEngine](../../../sagents/v2/agent/engine.py) into
   model steps, tools, checkpointing and recovery. Its large execution methods
   still coordinate these semantics; this composition refactor does not rewrite
   the state machine.

## Find code by the change you want to make

| Change | Start here | Validate with |
| --- | --- | --- |
| Application/provider wiring | [Composition map](../../../sagents/v2/composition/README.md) | `tests/sagents/v2/test_builder_matrix.py` |
| Run ownership and cleanup | `sagents/v2/application.py`, `composition/resources.py` | `tests/sagents/v2/test_run_composition_lifecycle.py` |
| Tool execution or interrupted effects | `sagents/v2/agent/engine.py`, `runtime/execution/lifecycle.py` | Recovery and execution-binding matrices in `tests/sagents/v2` |
| Session persistence | `sagents/v2/runtime/session/contracts.py`, then `state.py` | Session-store, transaction and fencing matrices |
| A model/tool/storage plugin | The domain's contract, then one `plugins/` implementation | That plugin's matrix plus `test_source_boundary_matrix.py` |
| Server admission/auth | `app/v2/server/conversations/admission.py`, `identity/` | `tests/app/v2/server` |
| Desktop backend behavior | `app/v2/desktop/backend/service.py`, `run_service.py` | `tests/app/v2/desktop` |
| Desktop rendering/state | `app/v2/desktop/lib/src/state/workspace_controller.dart`, `ui/` | `app/v2/desktop/test` |

## Trace the hosts

Server: `bootstrap.py` creates process services. Conversation admission freezes
catalog/policy inputs; `runtime/loop.py` resolves those inputs and calls
`application.compose_run()`. `packages/builder.py` borrows process runtime
services through `with_shared_runtime()`. `runtime/driver.py::CatalogRunDriver`
drives and closes the package application. Skill catalog/workspace
adapters remain in `skills/runtime.py`.

Desktop: `backend/service.py` owns process services. `run_service.py` admits and
observes Runs; `run_composition.py::_build_loop` calls the same
`application.compose_run()` boundary, obtains scoped ports through
`materialize_agent()`, and retains desktop policy/workspace wiring.
`run_lifecycle.py` connects Run resources to sandbox suspension and deferred
cleanup. Core resource ownership is in SAgents; desktop-specific lifecycle
policy stays in the host.

For composition internals, read `composition/agent_components.py` for the named
Agent dependency graph, then `composition/bound_tools.py` for workspace and tool
wiring after binding validation. Neither owns binding acquisition or recovery.
`agent/factory.py::create_loop()` is the shared host API. Explicit parameters
select prompt order and completion gates while preserving common authorization,
budget and authoritative history composition.

Desktop's `component_plan.py` translates frozen settings into component choices,
locked dependencies and cache identities. `model_providers.py` translates model
routes and owns process-local provider reuse under the host concurrency budget.
The run coordinator consumes these objects without duplicating their algorithms.
Member context budgets still use the root Agent; provider order and plan/goal
gates remain host policy.

The host adapters still contain significant product-specific wiring. Do not
assume every long function was split, or that `compose_run()` is a new durable
scheduler: it is an assembly/ownership boundary.

## Boundaries to preserve

- `sagents/v2` never imports applications; desktop and server do not import each
  other. Plugin implementations do not import sibling implementations.
- `StartRun`, frozen grants and composition identity describe what was admitted;
  recovering a Run must not silently pick wider permissions from live settings.
- Session mutation, events and checkpoints retain their atomic commit boundary.
- Unknown external side effects suspend/reconcile; refactoring cleanup must not
  introduce automatic retries of tool effects.
- Borrowed process resources survive closing a Run's package application.
- Resource cleanup and durable sandbox release are different operations.

## Local verification

From the repository root, using its Python 3.12+ virtual environment:

```bash
.venv/bin/pytest -q tests/sagents/v2/test_builder_matrix.py tests/sagents/v2/test_run_composition_lifecycle.py tests/sagents/v2/test_source_boundary_matrix.py tests/sagents/v2/test_composition_source_boundaries.py
.venv/bin/pytest -q tests/app/v2/server tests/app/v2/desktop
```

Live model and external database/sandbox tests require their own configured
services. A local test pass does not establish distributed deployment readiness.
