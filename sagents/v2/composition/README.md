# Reading application composition

Start with the [repository code map](../../../docs/en/architecture/code-reading-guide.md).
The public entry points remain `SAgentBuilder` and `SAgentApplication`; this
package contains their implementation, not a second public framework.

| File | Responsibility | Does not own |
| --- | --- | --- |
| `options.py` | Explicit host injections collected by Builder | Provider lifetime |
| `resolution.py` | Resolve manifests, trust checks and selection rules | Live resources |
| `providers.py` | Open selected providers through ExtensionHost | Plugin implementation |
| `assembler.py` | Initial application wiring, Agent/Flow driver factories and capability validation | Host business policy |
| `agent_components.py` | Named Agent component graph and dependency order | Plugin scope ownership |
| `bound_tools.py` | Run-bound workspace and official-tool service wiring | Binding acquisition, retry or cleanup |
| `materializer.py` | Scoped Agent ports and tenant/Agent-aware reuse in an existing application | Run admission |
| `contracts.py` | Assembly result types | Construction or execution |
| `identity.py` | Existing composition/cache identity rules | Credentials in plain text |
| `drivers.py` | Bind actual Run IDs to execution resources before creating loops | Session transitions |
| `resources.py` | Run ownership, rollback and retryable cleanup | Durable sandbox reconciliation |

## Initial application

`SAgentBuilder.build()` passes explicit `BuildOptions` to
`ApplicationAssembler.assemble()`. Assembly resolves the package, opens process
services, composes Agent capabilities, creates drivers, validates guarantees,
then starts the dispatcher and returns `SAgentApplication`. The Builder rolls
back acquired scopes if construction fails. The identity algorithm and plugin
scope IDs are preserved so existing admitted Runs remain recoverable.

## Host-admitted Run

Both hosts call `application.compose_run(compose)`. The callback resolves and
wires its host-specific inputs and registers newly owned resources with the
provided `RunResources`. Composition itself neither admits nor executes a Run.
The result contains `value` (the host's assembled driver/value) and `resources`.
The caller must close those resources when its execution boundary settles.

Desktop uses `materialize_agent()` for scoped capability selection and keeps its
sandbox lifecycle adapter. Server builds a package application using
`with_shared_runtime(process_application)` to borrow the same process services.
These adapters deliberately remain separate: desktop approvals and server
identity/catalog policies are not interchangeable.

## Ownership rules

- An injected resource is borrowed unless ownership is explicitly transferred.
- `resources.own(service)` registers a Run service.
- `resources.own(sandbox, dependency=True)` registers its execution dependency.
- Normal close attempts services in reverse order and keeps dependencies alive
  if any service failed to close. Retrying closes only pending resources.
- Composition failure attempts all acquired resources, retains the original
  exception, and leaves failed cleanup with the application for shutdown retry.
- Application close waits for admitted assembly operations to settle. It does
  not take ownership of successful Run assemblies from the host.
- Application scope handles are registered through `retain_scope()`, not by
  mutating another object's private list.
- Durable suspension/release/reconciliation remains in
  `runtime/execution/lifecycle.py`; resource close is not a replacement for it.

Plugins implement their own behavior and may duplicate code. They must not
import sibling implementations. Shared selection here belongs to the host
composition infrastructure, not to an implementation base class for plugins.

## Custom loop hosts

All hosts use `AgentCompositionFactory.create_loop()`. Explicit parameters
select context provider order, developer instructions, budget Agent, completion
gates and automatic memory recall. Defaults retain the standard package behavior.
Desktop supplies the root Agent ID for member budgets and its existing prompt
order/gates. Hosts no longer need separate engine/context wiring for these choices.

`build(package, runtime=...)` applies the same RuntimeConfig before resolution;
it replaces package runtime, never mutates an already resolved identity.
Register plugins before building. `application.process_provider()` uses the same
ExtensionHost validation and application-owned lifecycle for host providers.

`AgentComponents` replaces positional component tuples in initial assembly.
Its opener is injected by the application and registers resources before they
are used. `BoundToolComposer` consumes an already validated binding and explicit
service ports; both root and child drivers use it. Drivers remain responsible
for acquisition and rollback, so composition does not retry external effects.
