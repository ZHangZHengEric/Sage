# SAgents V2

SAgents V2 is an embeddable runtime for building and running tool-using AI
agents. It provides the execution loop, durable session history, event
streaming, tools, skills, memory, and extension points. A desktop app, server,
or other host supplies the product UI, authentication, model credentials, and
the global list of conversations.

V2 is independent from the legacy SAgents runtime. Importing `sagents.v2` does
not initialize global managers or application services.

**Requires Python 3.12 or newer.** The legacy Sage runtime stays on Python
3.10+. Importing `sagents.v2` on an older interpreter raises immediately.

## Start with this mental model

| Concept | Meaning |
| --- | --- |
| **Agent package** | A `sage.yaml` file that selects instructions, models, tools, skills, and limits. |
| **Session** | The durable conversation and concurrency boundary. It owns canonical history. |
| **Run** | One execution attempt inside a Session. A Session may contain multiple Runs. |
| **Turn / Step** | A Turn handles user input; a Step is one model request followed by any tool work. |
| **Runtime event** | The typed stream used by hosts to render progress, messages, tools, suspension, and completion. |

SAgents manages one known Session at a time. Listing, searching, naming,
archiving, and paging all Sessions belongs to the embedding application.

## What happens during a Run

```text
StartRun
  -> accept the Run in the Session store
  -> assemble model context from canonical history
  -> stream a model response
  -> authorize and execute requested tools
  -> repeat Steps when needed
  -> commit completion, failure, or suspension
  -> publish acknowledged runtime events to observers
```

The most important behavior is:

- Session history is authoritative; model requests are temporary projections.
- Closing an event stream detaches that observer but does not cancel the Run.
- A suspended Run can be resumed. Suspension is not a terminal state.
- Tools and plugins are selected explicitly; the runtime does not silently
  substitute another implementation.
- Memory, summaries, caches, and diagnostics are derived data. Their failure
  cannot rewrite an acknowledged Session commit.

## Quick start

**No manifest file is required.** Parse YAML text with `SageManifestLoader.loads()` and pass the resulting `SageManifest` to `build()`:

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
credentials:
  api-key: {source: env, key: MODEL_API_KEY}
models:
  primary:
    provider: openai-responses
    base_url: https://api.openai.com/v1
    credential: api-key
    model: your-model
agents:
  main:
    name: Assistant
    instructions: {inline: "Be helpful and concise."}
    models: {primary: primary}
entrypoint: {agent: main}
"""


async def main():
    manifest = SageManifestLoader().loads(AGENT_YAML)
    app = await SAgentBuilder().with_defaults(session_root="runtime").build(manifest)
    try:
        context = RequestContext(actor=ActorRef(
            principal_id="user-1", principal_type=PrincipalType.USER,
        ))
        stream = await app.entrypoint().run_stream(StartRun(
            agent_id="main",
            input=(InputItem(role="user", content=(TextBlock(text="Say hello!"),)),),
            resolved_spec_hash=app.composition_hash,
            idempotency_key=str(uuid4()),
        ), context)
        async for event in stream.events:
            print(event.model_dump_json())
        print((await stream.wait()).state)
    finally:
        await app.close()


if __name__ == "__main__":
    asyncio.run(main())
```

After installing the checkout with `python -m pip install -e .`, replace
`your-model`, set `MODEL_API_KEY`, and run the script with Python 3.12+.
The checked-in example runs as `python -m examples.sagents_v2_quickstart`.
It prints events and the final state, and saves Session data under `runtime/`.
It does not enable file or shell tools; those require explicit host resource bindings.

| Configuration input | Builder usage |
| --- | --- |
| YAML text | `build(SageManifestLoader().loads(yaml_text))` |
| Python dictionary | `build(SageManifest.model_validate(config_dict))` |
| File | `build("path/to/sage.yaml")` |
| Resolved package | `build(resolved_manifest)` |

Import `SageManifest` and `SageManifestLoader` from `sagents.v2.package.manifest`.
A raw string passed to `build()` is a path, not YAML content. Use inline instructions
for string manifests; `load()` resolves instruction files inside a package directory.
Use a unique idempotency key for each logical request, reusing it only for a retry
of the same request. Always close the application when the host is done.

[Full setup guide](../../docs/en/applications/GETTING_STARTED.md) ·
[Executable example](../../examples/sagents_v2_quickstart.py)

## Main capabilities

### Agents that create agents

`AgentManagementService` persists full `SageManifest` bundles, validates their
composition, and runs any selected agent through ordinary Native Sessions and
Runs. Hosts inject it with `SAgentBuilder.with_agent_management(service)` and
explicitly grant the `agent_package_*` tools in each agent's tool list. Created
agents may receive the same tools to create further agents. This is separate
from the lightweight Fibre spawn/leaf-delegation contract.

The service requires a host-owned authorizer and fresh-Builder factory. It
supports immutable versions, forks, CAS activation/rollback, scoped inventory,
idempotent invocation, multi-turn continuation, status, question replies and
cancellation. Activation is not a quality evaluation. Plugin source installation
and automatic self-improvement evaluations are not performed by this service.

Builder also binds declared Agent Flow entrypoints, `flow.node` plugins and
explicit `with_flow_tool_nodes()` implementations. `with_skill_provider()` wires
standard Skill ports into lazy loading and active-skill context. Unsupported
loop implementations and unbound Flow nodes fail explicitly.

See the [implementation and host integration guide](../../docs/zh/architecture/SAGENTS_V2_AGENT_MANAGEMENT.md)
and the [offline executable example](../../examples/sagents_v2_agent_management.py).

### Models

Built-in protocols cover OpenAI Responses, OpenAI-compatible Chat
Completions, and Anthropic Messages. A model route in `sage.yaml` chooses the
protocol, endpoint, model, capabilities, and credential reference. Secrets are
resolved by the host and are not stored in the package.

Provider-native continuation data is kept in a JSON-safe, protocol-namespaced
`provider_state` on assistant Items. The matching adapter replays OpenAI
reasoning items, Anthropic thinking/signature blocks, or compatible-provider
reasoning details after Tool calls without exposing them as user-visible text.
The envelope is intentionally opaque to the Agent loop. New state uses a
versioned protocol namespace and a bounded JSON contract; legacy unversioned
state remains replayable by the matching adapter. Unknown versions fail closed,
and another protocol never consumes a foreign namespace.

### Tools and skills

A tool provider exposes two paired interfaces: a catalog for model-visible
schemas and an executor for calls. Policy is applied before tools reach the
model. Large catalogs can use a selection policy so each request sees only a
small relevant subset.

Skills are loaded lazily from a skill provider. Official filesystem, shell,
network, and media tools execute only through host-provided sandbox interfaces;
they do not fall back to unrestricted process or filesystem access.

### Context and history

The Context assembler converts canonical Session history into a provider
request. A reducer may remove old conversation units or replace a verified
prefix with a summary to fit the model window. This never deletes the original
Session history.

Tool schemas, hidden-tool indexes, continuation guidance, and fixed provider
overhead are non-compressible request reservations. Reducers see only canonical
compressible context; after reduction, the runtime appends reserved content and
validates the final request size. Summary output must be smaller than the exact
compressible source it replaces.

Oversized indivisible Tool units use the `context.unit-compactor` port. The
built-in implementation accepts only a durable `context_reference` supplied by
the Tool and persisted in Session history; no reference means no truncation.

The standard Builder uses a finite 32,768-token fallback when no model window
is declared. System instructions, current-turn protection, historical summary
work, and auxiliary concurrency have separate bounds. See the
[context budget and concurrency guide](../../docs/zh/architecture/sagents-v2-context-budget.md)
for configuration, overflow behavior, and reproducible benchmarks.
The [single-host concurrency guide](../../docs/zh/architecture/sagents-v2-single-host-concurrency.md)
describes per-Run mutation fencing, Server concurrency settings, and benchmarks.

### Memory

Long-term Memory is separate from Session storage. It is enabled for an Agent
only when that Agent has the `search_memory` tool. Automatic recall and write
behavior is configured per Agent; provider selection is configured by the
runtime.

Session Memory is also separate: it retrieves relevant history omitted from
the current model request. Its index consumes only the appended suffix of each
observed Run ledger; recall does not rebuild Session history or resynchronize
the indexed prefix. Neither memory system is required for normal Session
continuity.

### Execution modes

`StartRun.invocation_mode` supports three host-selected modes:

- `normal`: ordinary agent execution.
- `plan`: inspection-oriented work that must submit a plan for approval.
- `goal`: persistent goal execution that must explicitly report completion.

Mode selection is a typed command field, not text parsed from the user's
message.

### Multi-Agent and Flow

Simple, Fibre, and Team are presets over the same Agent loop. Delegation creates
child Runs or forked Sessions; it is not a second execution engine. Flows use
the same lifecycle and event contracts through a graph-oriented driver.

Fibre and Team may use the same configured roster of existing Agents. Fibre
also exposes `sys_spawn_agent`; spawned descriptors are scoped to the current
Session, rebuilt from canonical Tool-result events on later Runs, and never
added to the host's persistent Agent catalog. Workspace sharing is an explicit
policy and is not inferred from the Agent mode.

## Persistence and hosting

`runtime.deployment_profile` defaults to `controlled_host`. Selecting
`distributed` is an executable admission policy, not a label: Builder requires
multi-process Session writes and subscriptions, a transactional outbox,
distributed Scheduler claims with atomic fencing, a restart-durable JobRuntime,
a Tool executor with a durable operation ledger and restart reconciliation, and
durable Artifact and Package stores. The built-in local providers do not satisfy
that profile; distributed Artifact/Package stores must also be shared across
processes, and the Package registry must verify signatures. A distributed manifest
therefore fails during composition until the host supplies server-grade plugins.

`controlled_host` does not mean single-conversation. One long-lived
`SAgentApplication` runs many Sessions and Runs asynchronously through a bounded
worker pool; `execution.scheduler.config.max_concurrent_runs` and
`max_concurrent_runs_per_tenant` provide process-wide and tenant quotas. Sandbox
isolation is an independent Host concern and is not required merely to serve
concurrent conversations. Reuse the Application instead of building one per
request.

Extension scope controls lifetime and ownership, not serialization. Process-,
tenant-, and agent-scoped providers can receive overlapping calls from many Runs;
plugins must keep shared state concurrency-safe and avoid holding locks across
model, network, subprocess, or other upstream I/O. A provider that cannot do so
must use Run scope.

`runtime.plugin_trust_policy` defaults to `trusted_declared`, which means the
host accepts responsibility for every explicitly declared Python plugin.
`built_in_only` rejects non-built-in extensions before an installed entry point
is imported and also rejects pre-registered external providers during planning.
Built-in trust comes from the Host's official registry provenance; an extension
cannot become trusted by setting `descriptor.built_in` itself. This is a code
admission boundary, not a configuration sandbox: hosts must still treat plugin
configuration such as MCP stdio commands and remote endpoints as privileged.

The default `FilesystemSessionStore` v4 keeps each Session under the configured
runtime root. Its typed, checksummed aggregate plus discriminated mutation
journal are authoritative; readable event, run, checkpoint, and derived files
are projections that can be regenerated. Older stores are never changed during
startup; migrate explicitly with `sage v2 migrate --runtime-root <path>`.

`sage.session.postgres` is an optional durable plugin (`pip install sage[postgres]`
or `asyncpg`). It reuses the same coordinator semantics, upserts compact Session
metadata, and appends Run events. `dsn` must be declared on the plugin
selection in `sage.yaml` (optional `schema_name` is allowed). Tables use the
`sagent_` prefix (`sagent_sessions`, `sagent_run_events`, …). The runtime does
not read a DSN environment variable. A process-held advisory lock rejects a
second writer (`multi_process_writes: False`). Subscribers stay in-process.
There is still no global Session index, and a PG store does not make the
Scheduler multi-host. Hosts that already own a connection string may also
inject `PostgresSessionStore(dsn=...)` through
`SAgentBuilder.with_session_store(...)`.

`sage.session.mysql` is a second optional durable plugin (`pip install sage[mysql]`
or `aiomysql`). It reuses the coordinator, appends Run events and Session
mutations, and periodically compacts them into a Session snapshot. Location and
start-idempotency indexes write only changed rows. `dsn` must be a `mysql://`
URL that includes a database; tables use the same `sagent_` prefix. Optional
`table_prefix` isolates a second store in a shared database. Reads and writes
borrow connections from one pool with no client-side size cap or reserved
writer connection. Concurrent sessions can commit independently. A Session
revision check rejects conflicting writes, but cross-process cache and
subscriptions are not synchronized (`multi_process_writes: False`). There is
no global Session index.

For MySQL, model text deltas are live-only stream previews. They carry a
`preview_sequence` and `preview_epoch` alongside the last canonical
`run_sequence`. The process retains all previews for unfinished Items so a
subscriber can replay every model delta during the active step. An Item's
previews are released when its durable completion is committed; terminal Run
events release any remaining previews. Completed messages, tool boundaries,
suspensions, and terminal states remain durable. After a process restart, an
unfinished preview may be lost; the next durable event still resumes from the
unchanged canonical Run cursor.

`SAgentApplication` is the application-level ownership boundary. It exposes
logical Agents and typed services while owning extension scopes, Scheduler,
workers, stores, diagnostics, and protocol adapters until `close()`.
Its immutable `resolved_plan` reports the final capability bindings, plugin or
host source, scopes, API versions, dependency edges, and composition hash
without exposing raw configuration or credentials.

The optional filesystem Scheduler persists pending work, leases, and fencing
counters for single-host restart recovery. Queued work can be redispatched;
uncheckpointed running work fails explicitly instead of being replayed. This
does not claim a distributed scheduler or a durable JobRuntime.

Worker fencing is a semantic plugin contract rather than a built-in database
transaction. A Scheduler used by `SAgentBuilder` must support
`execute_fenced(lease, operation)`, keeping the validated lease authoritative
until the SessionStore mutation completes. In-memory and filesystem schedulers
provide single-process/single-host implementations. A server plugin may use its
own database transaction or distributed lock, and advertises multi-host claim
support independently through `supports_distributed_claims`.

Tenant concurrency is enforced inside the same atomic `claim` through
`SchedulerClaimPolicy.max_active_per_tenant`. The built-in schedulers advertise
`supports_atomic_tenant_quota: true`; Builder rejects a configured tenant limit
when a selected Scheduler cannot enforce it without claim/requeue spinning.

`SessionStore` itself is a trusted internal port. HTTP/RPC/WebSocket adapters
should obtain `application.service("session.access")` and use its
context-bearing read, subscribe, checkpoint, interaction, and delete methods;
they should not expose raw ID-only SessionStore reads to tenants.

The reference Scheduler bounds completed idempotency metadata with
`max_retained_terminal_items` (default `4096`) and persists one global monotonic
fence sequence rather than a map that grows once per Run. In-memory JobRuntime
automatically retains terminal Jobs for 24 hours, at most 4096 Jobs and 256 MiB
of terminal output, while protecting a configurable output reconnect window.
In-memory and local-workspace sandbox providers retain at most 1024 detached
terminal metadata records for 24 hours. Suspended or attached resources are not
swept. Explicit `purge_terminal`/`purge_terminated` methods remain available;
local-workspace retention never deletes host workspace contents.

The in-memory JobRuntime also bounds admitted tasks (running plus queued;
default 1024), output per Job (8 MiB / 8192 chunks), and all buffered output
(256 MiB / 65536 chunks). A full admission or protected-retention budget returns
retryable `job.queue_full`; output overflow sets `JobSnapshot.output_truncated`.
These limits are configurable on `sage.job.ephemeral` and exposed by its
capabilities. They do not bound arbitrary runner allocations or Session history.
SQLite memory I/O retains its lock until cancelled thread work actually ends,
with eight shared thread slots per event loop.

Distributed plugins report `multi_process_writes`, `cross_process_subscribe`,
`transactional_outbox`, and `atomic_session_cas` independently. The built-in
SQL stores remain single-process writers. `sagents.v2.testing` exposes reusable
Scheduler and SessionStore conformance probes for exclusive claims, fencing,
tenant quota, atomic mutation/event visibility, and cursor recovery.

## Extending V2

Replaceable implementations are registered with an
`ExtensionRegistration`. Common extension boundaries include:

- `ModelProvider`
- `SessionStore`
- `MemoryProvider`
- Tool catalog and executor
- Skill provider
- Context reducer or summarizer
- Scheduler, job runtime, sandbox, and protocol adapters
- Diagnostic, log, and trace sinks

Production plugins can be published through the `sage.extensions` Python entry
point group. Direct registration and direct provider injection are useful for
tests or hosts that already own a client connection.

Contracts, legal lifecycle transitions, canonical event ordering, and the
orchestration protocol are framework semantics rather than plugins. Policies
with stable ports, such as continuation, Tool selection, and Context reduction,
may be plugins, but they cannot change those runtime invariants.

The extension kernel supports dependency resolution, API versions,
configuration validation, scoped lifetimes, startup rollback, and reverse-order
shutdown. Generic and Desktop paths use the same Agent composer, and manifest
Context/continuation selections are consumed by the Builder. Internally the
Builder may open multiple lifetime scopes; `resolved_plan` is the single final
composition fact exposed to hosts. See [`ARCHITECTURE.md`](ARCHITECTURE.md) for
the dependency and lifecycle rules.

## Source map

```text
sagents/v2/
├── 使用手册.md            # Chinese capability integration guide
├── sagent.py              # public start, observe, continue facade
├── builder.py             # package resolution and dependency composition
├── contracts/             # commands, events, items, and state models
├── agent/                 # the model/tool loop and execution modes
├── runtime/               # lifecycle kernel, sessions, sandbox, extensions
├── context/               # request assembly, budgets, reduction, summaries
├── model/                 # model contracts and provider implementations
├── tool/                  # tool catalog, execution, policy, built-ins
├── skill/                 # skill discovery and activation
├── memory/                # long-term memory
├── session_memory/        # retrieval over omitted Session history
├── flow/                  # graph execution
├── package/               # sage.yaml models and resolution
├── interfaces/protocols/  # Native, AG-UI, ACP, A2A, and MCP projections
└── testing/               # scripted providers and conformance helpers
```

Recommended reading order:

1. [`使用手册.md`](使用手册.md) — capability selection and configuration (Chinese)
2. `sagent.py`
3. `builder.py`
4. `contracts/commands.py` and `contracts/events.py`
5. `agent/engine.py`
6. `runtime/kernel.py`

For dependency rules and authoritative-data boundaries, read
[`ARCHITECTURE.md`](ARCHITECTURE.md). For behavior examples, the tests under
`tests/sagents/v2/` are the most precise executable documentation.

## Development checks

```bash
pytest tests/sagents/v2
```

When changing a provider or store, also run its domain conformance tests. When
debugging prompts, inspect the final provider request (`messages`, visible
tools, and cache markers) rather than only the canonical Session history.

### Input usage calibration

The default step builder uses reported total input usage (including its cached
subset once) as the next request's baseline within the same Run. When the entire
previous message prefix, resolved configuration, and tool schemas are unchanged,
only appended messages are estimated. The budget also reserves 3% of the reported
baseline, with a minimum of 128 tokens. Each response replaces the baseline, so
this margin does not accumulate. Output usage is not treated as the next input's
message length, and no per-message count is labelled provider-measured.

Calibration applies to built-in reducer budgeting as well as final request
validation. Changed/truncated prefixes, changed images or tools, missing usage,
compatibility fallbacks, and context-overflow retries fall back to the ordinary
estimator. Non-additive custom estimators retain their existing behavior. The
bounded in-memory cache stores fingerprints and counters, not prompt bodies;
a fresh builder or process restart begins with estimation until usage arrives.
Request diagnostics record the accounting method, baseline request, reported
input, estimated delta, and safety margin. Calibration scopes are task-local so
concurrent Runs cannot borrow each other's usage.

Skill loading is selected through `skill.loading`, independently of the Skill
catalog/source and `load_skill` tool providers. The built-in
`sage.skill.loading.lazy` plugin accepts `max_active_tokens` (positive integer,
default `6000`). This bounds the combined active Skill context, not model output.

```yaml
runtime:
  capabilities:
    skill.loading:
      plugin: sage.skill.loading.lazy
      config:
        max_active_tokens: 12000
```

`plugins[].config` supplies plugin defaults; capability selection config overrides
those defaults. Builder and Desktop materialize the selected provider. Direct
`AgentCompositionFactory.create_skill_loader()` callers can use the same manifest
configuration for the built-in implementation, or inject `skill_loading` with a
custom `create_loader(**ports)` implementation.

Desktop v2 exposes this under runtime components. Its shared configuration editor
reads scalar properties (`string`, `integer`, `number`, `boolean`), enum choices, and defaults
from `config_schema`; saving validates the configuration against the plugin schema
on the backend. Host-injected required ports are omitted from settings validation
and validated at plugin instantiation. Complex schemas are not yet editable by
this scalar form. Skill loading changes apply on the next run.

Desktop plugin forms show registered defaults and saved overrides. Enum fields
use selectors and preserve the schema value type. Product-injected fields without
user-facing defaults are hidden; fixed values with defaults are shown read-only
and omitted from submitted overrides. Built-in registrations publish scalar
constructor defaults, with explicit factory defaults taking precedence. Desktop
completion thresholds and model timeouts remain configurable when the selected
implementation uses them; local tool selection does not expose model timeouts.
