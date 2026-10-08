# Versioned source layout

Application implementations are grouped symmetrically under `app/v1/` and
`app/v2/`. Agent engines live under `sagents/v1/` and `sagents/v2/`.

| Area | v1 | v2 |
| --- | --- | --- |
| Agent runtime | `sagents/v1/` | `sagents/v2/` |
| Desktop | `app/v1/desktop/` | `app/v2/desktop/` |
| Server | `app/v1/server/` | `app/v2/server/` |
| Legacy application services | `app/v1/common/` | Host-owned services |
| Browser bridge | `app/v1/chrome-extension/` | — |
| Runtime tests | `tests/sagents/v1/` | `tests/sagents/v2/` |
| Application tests | `tests/app/v1/` | `tests/app/v2/desktop/`, `tests/app/v2/server/` |
| Legacy examples | `examples/v1/` | `examples/sagents_v2_*.py` |
| Legacy benchmarks | `scripts/v1/` | `scripts/v2/benchmark_v2_*.py` |

The `sagents/v1` and `sagents/v2` runtime packages own their implementations
independently; there is no cross-version runtime helper package. AnyTool is an independent MCP integration, not a runtime helper package. The old model probes, image/request helpers, logger,
diagnostics, and sandbox policy all belong to `sagents/v1/`.

Desktop v2 uses the image encoder already provided by `sagents/v2/`. Its command
assessment rules and fallback model request defaults belong to its own backend.
Those modules do not import v1 code. V2 capability profiles continue to take
precedence over fallback request defaults.

`clients/cli/` and `clients/terminal/` select between runtimes and remain public entry
points. `app/skills/` and `app/wiki/` remain shared resources. `app/v1/common/` is the legacy application service layer, not a version-neutral
runtime library. `mcp_servers/` contains separately hosted MCP integrations;
several still depend on v1. Legacy integrations remain outside the agent engine; AnyTool is independently deployable. The AnyTool MCP package is independent; v2 does not
consume the legacy adapters. Deployment files keep their existing locations while
referencing the new v1 source paths. Runtime data directories are unchanged.

## Imports and commands

The public `from sagents import SAgent` export remains lazy and refers to the
same class as `from sagents.v1 import SAgent`. V2 engine imports remain `sagents.v2`; application imports use `app.v2.desktop`
and `app.v2.server`. Legacy services import `app.v1.common`.
Internal/deep imports now use explicit versioned paths; external code using
`sagents.context`, `sagents.tool`, `app.server`, or `app.desktop` must update to
`sagents.v1.context`, `sagents.v1.tool`, `app.v1.server`, or `app.v1.desktop`.
There is no duplicate module tree or global import hook.

```bash
python examples/v1/sage_demo.py --help
python examples/v1/sage_cli.py --help
python examples/v1/sage_server.py --help
python -m app.v1.server.main
bash app/v1/desktop/scripts/dev.sh
python -m pytest tests/sagents/v1 tests/app/v1
```

The `sage` command still points to `clients.cli.main:main`, including its `v2`
subcommands. Old release notes and `docs/archive/` describe historical layouts
and are not rewritten.

## Ownership and dependency rules

| Directory | Responsibility | Dependency rule |
| --- | --- | --- |
| `sagents/v1`, `sagents/v2` | Version-owned agent engines | No imports from the other engine or application service layer |
| `app/v1` | Legacy Desktop, Server, browser bridge | Uses v1 and `app/v1/common` |
| `app/v2/desktop` | Flutter client and local Python host | Uses v2 and the independent AnyTool MCP package; no legacy services |
| `app/v2/server` | Server API, persistence, web client | Uses v2; no legacy application services |
| `app/v1/cli` | Legacy CLI implementation | Uses v1 application services |
| `app/v2/cli` | V2 CLI implementation and configuration | No v1 imports |
| `clients/cli` | Public command dispatch and terminal launcher | Lazily selects the application version |
| `clients/terminal` | Rust terminal client and launchers | Selects the requested backend; not an agent engine |
| `app/v1/common` | Legacy application configuration, DAOs, schemas, services | New v2 features must not import it |
| `mcp_servers` | Built-in MCP integrations | Not a version-neutral core library |
| `app/skills`, `app/wiki` | Packaged content | Resources rather than runtime implementations |
| `scripts`, `deploy`, `.github` | Repository operations, packaging, CI | Version-specific source paths must be explicit |
| `tests` | Tests mirroring source ownership | Keep v1/v2 suites separate |
| `docs`, `examples` | Documentation and runnable examples | Historical archive paths do not define current entry points |

### Independent AnyTool MCP

`mcp_servers/anytool/` owns tool schemas, simulation prompts, JSON parsing,
model protocol adapters, and its standalone stdio entry point. It imports neither
`common`, `app`, nor either `sagents` runtime. It supports OpenAI Chat Completions,
OpenAI Responses, Anthropic Messages, and Gemini GenerateContent through explicit simulator configuration.

- v1 owns its DAO/model selection and HTTP mounting adapters in
  `app/v1/common/services/anytool_adapter.py` and `app/v1/common/services/anytool_http.py`.
- Desktop v2 owns its mount and configuration in `app/v2/desktop/backend/anytool.py`.
  Complete explicit simulator credentials take precedence; otherwise it selects
  the user's usable default model, then the first usable model from the v2 catalog.
- MCP tool arguments cannot override the host-configured user identity.
- AnyTool can run without either application: `python -m mcp_servers.anytool CONFIG.json`.

See [AnyTool configuration](../mcp_servers/anytool/README.md).

### Automated checks

Run `python scripts/checks/check_architecture.py` from the repository (or invoke it by
absolute path from another directory). CI runs it before the Python test jobs. It parses
all tracked and non-ignored new Python sources, checks internal module paths,
resolves relative imports, and rejects cross-version runtime imports and
legacy imports in v2 applications. It also forbids Sage imports inside AnyTool. Literal dynamic imports are checked too;
computed dynamic imports and actual runtime behavior still need integration tests.
Historical manual demos are syntax-checked but excluded from import validation.

`pyrightconfig.json` includes both v2 Python hosts and uses `.venv`. Python
architecture checks do not replace Flutter, TypeScript, Rust, packaging, or HTTP
smoke checks; their current results are in [the runtime report](V1_V2_RUNTIME_CHECK.md).

Ignored `build/`, `dist/`, `node_modules/`, caches, logs, and local workspace data
are generated state, not additional source layers. Do not move or delete user
workspace data as part of source organization.

## Local workspace leftovers

`app/web` contained only old dependency artifacts; these were verified and
removed during the requested cleanup. It is not a supported application.
`app/agent_workspace` contains local identity/memory/skill files and is preserved
at its existing path; it is user data, not tracked application source. Python
caches may reappear after running commands and are ignored by Git.

## Command and terminal clients

`app/cli` and `app/terminal` no longer exist. The Python CLI implementations are
version-owned; `clients/cli` contains only public dispatch, combined help, and the
terminal launcher. The installed command remains `sage`; the module entry point
is `python -m clients.cli.main`. `sage run` selects v1, `sage v2 run` selects v2,
and `sage tui --runtime v2` starts the Rust client with the v2 protocol.

V2 CLI environment loading and stderr logging are independent of the v1 startup
configuration and database. The existing environment variable names and defaults
are preserved. Import-blocking tests cover both directions of dispatch.

## Single built-in skill source and script ownership

Only `app/skills` is the built-in skill source. The former ignored root `skills`
was a local workspace with conflicting files and a sandbox, not a second source
package; it is preserved under `.sage/organization-backup/root-skills`. User
skill stores and packaged copies are runtime data, not additional source trees.

Repository scripts are grouped under `scripts/checks`, `dev`, `maintenance`,
`release`, `v1` and `v2`. See [script usage and side effects](../scripts/README.md).
