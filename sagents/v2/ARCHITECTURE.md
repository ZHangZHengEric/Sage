# SAgents V2 dependency map

SAgents V2 uses domain modules around a small extension kernel. Public callers
normally import only `SAgent` and `SAgentBuilder` from `sagents.v2`.

## Source dependency boundary

Production code under `sagents/v2/` may import only:

- another module under `sagents.v2`;
- the Python standard library;
- an explicitly declared third-party protocol or SDK dependency.

It must not import the legacy `sagents` runtime or application-owned packages
such as `common`, `app`, `mcp_servers`, `agents`, or `skills`. Integrations with
those applications happen through public V2 contracts and injected plugins.
The source-boundary test parses every V2 module, including literal dynamic
imports, so deleting the legacy implementation cannot break V2 imports.

| Module | Owns | Primary extension boundary |
|---|---|---|
| `contracts/` | Commands, events, items, run/session state | Versioned wire models |
| `runtime/kernel.py` | Legal lifecycle commands and state transitions | `SessionStore` |
| `runtime/session/` | One known Session, Runs, journal, CAS, resume | `SessionStoreRegistry` |
| `agent/` | One model/tool loop and delegation policies | Presets and policies |
| `context/` | Provider payload assembly and reduction | sources, estimator, summarizer |
| `model/` | Model request/stream contract | `ModelProviderRegistry` |
| `tool/` | Paired catalog and executor contract | `ToolProviderRegistry` |
| `skill/` | Catalog, lazy source, verification, activation | `SkillProviderRegistry` |
| `memory/` | Long-term recall/write coordination | `MemoryProviderRegistry` |
| `flow/` | One graph engine | `FlowNodeRegistry` |
| `runtime/execution/` | Jobs, scheduler, workspace and sandbox | provider contracts |
| `runtime/observability/` | Non-authoritative diagnostics and traces | sinks |
| `runtime/extensions/` | registrations, resolution, scopes and lifecycle | microkernel |
| `package/` | Manifest resolution, presets and package lifecycle | package definitions |
| `interfaces/protocols/` | Native/AG-UI/ACP/MCP/A2A projections | protocol adapters |
| `testing/` | Scripted providers and conformance harnesses | test-only plugins |

```text
sagent -> builder -> agent/factory -> runtime/kernel -> domain contracts
                                      agent loop -> context/model/tool/skill/memory
builder -> extension registry/resolver/host -> domain plugin factories
interfaces -> canonical RuntimeEvents
Desktop/server -> SAgents + application-owned Session index
```

`runtime/extensions/` never contains domain implementations. An implementation
lives under its domain, for example `model/plugins/openai_responses.py`, and is
registered by a real `ExtensionRegistration` factory.

`runtime/kernel.py` depends only on `SessionStore` contracts and requires the
selected store at construction. Shared transactional semantics live in
`runtime/session/state.py`; file and ephemeral backends adapt that state core
without inheriting from each other.

Execution domains consume `runtime/contracts.py::RuntimePort`; only composition
code constructs `HarnessRuntime`. This keeps Agent and Flow orchestration from
depending on one in-process lifecycle implementation.

## Single-Session authority

The framework has no concept of “all Sessions”. `SessionStore` can create or
open one known `session_id`, manipulate its Runs, and recover that Session from
its checksummed state. It has no list/search/page/title/archive/favorite API.

`FilesystemSessionStore` does not materialize all Sessions in memory on startup.
A known `session_id` maps directly to one directory. Run-only compatibility
methods use a locator and load only the matching Session. Product software such
as Desktop owns any global index.

## Authoritative versus derived data

```text
Session state    -> authoritative lifecycle and canonical history
derived/         -> deletable summaries, token caches, Skill activation
MemoryProvider   -> independent long-term Memory backend
DiagnosticSink   -> optional model/trace diagnostics, never recovery input
Desktop index    -> product-owned list/search metadata
```

Deleting derived data or diagnostics cannot change Session recovery. Memory
failure cannot roll back an acknowledged Session commit.
