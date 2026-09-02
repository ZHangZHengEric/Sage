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

The public entry point is:

```python
from sagents.v2 import SAgentApplication, SAgentBuilder
```

`SAgentBuilder` reads the package, resolves its plugins once, and builds a fully
injected runtime.

### 1. Define a small Agent package

```yaml
# sage.yaml
schema_version: sage/v2
kind: application

metadata:
  id: com.example.assistant
  version: 1.0.0
  name: Example Assistant

credentials:
  model-key:
    source: env
    key: MODEL_API_KEY

models:
  primary:
    provider: openai-responses
    base_url: https://api.openai.com/v1
    credential: model-key
    model: your-model

agents:
  main:
    name: Main Assistant
    instructions:
      inline: Be helpful, concise, and explicit about uncertainty.
    models:
      primary: primary

entrypoint:
  agent: main
```

This example intentionally has no tools. Official file and shell tools require
the host to provide an `OfficialToolRuntime` backed by an explicit sandbox.

### 2. Build and run it

```python
import asyncio

from sagents.v2 import ActorRef, RequestContext, SAgentBuilder, StartRun
from sagents.v2.contracts.commands import InputItem
from sagents.v2.contracts.items import TextBlock
from sagents.v2.contracts.principals import PrincipalType


async def main() -> None:
    application = await (
        SAgentBuilder()
        .with_defaults(session_root="runtime")
        .build("sage.yaml")
    )
    agent = application.entrypoint()

    context = RequestContext(
        actor=ActorRef(
            principal_id="user-1",
            principal_type=PrincipalType.USER,
        )
    )
    command = StartRun(
        agent_id="main",
        input=(
            InputItem(
                role="user",
                content=(TextBlock(text="Explain this repository."),),
            ),
        ),
        resolved_spec_hash=application.composition_hash,
        idempotency_key="request-1",
    )

    stream = await agent.run_stream(command, context)
    async for event in stream.events:
        print(event.type)

    result = await stream.wait()
    print(result.state)
    await application.close()


asyncio.run(main())
```

In a real host, use a unique idempotency key for each logical request and reuse
the same key only when retrying that exact request.

## Main capabilities

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

### Memory

Long-term Memory is separate from Session storage. It is enabled for an Agent
only when that Agent has the `search_memory` tool. Automatic recall and write
behavior is configured per Agent; provider selection is configured by the
runtime.

Session Memory is also separate: it retrieves relevant history omitted from
the current model request. Neither memory system is required for normal Session
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
or `aiomysql`). It also reuses the coordinator, upserts compact Session
metadata, and appends Run events. `dsn` must be a `mysql://` URL that includes
a database; tables use the same `sagent_` prefix. Optional `table_prefix`
isolates a second store in a shared database. A process-held `GET_LOCK`
rejects a second writer (`multi_process_writes: False`). Subscribers stay
in-process. There is no global Session index.

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
