# SAgents V2 architecture and dependency rules

SAgents V2 is organized as domain modules around a small extension kernel. The
public composition root is `SAgentBuilder`; callers normally use only exports
from `sagents.v2`. Host-facing capability selection is documented in
[`使用手册.md`](使用手册.md).

This document describes both the enforced architecture and the remaining
composition debt. A capability appearing in the extension registry does not by
itself mean that every host selects that capability through the same path.

## Architectural intent

V2 follows four rules:

1. Canonical runtime semantics remain in a small, provider-neutral core.
2. Replaceable behavior is exposed through a domain-owned port.
3. Concrete implementations are selected only by a composition root.
4. Product concerns stay in the embedding host and consume public V2 contracts.

The goal is not to make every class a plugin. Commands, event schemas, legal Run
transitions, CAS/idempotency rules, and tool-call ordering are framework
invariants. Model backends, persistence, policies, infrastructure, and protocol
projections are replaceable implementations.

## Source dependency boundary

`sagents.v2` requires Python 3.12 or newer. The legacy Sage runtime remains
Python 3.10+.

Production code under `sagents/v2/` may import only:

- another module under `sagents.v2`;
- the Python standard library;
- an explicitly declared third-party protocol or SDK dependency.

It must not import the legacy `sagents` runtime or application-owned packages
such as `common`, `app`, `mcp_servers`, `agents`, or `skills`. Integrations with
those applications happen through public V2 contracts and injected providers.
The source-boundary test parses every V2 module, including literal dynamic
imports, so deleting the legacy implementation cannot break V2 imports.

Dependencies point inward:

```text
product host
    -> public facade / builder / package manifest
        -> orchestration and policies
            -> domain ports and canonical contracts
                <- provider plugins

protocol adapters -> canonical RuntimeEvents
diagnostics       -> acknowledged requests/events, never runtime authority
```

Domain contracts must not import their provider implementations. Provider
plugins may depend on their own domain contracts and external SDKs, but not on
Desktop/server code.

## Module ownership

| Module | Owns | Replaceable boundary |
|---|---|---|
| `contracts/` | Commands, events, items, Run/Session state | Versioned native models |
| `runtime/kernel.py` | Legal lifecycle commands and state transitions | `SessionStore`, `JobRuntime` |
| `runtime/session/` | One known Session, Runs, journal, CAS, resume | Session storage provider |
| `agent/` | Model/tool loop, safe points, delegation, policies | Injected policies and domain ports |
| `context/` | Canonical request projection, budgets, reduction, summaries | One file per estimator/store/summarizer/reducer in `context/plugins/` |
| `model/` | Model request/stream contract | Model provider |
| `tool/` | Catalog, executor, selection and authorization | One file per selection policy and Tool provider in `tool/plugins/`; official implementations in `tool/official/` |
| `skill/` | Catalog, lazy source, verification, activation | Skill provider |
| `memory/` | Long-term recall/write coordination | One file per recall-query/provider plugin in `memory/plugins/` |
| `session_memory/` | Retrieval over omitted Session history | Session-memory provider |
| `goal/`, `plan/` | Typed goal/plan state and completion gates | State providers and policies |
| `flow/` | Graph execution over the same Run lifecycle | Flow-node provider |
| `runtime/execution/` | Jobs, scheduling, bindings, workspace and sandbox | Backends in `scheduler/plugins/`, `sandbox/plugins/`, `jobs/plugins/` |
| `runtime/observability/` | Non-authoritative diagnostics and traces | One file per sink in `observability/plugins/` |
| `runtime/extensions/` | Registration, resolution, scopes and lifecycle | Extension microkernel only |
| `package/` | Manifest validation, policy ceilings and resolved composition input | Package source/registry |
| `interfaces/protocols/` | Native, AG-UI, ACP, MCP and A2A projections | Protocol adapter |
| `testing/` | Scripted providers and conformance harnesses | Test-only implementations |

`runtime/extensions/` never contains a domain implementation. For example,
OpenAI Responses belongs in `model/plugins/`, while its
`ExtensionRegistration` is exposed to the extension registry.

## Semantic core, plugins, and host bridges

| Layer | Examples | Rule |
|---|---|---|
| Semantic core | Run state machine, canonical events, CAS, idempotency, tool proposal before dispatch | Not replaceable; changes require contract/version review |
| Domain policy | continuation, tool selection, context reduction, summarization | Replaceable behind a typed domain port |
| Infrastructure | SessionStore, Scheduler, JobRuntime, sandbox, artifacts | Replaceable; capability declarations must state durability/isolation truthfully |
| Provider adapter | OpenAI Responses, Anthropic Messages, OpenAI-compatible chat | Owns wire conversion and provider-native continuation state |
| Protocol adapter | Native, AG-UI, ACP, MCP, A2A | Projects canonical events; cannot mutate runtime truth |
| Host bridge | credentials, Run execution bindings, product Session index | Injected by Desktop/server; never imported by the core |

A component should become a plugin only when there is a stable port, at least
two meaningful implementations or a host-owned implementation, explicit
lifecycle/configuration, and conformance tests. Small internal strategies do not
need plugin registration merely to avoid a direct import.

## Extension composition

The implemented extension lifecycle is:

```text
ExtensionRegistration
  -> ExtensionRegistry
  -> ExtensionResolver (capability + API version + dependencies)
  -> ExtensionCompositionPlan (configuration + scope + composition hash)
  -> ExtensionHost.open_scope(...)
  -> immutable ProviderSet
  -> injected domain service
```

Supported lifetimes are `process -> tenant -> agent -> run`. A longer-lived
plugin cannot depend on a shorter-lived plugin. Startup follows the resolved
dependency order; failure and shutdown stop instances in reverse order.

`builder.register(registration)` makes an implementation available. Installed
entry points may be explicitly loaded and then registered by the host;
`sage.yaml.plugins` supplies declarations and version/configuration constraints.
`runtime.capabilities` selects registered implementations. It must not be treated as an
instruction to install packages or as proof that a selected capability is wired
into the standard composition root.

Tool catalog and executor are a paired capability from the same extension
scope. A host must never combine a schema catalog from one plugin with an
executor from another plugin unless an explicit adapter owns that mapping.

Host-owned objects use the same registration factory contract with explicit
borrowed ownership. Runtime parameters remain serializable. There is no parallel
object-injection or host-defined execution-driver entry point.

## Composition roots

`SAgentBuilder` validates registrations and selections, owns provider lifetimes
and rollback, and constructs `SAgentApplication`. `AgentCompositionFactory` receives
already-resolved ports and wires an Agent loop without discovering plugins.
`SAgent`, `AgentLoopEngine`, and `HarnessRuntime` must never consult a global
registry at execution time.

The host executes `build(runtime=..., models=...)`, `load_agent(package,
subagents=...)`, and `entrypoint().run_stream(command, context, agent=loaded)`.
The SDK assembles Agent loops, official tools, context, Team execution and
Run-owned sandbox leases. Hosts do not construct or replace those components.
Process-local services come from registration factories and declared dependencies.

`LoadedAgent.resolved_plan` identifies the selected capability providers, scopes,
API versions, dependency edges, implementation versions and composition hash.
`app.run_configuration(run_id, context)` exposes the authorized Run's original
Agent and runtime selection; `execution_configuration` and `execution_diagnostics`
expose its accepted policy and actual sandbox capabilities. New App settings do
not replace an admitted Run's configuration, including after restart.

## Provider boundary

Canonical Session history and provider wire state are different concerns:

- canonical Items are portable runtime history;
- provider-native continuation items are opaque, provider-scoped execution
  state needed to continue some reasoning/tool turns correctly;
- visible reasoning summaries are diagnostics/UI content, not a substitute for
  encrypted reasoning items or signed thinking blocks.

The model port must transport provider-native replay state without teaching the
Agent loop OpenAI-, Anthropic-, or vendor-specific fields. A provider adapter
captures, validates, persists through the active Run checkpoint, and replays its
own versioned envelope. Changing provider/protocol must explicitly reject or
discard incompatible replay state at a safe boundary; silent loss is invalid.

The current `ModelMessage`/`ModelResponse` path carries a bounded, JSON-safe,
protocol-namespaced, versioned `provider_state`. OpenAI Responses reasoning items,
Anthropic thinking/signature blocks, and OpenAI-compatible reasoning details
are captured by their adapters, attached to the assistant Item, reconstructed
from Session history, and replayed only by the matching adapter.

Each newly captured namespace uses `schema_version=1` and an 8 MiB encoded
limit. Legacy v0 Session rows remain readable; a matching adapter rejects an
unknown envelope version, while a different protocol ignores state outside its
namespace. Provider-native state is never guessed or converted across protocols.
A host must freeze the selected model route and Agent runtime definition for the
lifetime of a Run (including recovery), or fail closed when it cannot recreate
that composition; provider and Agent configuration changes apply only to new
Runs. Credentials and explicit monotonic authorization updates may be resolved
from current host state and must never be embedded in the snapshot. Live provider
and crash/recovery tests remain required in addition to payload golden tests.

## Context boundary

Context reduction operates on canonical conversation units. Local input-token
estimators, calibration and preflight token gates have been removed. A configured
input ceiling remains a trigger: after reported provider input usage reaches the
ceiling minus explicit output/input reserves, the next projection compresses
history. Cached input is a subset of input usage, never added twice. An API
`model.context_window_exceeded` rejection also triggers compression immediately,
including structured errors inside an HTTP 200 stream. Without a counting API,
a new input's exact token size is only known after provider feedback.

The main loop permits at most six compression retries per uncommitted step.
Compression preserves the exact latest real user request and processes complete
Tool batches, including parallel results and attached media. Large completed
current-turn batches can be summarized atomically. Durable references are used
only when supplied by the Tool. No canonical messages or successful Tool receipts
are removed or replayed. An unchanged rejected projection stops recovery.

Summary requests first send their complete source, including the previous
checkpoint. Only API overflow splits the source into two halves. Both halves
must succeed before their structured summaries are merged without discarding fields or identifiers.
Completed API output is never locally clipped to a guessed token envelope. Model
calls, output-format retries and transient retries share a 64-call operation
quota; splitting has a depth ceiling of 12. Empty or expanding summaries fail
without advancing coverage. Checkpoints commit only after the full selected
canonical prefix has been summarized, with digest validation and revision CAS.
Completion-Judge rules and its JSON output contract remain in a protected
system message, separate from compressible execution evidence.
Auxiliary selection, memory query and completion-judge requests use the same
bounded API-feedback recovery and buffer intermediate responses.

Mandatory instructions and a single irreducible current user input cannot be
compressed safely. Recovery stops with an explicit resumable error and preserves
the full ledger. Proactive reported-usage pressure alone never fails an otherwise
usable request when no reducible content remains.

Transient model failures get up to three transparent retries with exponential
backoff (1, 2, 4 seconds), without consuming another successful Agent step.
Interrupted streams cancel their partial Items before retrying; cancelled output
never enters canonical model history. Only the uncommitted model request is
replayed: completed Tool calls and their results remain authoritative. Summary
model calls also retry temporary provider failures, preserving saved summary
checkpoints. Authentication/configuration errors and uncertain Tool side effects
continue through typed recovery rather than blindly repeating execution.

## Runtime and persistence boundaries

`runtime/kernel.py` depends on `SessionStore` contracts and requires the
selected store at construction. Shared transactional semantics live in
`runtime/session/state.py`; file and ephemeral backends adapt that state core.

Execution domains consume `runtime/contracts.py::RuntimePort`; only composition
code constructs `HarnessRuntime`. This keeps Agent and Flow orchestration from
depending on one in-process lifecycle implementation.

Durable Session state does not imply durable execution. The default Scheduler,
JobRuntime and package registry are single-process/ephemeral reference
implementations. The standard runtime preset stores ArtifactStore binary
snapshots under its state root's `artifacts` directory; hosts without a
storage root may explicitly use the ephemeral store. The filesystem store supports
processes sharing one local directory, not independent hosts. `analyze_image` reads through
the sandbox, normalizes once, and stores an immutable content-addressed snapshot.
The ledger carries `sage-image:<sha256>` and only inference projections contain
base64. Tenant-scoped stores isolate references; missing or corrupt attachments
fail explicitly. Source file edits, deletion, and sandbox release do not change
the snapshot. Remote image URLs and legacy inline messages retain their existing
behavior. The optional filesystem Scheduler persists pending
work, leases, and fencing counters for single-host restart recovery. Dispatcher
recovery executes only queued/resuming work; an uncheckpointed running Run is
failed as `execution.worker_restarted` instead of being replayed. This is not a
distributed lease provider or a durable JobRuntime. Capability flags must fail
closed when a requested durability or isolation guarantee is unavailable.

The framework does not implement or require a particular database transaction.
It requires the selected Scheduler plugin to expose
`supports_atomic_fenced_mutations` and `execute_fenced(lease, operation)`. The
plugin must keep that lease authoritative until the supplied Session mutation
finishes. The in-process providers do this with their scheduler lock; a future
distributed provider may use a database transaction, row/advisory lock, or any
other linearizable mechanism. Builder composition fails closed when this
semantic capability is absent. `supports_distributed_claims` remains a separate
capability and is false for the built-in schedulers.

Model reads poll durable pause/cancel state and deadline without repeatedly
cancelling the provider socket. Tool cancellation is an optional port and is
used only when both the Tool definition declares cooperative/forceable
semantics and the selected Executor implements it. Confirmed cancellation,
too-late completion, and unknown outcomes remain distinct; non-cancellable
Tools settle before a requested pause is checkpointed, and terminal Runs never
publish late results.

## Single-Session authority

The framework has no concept of “all Sessions”. `SessionStore` can create or
open one known `session_id`, manipulate its Runs, and recover that Session. It
has no list/search/page/title/archive/favorite API.

`SessionStore` is a trusted internal persistence port. Server transports must
use the `session.access` service (`AuthorizedSessionAccess`) for reads,
subscriptions, checkpoints, interactions, and deletion. That facade requires a
`RequestContext` and verifies the durable Session owner before returning data.

Reference runtime metadata has explicit retention boundaries. Scheduler
terminal idempotency tombstones are count-bounded by
`max_retained_terminal_items`, while fencing uses one persisted monotonic
sequence instead of one counter per Run. Job and sandbox plugins expose
incremental TTL/count/byte retention plus explicit
`purge_terminal`/`purge_terminated`. Fresh Job output, suspended checkpoints,
and attached sandboxes are protected from automatic reclamation.

`FilesystemSessionStore` (in `runtime/session/plugins/`) does not materialize
every Session on startup. A known
`session_id` maps directly to one directory. Product software such as Desktop
owns any global index. A commit exports only that Session aggregate; it no
longer serializes all loaded Sessions before filtering. The reference
coordinator uses a small topology lock for immutable Run/Session relationships
and a sorted per-Session lock table. Different Session writes may persist in
parallel, one Session remains strictly serialized, tree deletion revalidates
its locked topology, and failed persistence restores only the target aggregate.

Optional SQL backends live in `runtime/session/plugins/`, matching other
replaceable providers. `sage.session.postgres` follows the same
open-by-`session_id` rule and does not `SELECT *` every Session at startup.
Compact metadata and appended Run events live in `sagent_`-prefixed tables. A
process-held advisory lock rejects a second writer. Subscribers stay
in-process. A PostgreSQL store still does not provide a global Session index
or a distributed Scheduler.

`sage.session.mysql` is the same open-by-`session_id` store on InnoDB, with
`sagent_`-prefixed tables, appended Run events, and a process-held `GET_LOCK`.
It does not claim multi-process writes or cross-process subscribe.

## Authoritative versus derived data

```text
Session state/checkpoint -> authoritative lifecycle and canonical history
active provider replay   -> authoritative for exact in-flight continuation
derived/                 -> deletable summaries, token caches, Skill activation
MemoryProvider           -> independent long-term Memory backend
DiagnosticSink           -> optional model-request diagnostics, never recovery input
TraceSink                -> optional Session span tree (root session + forked children), never recovery input
Desktop index            -> product-owned list/search metadata
```

Deleting derived data or diagnostics cannot change Session recovery. Memory
failure cannot roll back an acknowledged Session commit.

Derived per-Session values are reached through `DerivedStateStore`, a port
separate from `SessionStore`. Conversation summaries, Skill activation, and the
dynamic Agent roster depend on that narrow port, so a new authoritative
Run/Event/Checkpoint backend does not have to ship a key-value cache to be a
valid `SessionStore`, and a caller's type states whether its reads are
authoritative. The shipped stores still satisfy both ports with one object and
report `derived_state_authoritative: False`. A custom SessionStore without the
derived-state port requires an explicitly registered and selected
`derived-state.store` implementation; the Builder does not silently substitute
volatile state. Authorized deletion forgets independent derived values only after
the canonical Session tree has been deleted successfully.

## Architecture acceptance gates

A new module or plugin is complete only when:

- its dependency direction passes the source-boundary test;
- the port has conformance tests independent of the built-in implementation;
- capability, API version, scope, configuration, and truthful guarantees are
  declared;
- startup rollback and reverse-order shutdown are tested;
- canonical events and recovery behavior remain provider-independent;
- final provider payload tests cover messages, tool schemas, replay state, and
  cache markers;
- Desktop/server use the same composition path or document an intentional host
  adapter, not a duplicated loop.
