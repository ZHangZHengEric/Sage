# SAgents V2 developer guide

SAgents V2 manages one known Session and the Runs inside it. It does not manage
a user's global Session collection. Desktop, a server, or another embedding
application owns listing, search, paging, titles and archival indexes.

## Public entrypoint

```python
from sagents.v2 import SAgent, SAgentBuilder
```

`SAgentBuilder` is the composition root. It resolves configuration once,
selects registered factories, and injects concrete interfaces into the Kernel
and Agent loop. Runtime code has no global service locator and never silently
substitutes another plugin.

## Directory map

```text
sagents/v2/
├── __init__.py                 # stable public exports
├── sagent.py                   # start/continue/stream facade
├── builder.py                  # plugin selection and object graph
├── contracts/                  # canonical command/event/state models
├── runtime/
│   ├── kernel.py               # lifecycle state transitions
│   ├── session/                # SessionStore + file/ephemeral plugins
│   ├── execution/              # scheduler, jobs, sandbox, workspace
│   ├── artifact/               # ArtifactRef and ArtifactStore boundary
│   ├── credentials/            # secret references and resolution
│   ├── extensions/             # registry, resolver, host, scopes
│   └── observability/          # diagnostics that never drive recovery
├── agent/                      # one AgentLoopEngine, presets and delegation
├── model/                      # contract, registry, plugins, middleware
├── context/                    # assembler, sources, reducer, summary
├── memory/                     # backend-neutral long-term Memory contract
├── tool/                       # paired Tool catalog/executor plugins
├── skill/                      # catalog/source/verifier/activation
├── flow/                       # one FlowEngine and node registry
├── package/                    # manifest, resolution and presets
├── interfaces/protocols/       # downstream protocol projections
└── testing/                    # scripted and conformance implementations
```

There is intentionally no `api/`, top-level `plugin/`, `providers/`,
`builtins/`, or `knowledge/` directory.

## Recommended reading order

1. `sagent.py`: what a caller can start, observe and resume.
2. `builder.py`: how a complete Agent is assembled.
3. `contracts/`: stable commands, events and state snapshots.
4. `runtime/kernel.py`: lifecycle transitions exposed to drivers.
5. `runtime/session/`: the authoritative single-Session boundary.
6. `agent/engine.py`: the only model/tool execution loop.
7. `context/`: how canonical history becomes a provider request.
8. `model/`, `tool/`, `skill/`, `memory/`: replaceable domains.
9. `runtime/extensions/`: factory resolution and scoped lifecycle.
10. `package/`: authoring manifests and resolved policy ceilings.

When debugging a prompt, follow it through the selected model plugin and inspect
the final `messages + tools + cache markers` payload. Golden tests lock system
and user content, message order, compression semantics and provider cache marks.

## Lifecycle

```text
StartRun
  -> SessionStore atomically accepts Session/Run/input events
  -> SAgent starts one RunDriver
  -> AgentLoopEngine starts Turn/Step
  -> ContextAssembler reads canonical history + ephemeral sources
  -> ModelProvider streams Items
  -> Tool policy authorizes Catalog/Executor calls
  -> SessionStore commits checkpoint, suspension or terminal state
  -> subscribers observe only acknowledged commits
  -> optional Memory ingestion runs after canonical publication
```

Simple, Fibre and Team are presets over the same `AgentLoopEngine`. Team work is
delegation tooling, child Runs and forked Sessions, not a second loop engine.

Session is the canonical history and concurrency boundary. Run is one execution
attempt with its own state, checkpoint and cursor. A closed stream does not
cancel a Run. A suspended Run is resumable, not terminal. A fork stores an
immutable parent-history base in the child journal, so deleting the parent does
not break the child. `parent_session_id` is lineage, not a foreign key.

## FilesystemSessionStore

```text
<root>/
├── store.json
├── .writer.lock
├── idempotency/start/
├── transactions/
├── trash/
└── sessions/<encoded-session-id>/
    ├── journal.jsonl
    ├── derived/<namespace>/<key>.json
    └── lock
```

`journal.jsonl` is the only authoritative Session source. Each envelope has a
transaction ID, previous/current revision, full single-Session state and a
checksum. Appends are flushed and fsynced before events are published. An
incomplete final line is ignored; a bad checksum or discontinuous middle
revision is a typed corruption error.

There is no global catalog file or `list_sessions()` method. The
`idempotency/start` directory is only an exact-retry lookup when the first
StartRun did not have a Session ID. Journal data remains authoritative and can
rebuild this lookup.

## Extensions

An extension is a descriptor coupled to an executable factory. The registry
rejects duplicate IDs. The resolver validates API versions, selections,
dependencies and cycles. The host creates process/tenant/agent/run instances,
starts dependencies first, stops them in reverse order, and rolls back partial
startup failures.

Domain facades are `SessionStoreRegistry`, `ModelProviderRegistry`,
`MemoryProviderRegistry`, `ToolProviderRegistry`, `SkillProviderRegistry` and
`FlowNodeRegistry`. Inventory comes only from real registrations.

All host-selectable first-party implementations use this same registry. The
current inventory is grouped below; the registry remains the authoritative
machine-readable source.

- Session: `sage.session.filesystem`, `sage.session.ephemeral`.
- Memory: `sage.memory.filesystem-bm25`, `sage.memory.noop`.
- Model: `sage.model.openai-responses`,
  `sage.model.openai-chat-completions`, `sage.model.anthropic-messages`.
- Tool: `sage.tool.official`, `sage.tool.skill`,
  `sage.tool.multi-agent`, `sage.tool.mcp`.
- Context reducers: `sage.context.reducer.window`,
  `sage.context.reducer.persistent-summary`.
- Context summarizers: `sage.context.summarizer.extractive`,
  `sage.context.summarizer.model`.
- Context summary state: `sage.context.summary-store.ephemeral`,
  `sage.context.summary-store.session-derived`.
- Token estimation: `sage.context.token-estimator.json-heuristic`,
  `sage.context.token-estimator.unicode-heuristic`,
  `sage.context.token-estimator.tiktoken`.
- Execution: `sage.scheduler.ephemeral`, `sage.job.ephemeral`,
  `sage.sandbox.ephemeral`, `sage.sandbox.local-workspace`.
- Skill and Flow: `sage.skill.filesystem`, `sage.flow.agent`.
- Credentials: `sage.credentials.environment`, `sage.credentials.mapping`.
- Observability: `sage.observability.noop`,
  `sage.observability.filesystem`.
- Artifact and packages: `sage.artifact.ephemeral`,
  `sage.package-registry.ephemeral`.
- Interface projections: `sage.protocol.native`, `sage.protocol.ag-ui`,
  `sage.protocol.acp`, `sage.protocol.a2a`, `sage.protocol.mcp`.

Contracts, the Kernel, assemblers, policies, and services are not plugins:
they define framework semantics or coordinate already selected interfaces.
Only interchangeable implementations with a real factory belong in the
registry.

## Memory boundary

Memory is not Session storage. `MemoryProvider` exposes `recall`, `remember`,
`forget`, `get`, `health` and capabilities. SAgents does not define vector
tables, embeddings, rerankers or a vendor storage protocol.

`AgentDefinition.memory` controls recall, limit, auto-write and scope. Runtime
configuration selects the backend. Recall creates a volatile context segment
with provenance and never enters canonical history. Automatic write happens
only after a completed canonical Run or explicit snapshot publication. Failure
cannot roll back the Run.

The default remains `sage.memory.noop`. `sage.memory.filesystem-bm25` is the
first useful durable implementation: it stores records only in its own scoped
root and uses the established Chinese/Latin tokenization and BM25 ranking
family. It does not read or duplicate Session journals. Retrieval over
canonical conversation history is a Context concern; long-term, cross-Run
facts are the Memory provider's concern.

```yaml
runtime:
  memory_provider:
    plugin: sage.memory.filesystem-bm25
    config:
      root: runtime/memory-store
```

## Official tools

`sage.tool.official` loads the established decorator-backed SAgents tools. It
contains their V2-native implementations, and each method uses
`sagents.v2.tool.tool` as the single source for both schema and execution
registration. There is no V1 `ToolManager`, schema adapter, or automatic module
discovery in this path.

The 20 locally decorated tools are:

```text
apply_patch              grep                     glob
list_dir                 execute_shell_command    await_shell
kill_shell               file_read                file_write
file_update              analyze_image            read_lints
search_memory            questionnaire_async      questionnaire
todo_write               todo_read                tool_expand_tools
turn_status              fetch_webpages
```

Mode-specific code adds `sys_delegate_task`, `sys_spawn_agent`, and
`sys_team_delegate_task`. MCP and mode tools remain provider/mode additions
rather than being silently imported by `SAgentBuilder`.

Resource access is explicit. The embedding host provisions a V2 sandbox,
selects its policies, creates the grant signer and optionally selects a
`JobRuntime`, then injects one `OfficialToolRuntime`. File tools use
`SandboxFileSystem`; commands use `SandboxProcessRuntime`; background command
lifecycle uses `JobRuntime`; URL/image fetches use `SandboxNetworkRuntime`.
Tools cannot fall back to `Path`, `subprocess`, or an ungoverned HTTP client.

```python
manifest.runtime.tool_provider = ProviderSelection(
    plugin="sage.tool.official"
)
tool_runtime = OfficialToolRuntime(
    sandbox_handle,
    sandbox_grant_issuer,
    job_runtime=job_runtime,
)
agent = (
    SAgentBuilder()
    .with_defaults(session_root="runtime/session-store")
    .with_tool_runtime(tool_runtime)
    .build(manifest)
)
```

Built-in tools must use `sagents.v2.tool.tool`; the plugin loader collects only
decorated methods. `ToolDefinition` remains the runtime contract, not a second
place to hand-write built-in catalogs. `load_skill` is loaded by
`sage.tool.skill`; Fibre/Team delegation methods are loaded by
`sage.tool.multi-agent`.

External MCP servers are also Tool plugins. They are never discovered by
importing repository modules. Since their functions live outside this process,
the configured MCP server's `list_tools` response replaces the local Python
decorator as the authoritative declaration. `sage.tool.mcp` normalizes those
remote schemas to the same Catalog/Executor contracts, and public names use
`mcp_<server>_<tool>`.

## Scheduler and JobRuntime

These interfaces solve different lifecycle problems and neither stores a
Session:

- `Scheduler` queues a Run work item and hands it to a worker. Priority,
  delayed availability, renewable leases and fencing tokens prevent two stale
  workers from both committing the same work.
- `JobRuntime` owns background work started by a Run, such as a long command or
  media operation. It provides submit/inspect/wait/cancel, cursor-based output,
  pause handling, orphan detection and adoption by another Run.

The current `ephemeral` implementations are single-process reference plugins.
They are suitable for tests and local hosts, but a distributed service should
replace them with durable queue and Job backends through the same extension
registry.

## What a Context reducer does

A reducer receives the fully assembled model messages and a token/message
budget, then returns a bounded provider-request projection. It never deletes or
rewrites canonical Session events.

- `window` removes the oldest complete conversation units. An assistant tool
  call and its tool results are kept or removed together.
- `persistent-summary` replaces an old verified prefix with a derived summary
  and keeps recent units. The summary is stored under Session derived state and
  is invalidated when the source-message digest no longer matches.

This separation is why a user can still read the complete history and restore
the Session even when the model request was compressed.

## Example 1: default SAgent

```python
agent = (
    SAgentBuilder()
    .with_defaults(session_root="runtime/session-store")
    .with_model_client(model_http_client)
    .build("sage.yaml")
)

stream = await agent.run_stream(command, request_context)
async for event in stream.events:
    handle(event)
result = await stream.wait()
```

## Example 2: third-party ModelProvider

```python
registration = ExtensionRegistration(
    descriptor=my_descriptor,
    factory=lambda context, dependencies: MyModelProvider(context.config),
)

agent = (
    SAgentBuilder()
    .with_defaults(session_root="runtime/session-store")
    .register(registration)
    .build(package)
)
```

The model route selects it independently from the provider protocol:

```yaml
models:
  primary:
    plugin: acme.model.private-gateway
    provider: openai-responses
    model: acme-large
```

The package selects a stable plugin ID. Secrets come from host overrides or a
credential resolver, never from persisted manifests.

## Example 3: database SessionStore or MemoryProvider

Implement `runtime/session/contracts.py::SessionStore` or
`memory/contracts.py::MemoryProvider`, publish an `ExtensionRegistration`, and
run the same domain conformance tests as the built-ins. A database SessionStore
still owns only known-Session operations; global product indexing stays outside
SAgents.

Direct injection is useful during development:

```python
agent = (
    SAgentBuilder()
    .with_session_store(MyDatabaseSessionStore(connection))
    .with_memory_provider(MyMemoryProvider(client))
    .with_model_provider(my_model)
    .build(package)
)
```
