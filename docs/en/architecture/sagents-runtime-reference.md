---
layout: default
title: Runtime Reference
parent: Architecture
nav_order: 15
lang: en
ref: v2-detail-sagents-runtime-reference
---

{% include lang_switcher.html %}

<a id="sagents-v2-runtime-配置参考"></a>

# SAgents Runtime reference

Skills can be configured as two groups, management and usage. See
[Skill plugins and version behavior](sagents-skill-management-and-usage.md).

[Host development](sagents-host-development.md) · [sage.yaml reference](sagents-manifest-reference.md) · [Code reading guide](code-reading-guide.md)

This reference describes configuration supported by SAgentBuilder.build() and app.load_agent(). Runtime chooses App components; the App catalog owns model routes and credentials; Agent Packages define instructions, model IDs, tool scope and budgets. Desktop/Server database addresses, login, listeners and workspace choices are host settings rather than RuntimeConfig fields.

<a id="app-模型配置"></a>

## App model configuration

App accepts two configurations: runtime.yaml selects components and parameters; models.yaml manages models and credential references. models is not a RuntimeConfig field and must not be placed inside runtime.yaml. Agent Packages reference App model IDs.

```python
from sagents.v2 import SAgentBuilder

app = await SAgentBuilder().build(
    runtime="./runtime.yaml",
    models="./models.yaml",
)
try:
    agent = await app.load_agent("./agents/assistant")
finally:
    await app.close()
```

models accepts a path string, Path, dictionary or ModelCatalogConfig. Text uses models_config_text= and is mutually exclusive with models. Omission creates an empty catalog without reading local keys or providing models. Runtime components still use the standard profile; Desktop/Server inject their host model catalogs.

```yaml
# models.yaml
credentials:
  model-key: {source: env, key: MODEL_API_KEY}
models:
  primary:
    provider: openai-responses
    model: your-model
    base_url: https://api.openai.com/v1
    credential: model-key
    request:
      max_output_tokens: 4096
      reasoning_effort: medium
    limits:
      context_window: 128000
      max_output_tokens: 4096
    capabilities:
      tool_calling: true
      reasoning: true
```

your-model, window sizes and reasoning options are examples requiring real provider values. Declarations cannot add unsupported model features. Never copy another route's probe results. The only top-level fields are models and credentials, both empty mappings by default. Unknown fields, duplicate YAML keys and invalid credential references are rejected.

<a id="更新与版本"></a>

### Updates and revisions

`build(models=...)` configures the model catalog before build. Update a running App through:

```python
await app.update_models("./models.yaml")  # 原子替换整个目录
route = app.models.models["primary"].model_copy(deep=True)
route.request.reasoning_effort = "high"
await app.update_model("primary", route)  # 替换单个模型的完整配置
agent_v2 = await app.load_agent("./agents/assistant")
```

update_model accepts a complete ModelRoute or equivalent dictionary, not a partial patch. Submit new credentials through update_models. app.models returns a copy; modifying it does not update App. Validation precedes publication and failures preserve the current catalog.

After model updates, reload the same Package to obtain a new handle. Old handles and admitted Runs retain their snapshots. Package changes still require update_agent. Updating unused models does not change an Agent's composition identity. Recovery uses the admitted revision rather than current model settings. Credential services supply secret material without embedding it in Package or model snapshots.

Hosts admitting different configurations concurrently can pass isolated configuration directly to each load:

```python
agent = await app.load_agent(package, runtime=selected_runtime, models=selected_models)
updated = await app.update_agent(
    agent=agent, package=changed_package,
    runtime=selected_runtime, models=selected_models,
)
```

Both arguments are copied, validated and included in composition without changing `app.runtime_configuration` or `app.models`. Different revisions can build concurrently; concurrent requests for the same revision share one build. `update_agent` still checks that the supplied revision is current; after a competing update wins, reload the current handle before retrying. Session storage, scheduling and security settings belong to the App identity and cannot be switched by an individual load.

Active execution, admission and streaming projection retain revision resources. Other idle revisions, including the current configuration, are cached up to 64 entries and released after 300 idle seconds by a task running every 30 seconds; only the immutable handle and plan metadata remain for the current configuration. The first revision provides shared App services and remains until shutdown. Reclamation preserves revision snapshots: using an old handle through `entrypoint()`, the stable facade returned by synchronous `app.agent()`, or recovery reassembles that revision and verifies its original composition hash. The synchronous facade's `runtime.start_run/stream` also restores the original revision to freeze execution configuration; other RuntimePort reads and controls use the shared App runtime. Event subscriptions and protocol projections hold revision references while iterating; close their iterator or detach when finished. Tenant workspace paths belong to the admitted Run's execution snapshot. Server freezes the path from verified identity during admission, so additional tenants do not cause the same Agent to be composed repeatedly.

### credentials

```yaml
credentials:
  public-api:
    source: env
    key: MODEL_API_KEY
  managed-api:
    source: host
    ref: tenant-primary-model
```

| Field | Type | Default | Meaning |
| --- | --- | --- | --- |
| `source` | `env` / `host` | required | Resolve from environment or host credential service |
| `key` | string / null | null | Environment variable name for env |
| `ref` | string / null | null | Credential reference for host |

key/ref must identify environment variables or host references, not contain secrets. env requires a usable key and host a resolvable ref. Nullable schema fields do not establish credential availability; the provider validates resolution. The default environment provider does not read host credentials from Server databases.

### models

App models.<id> defines routes; Package agents.main.models.<slot> references an App ID. Common slots are primary and fast; route names are configurable.

| ModelRoute field | Type | Default | Meaning |
| --- | --- | --- | --- |
| `provider` | Identifier | required | Provider protocol ID, not model name |
| `plugin` | Identifier / null | null | Registered model.provider plugin; otherwise resolve provider protocol |
| `base_url` | string / null | null | Absolute HTTP(S) URL without userinfo, query or fragment |
| `credential` | Identifier / null | null | Key in top-level credentials |
| `model` | string | required | Provider model ID |
| `request` | ModelRequestDefaults | see below | Request defaults |
| `limits` | ModelLimits | see below | Context/output limits |
| `capabilities` | ModelCapabilityDeclaration | see below | Declared capabilities; not a substitute for probing |
| `capability_profile` | ModelCapabilityProfile / null | null | Versioned host probe results and invocation strategy |

Built-in protocols are openai-responses, openai-chat-completions, anthropic-messages and gemini-generate-content, implemented as sage.model.<protocol>. Missing models or protocol mismatch do not trigger provider fallback.

| request field | Type / range | Default | Meaning |
| --- | --- | --- | --- |
| `max_output_tokens` | positive integer / null | null | Requested output token limit |
| `temperature` | number / null | null | Sampling temperature subject to provider constraints |
| `top_p` | number / null | null | Nucleus sampling, subject to provider constraints |
| `reasoning_effort` | string / null | null | Reasoning effort interpreted by model protocol |
| `extra` | object | `{}` | Protocol extensions; support varies |

| limits field | Type | Default | Meaning |
| --- | --- | --- | --- |
| `context_window` | positive integer / null | null | Context window limit |
| `max_output_tokens` | positive integer / null | null | Model output token limit |

null means unspecified here, not unlimited. Model, host and Run budgets still apply.

| capabilities field | Default | Meaning |
| --- | --- | --- |
| `multimodal` | false | Multimodal input |
| `structured_output` | false | Structured output |
| `tool_calling` | true | Tool calling |
| `reasoning` | false | Reasoning |
| `parallel_tool_calls` | false | Parallel tool calls |

All capability flags above are boolean. capability_profile has schema_version=1 and requires plugin_id, plugin_version, protocol, route_fingerprint, positive effective_max_output_tokens and outcomes. verified_at defaults to current UTC; invocation_strategy and metadata default to {}. outcomes must contain exactly connection, multimodal, structured_output, json_object, tool_calling and reasoning_control without duplication.

Each outcome requires name and status (supported/unsupported/error/skipped). response, error, error_code, error_category and provider_code default to null; metadata defaults to {}. These facts belong to one route revision. Copying another profile does not constitute validation. The plugin interprets invocation_strategy.

<a id="目录"></a>

## Contents

- [Input forms](#输入方式)
- [Defaults and precedence](#默认值和优先级)
- [All RuntimeConfig fields](#runtimeconfig-全部字段)
- [All CapabilitySelection fields](#capabilityselection-全部字段)
- [Default components](#默认组件)
- [Common configurations](#常见配置)
- [Custom plugins, validation and lifecycle](#自定义插件校验和生命周期)
- [Configuration and recovery diagnosis](#排查配置与恢复问题)
- [Built-in plugin parameters](#内置插件完整参数表)

<a id="输入方式"></a>

## Input forms

These inputs apply at App creation. Paths and text are distinguished explicitly without guessing YAML strings.

```python
from pathlib import Path
from sagents.v2 import SAgentBuilder
from sagents.v2.package.manifest.runtime import RuntimeConfig

# 四种等价的输入形式，实际项目选一种。
app = await SAgentBuilder().build(runtime="./runtime.yaml")
# app = await SAgentBuilder().build(runtime=Path("./runtime.yaml"))
# app = await SAgentBuilder().build(runtime={"capabilities": {}})
# app = await SAgentBuilder().build(runtime=RuntimeConfig())
# app = await SAgentBuilder().build(runtime_config_text="preset: standard\n")
try:
    agent = await app.load_agent("./agents/assistant")
finally:
    await app.close()
```

runtime and runtime_config_text are mutually exclusive. YAML/JSON must have an object root; duplicate keys, unknown fields and wrong types fail. Runtime files begin directly with preset/capabilities: **do not wrap them in runtime:** as in sage.yaml. File paths support ~. Component config.root values follow component/host semantics, without a universal runtime-file-relative rule. Prefer absolute deployment paths.

<a id="默认值和优先级"></a>

## Defaults and precedence

Distinguish these cases:

| Call | Behavior |
| --- | --- |
| build() without runtime | Shared Desktop component profile; runtime root defaults to .runtime/sagents in cwd |
| `build(runtime={})` / `build(runtime=RuntimeConfig())` | RuntimeConfig field defaults and assembler fallbacks, without layering the full Desktop profile |
| build(runtime=config) | App uses this runtime; subsequently loaded Packages cannot override it |

Use `default_runtime(session_root)` and pass its result to `build(runtime=..., models=...)` to choose the runtime root. Shared defaults select components without reading Desktop API keys, catalogs, databases or personal settings.

For small overrides, copy default_runtime() before editing. A two-component explicit config does not automatically inherit the Desktop profile:

```python
from sagents.v2 import SAgentBuilder
from sagents.v2.composition.defaults import default_runtime
from sagents.v2.package.manifest.runtime import RuntimeConfig

config = default_runtime("./runtime").model_dump(mode="json")
config["capabilities"]["context.reducer"]["config"] = {
    "summary_target_tokens": 1536,
    "protected_recent_units": 6,
}
app = await SAgentBuilder().build(runtime=RuntimeConfig.model_validate(config))
try:
    agent = await app.load_agent("./agents/assistant")
finally:
    await app.close()
```

Configuration precedence:

1. build fixes App runtime; editing Packages does not replace process resources.
2. plugins[].config supplies declaration parameters. capabilities.<name>.config overrides them; composition may also add defaults. Inspect the resolved plan.
3. Explicit host services and locked dependencies win. YAML cannot replace injected model, session_store or derived_state objects.
4. Server/Desktop construct runtime from their settings, persistence and grants; shared SDK contracts do not override host security policies.

To adopt sage.yaml runtime, read and pass it explicitly, as the starter does:

```python
from sagents.v2 import SAgentBuilder
from sagents.v2.package.manifest import SageManifestLoader

manifest = SageManifestLoader().load("./agents/assistant/sage.yaml")
app = await SAgentBuilder().build(runtime=manifest.runtime)
try:
    agent = await app.load_agent(manifest)
finally:
    await app.close()
```

<a id="runtimeconfig-全部字段"></a>

## All RuntimeConfig fields

| Field | Type / values | Default | Purpose and boundary |
| --- | --- | --- | --- |
| `preset` | Identifier | `standard` | Preset label; generic composition does not switch profiles by name |
| `deployment_profile` | `controlled_host` / `distributed` | `controlled_host` | Required guarantees; distributed adds checks rather than enabling replicas |
| `plugin_trust_policy` | `trusted_declared` / `built_in_only` | `trusted_declared` | Trust declared plugins or registry-verified built-ins; self-declared metadata cannot bypass trust |
| `capabilities` | capability → selection or selection array | `{}` | Select implementation, name, scope and config within cardinality constraints |
| `required_guarantees` | capability → guarantee → expected value | `{}` | Enforced provider requirements; fail when unproven |

Identifier is 1–192 characters, starts with a letter/digit and otherwise permits letters, digits and `._:@/-`. Guarantee names must match actual provider reports. Built-in SessionStore/Scheduler do not supply a complete distributed claims/outbox/subscription system. Switching to SQL alone does not enable shared multi-process execution.

<a id="capabilityselection-全部字段"></a>

## All CapabilitySelection fields

```yaml
capabilities:
  context.unit-compactor:
    plugin: sage.context.unit-compactor.reference
    name: default
    scope: agent
    config: {}

```

| Field | Type | Default | Meaning |
| --- | --- | --- | --- |
| `plugin` | Identifier | required | Registered plugin ID, not import path |
| `name` | Identifier | `default` | Offer name; implicit default is resolvable for a single matching offer |
| `scope` | `process` / `tenant` / `agent` / `run` / null | null | Use composition scope by default; explicit scope must be supported |
| `config` | object | `{}` | Plugin-specific validated parameters |

process follows App lifetime; tenant isolates tenants; agent follows an Agent/revision composition scope; run follows one Run. Scope neither creates cross-process sharing nor adds locks. Process/tenant/Agent plugins must handle overlapping calls. Some composition points require a particular scope and host identity.

<a id="默认组件"></a>

## Default components

R denotes Path(session_root).expanduser().resolve(), with session_root=.runtime/sagents by default. Omitted config uses the plugin defaults below.

| Capability | build() default plugin | Default parameters / purpose |
| --- | --- | --- |
| `session.store` | `sage.session.filesystem` | root=R; canonical Sessions, commands and events |
| `memory.provider` | `sage.memory.filesystem-bm25` | root=R/memory; long-term retrieval/storage |
| `session-memory.provider` | `sage.session-memory.sqlite-bm25` | root=R/session-memory; Session memory index |
| `skill.loading` | `sage.skill.loading.lazy` | On-demand Skill activation, up to 24000 active characters |
| `agent.continuation-policy` | `sage.agent.continuation.llm-judge` | Model judges continuation/completion |
| `context.reducer` | `sage.context.reducer.persistent-summary` | Persistent summary compression |
| `context.summarizer` | `sage.context.summarizer.model` | Primary model generates summaries |
| `context.summary-store` | `sage.context.summary-store.session-derived` | Session-derived summary state |
| `memory.recall-query` | `sage.memory.recall-query.llm` | Model-generated recall queries |
| `tool.selection-policy` | `sage.tool-selection.llm` | Select visible tool schemas on demand |
| `observability.diagnostic-sink` | `sage.observability.filesystem` | root=R/sessions, legacy_root=R/diagnostics; diagnostics |
| `observability.log-sink` | `sage.logging.filesystem` | root=R/logs; structured runtime logs |
| `workspace.initializer` | `sage.workspace.initializer.claw` | language=en; workspace starter material |

Other services use composition fallbacks: sage.scheduler.ephemeral, sage.job.ephemeral, sage.artifact.session, sage.package-registry.ephemeral, sage.trace.noop, sage.credentials.environment and sage.context.unit-compactor.reference. App models resolve Agent model ID references.

Explicit empty runtime differs: memory and Session memory are noop, recall query is direct, continuation deterministic, diagnostics/logging noop and workspace initialization bare. Session storage still falls back to filesystem. **Providing memory components does not enable Agent memory.recall/auto_write; both default to false.**

Sandbox is host-bound: shared defaults recommend sage.sandbox.local-workspace, but default_runtime() deliberately omits execution.sandbox because it requires a verification key, workspace and execution binding. Desktop uses real host paths. workspace_root, workspace_path_mode, workspace_mapping and filesystem_mode belong to execution bindings, not arbitrary plugin config. build() alone grants no local filesystem execution permission.

<a id="常见配置"></a>

## Common configurations

<a id="输出日志调整摘要和调度并发"></a>

### Logging, summaries and scheduler concurrency

This is an explicit runtime; omitted components use composition fallbacks. To retain all Desktop defaults, copy default_runtime() first.

```yaml
preset: standard
deployment_profile: controlled_host
plugin_trust_policy: trusted_declared
capabilities:
  session.store:
    plugin: sage.session.filesystem
    config: {root: /srv/my-app/runtime}
  observability.log-sink:
    plugin: sage.logging.stdout
    config: {stream: stderr, min_level: debug, format: json}
  context.reducer:
    plugin: sage.context.reducer.persistent-summary
    config: {summary_target_tokens: 1536, protected_recent_units: 6}
  execution.scheduler:
    plugin: sage.scheduler.filesystem
    config:
      root: /srv/my-app/runtime/scheduler
      max_concurrent_runs: 8
      max_concurrent_runs_per_tenant: 2
      lease_seconds: 172800
```

Scheduler concurrency limits App Runs rather than model-provider QPS. The runtime renews leases; lease_seconds is not a conversation timeout. Agent/Run wall_time_seconds, summarizer timeouts and per-server MCP timeouts serve different boundaries.

<a id="mcp-与工具可见性"></a>

### MCP and tool visibility

```yaml
capabilities:
  tool.catalog:
    plugin: sage.tool.mcp
    name: mcp
    config:
      servers:
        - name: docs
          protocol: streamable_http
          url: http://127.0.0.1:9000/mcp
          timeout_seconds: 30
          required: true
          max_result_bytes: 4194304
```

This config adds a tool source. Agent tools still require explicit authorization. Use discovered MCP names rather than guessing. Verify connectivity and authentication. stdio uses command/args/env; HTTP/SSE uses url. env is the subprocess environment, not global interpolation. required=true discovery failure must not be reported as a usable source.

<a id="数据库存储"></a>

### Database storage

```yaml
capabilities:
  session.store:
    plugin: sage.session.mysql
    config:
      dsn: mysql://user:password@localhost/sage
      table_prefix: sagent
```

DSNs illustrate syntax; never commit passwords. Runtime text has no universal ${ENV} interpolation. Hosts should read secrets and build config or inject SessionStore. MySQL requires aiomysql. SQL storage does not make in-memory Jobs or schedulers durable/distributed.

<a id="自定义插件校验和生命周期"></a>

## Custom plugins, validation and lifecycle

Use the same registration and configuration path as built-ins; register before build:

```python
from sagents.v2 import SAgentBuilder
from examples.v2.host.plugins import compactor_registration

builder = SAgentBuilder()
builder.register(compactor_registration())
app = await builder.build(runtime={
    "capabilities": {
        "context.unit-compactor": {
            "plugin": "example.context.reference-compactor",
            "config": {"minimum_characters": 4},
        },
    },
})
try:
    agent = await app.load_agent("./agents/assistant")
finally:
    await app.close()
```

See independent [plugins.py](../../../examples/v2/host/plugins.py). Registration supplies descriptor, schema/config model, factory and optional start/stop. Depend on SDK contracts rather than other implementations; inheritance from a shared base is unnecessary.

build fixes registry/configuration and Agent loading performs composition/validation. Unknown options, missing dependencies, unavailable plugins, incompatible scope/API and unsupported guarantees must fail there. Accepted parameters alone do not prove activation. Plugin declarations do not install dependencies, and YAML does not perform arbitrary Python imports.

`config` accepts finite JSON values at configuration, planning and plugin-context boundaries. Models, stores, clients and callbacks are dependencies rather than parameters. Built-ins and custom plugins declare required capabilities in `ExtensionDescriptor.dependencies` and retrieve instances in factories with methods such as `dependencies.require_unique("model.provider")`; named dependencies use `require(capability, name)`. The same graph checks versions, startup order, lifetimes and cleanup ownership. Missing or invalid-lifetime dependencies fail composition; object configuration has no fallback.

Register host-created objects through factories with `ownership="borrowed"`; the host closes these objects. The default `ownership="owned"` transfers resource cleanup to the plugin lifecycle. App-owned plugins follow scoped startup, rollback and shutdown. Close App with try/finally, reuse it across requests and do not manually close App-owned providers.

<a id="排查配置与恢复问题"></a>

## Configuration and recovery diagnosis

1. Inspect agent.resolved_plan and agent.resource_readiness; app.resolved_plan is only the initial process view.
2. Query `app.execution_configuration(run_id, context)` and `app.execution_diagnostics(run_id, context)` for the admitted configuration and actual binding.
3. Correlate session_id, run_id and resolved_spec_hash; recovery must retain the admitted revision.
4. update_agent does not replace shared storage/scheduling. Rebuild App for runtime changes with an explicit old-Run migration/recovery policy.
5. Retain agent-revisions and Sessions. Local archived recovery requires matching runtime, not the latest settings.
6. Readiness still needs representative real model/tool calls.

<a id="内置插件完整参数表"></a>

## Complete built-in plugin parameters

The tables cover every registered plugin, including parameterless ones. Schema-required fields describe JSON parameters; runtime objects are declared capability dependencies. Defaults come from registered schema and verified factories/schedulers. No fixed value means context-dependent, rather than null or disabled.

Ranges are validation constraints. Bytes and seconds are literal units. Tokens mean API output budgets or measured provider usage thresholds, without local input estimates. Dependency objects are resolved through providers rather than configuration fields. Registration does not mean any capability entry creates a plugin: tool/model/Flow/interface composition has dedicated paths. Check offered capabilities and consumption points.

<a id="插件索引"></a>

### sage.agent.approval-memory.session

Standard agent.approval-memory implementation with declared dependencies and lifecycle.

Version: `2.0.0`; scope: process; ownership: `owned`。

Provides: `agent.approval-memory:default` (API `2`)。

Dependencies: `derived-state.store` (API `>=2,<3`)。

No fixed configuration fields; consult the public schema for additional parameters.

### sage.agent.continuation.deterministic

Applies ordered safety, budget, and completion rules without a model call.

Version: `2.0.0`; scope: agent, run; ownership: `owned`。

Provides: `agent.continuation-policy:default` (API `2`)。

| Parameter | Type | Required | Schema Default | Constraints |
| --- | --- | --- | --- | --- |
| `repeat_threshold` | `integer` | No | `3` | `{"minimum":1}` |

### sage.agent.continuation.explicit-status

Completes only when the model emits an explicit turn_status.

Version: `2.0.0`; scope: agent, run; ownership: `owned`。

Provides: `agent.continuation-policy:default` (API `2`)。

| Parameter | Type | Required | Schema Default | Constraints |
| --- | --- | --- | --- | --- |
| `repeat_threshold` | `integer` | No | `3` | `{"minimum":1}` |

### sage.agent.continuation.hybrid

Combines deterministic safety rules with an LLM judge for completion.

Version: `2.0.0`; scope: agent, run; ownership: `owned`。

Provides: `agent.continuation-policy:default` (API `2`)。

Dependencies: `model.provider`.

| Parameter | Type | Required | Schema Default | Constraints |
| --- | --- | --- | --- | --- |
| `repeat_threshold` | `integer` | No | `3` | `{"minimum":1}` |
| `model_binding` | `string` | No | `"fast"` | `{"minLength":1}` |
| `timeout_seconds` | `number` | No | `60.0` | `{"exclusiveMinimum":0}` |

### sage.agent.continuation.llm-judge

Uses a judge model to decide completion when no tool call is pending.

Version: `2.0.0`; scope: agent, run; ownership: `owned`。

Provides: `agent.continuation-policy:default` (API `2`)。

Dependencies: `model.provider`.

| Parameter | Type | Required | Schema Default | Constraints |
| --- | --- | --- | --- | --- |
| `repeat_threshold` | `integer` | No | `3` | `{"minimum":1}` |
| `model_binding` | `string` | No | `"fast"` | `{"minLength":1}` |
| `timeout_seconds` | `number` | No | `60.0` | `{"exclusiveMinimum":0}` |

### sage.agent.tool-policy.default

Standard agent.tool-policy implementation with declared dependencies and lifecycle.

Version: `2.0.0`; scope: process; ownership: `owned`。

Provides: `agent.tool-policy:default` (API `2`)。

| Parameter | Type | Required | Schema Default | Constraints |
| --- | --- | --- | --- | --- |
| `approval_strategy` | `string` | No | `"configured"` | `{"enum":["configured","always_ask","high_risk","auto_approve"]}` |

### sage.artifact.ephemeral

Process-local artifact bytes without restart durability.

Version: `2.0.0`; scope: process, run; ownership: `owned`。

Provides: `artifact.store:default` (API `2`)。

No fixed configuration fields; consult the public schema for additional parameters.

### sage.artifact.filesystem

Immutable binary artifact files with local restart durability.

Version: `2.0.0`; scope: process; ownership: `owned`。

Provides: `artifact.store:default` (API `2`)。

| Parameter | Type | Required | Schema Default | Constraints |
| --- | --- | --- | --- | --- |
| `root` | `string` | Yes | Not declared | `{"minLength":1}` |

### sage.artifact.session

Artifacts retained by the owning Session store.

Version: `2.0.0`; scope: process; ownership: `owned`。

Provides: `artifact.store:default` (API `2`)。

Dependencies: `session.store`.

No fixed configuration fields; the public schema determines whether extra parameters are allowed.

### sage.context.reducer.persistent-summary

Summarizes complete history only after API rejection or reported usage reaches a configured limit.

Version: `2.0.0`; scope: agent, run; ownership: `owned`。

Provides: `context.reducer:default` (API `2`)。

Dependencies: `context.summary-store`, `context.summarizer`, `context.unit-compactor`.

| Parameter | Type | Required | Schema Default | Constraints |
| --- | --- | --- | --- | --- |
| `summary_target_tokens` | `integer` | No | `1024` | `{"minimum":1}` |
| `protected_recent_units` | `integer` | No | `4` | `{"minimum":1}` |
| `max_summary_calls` | `integer` | No | `64` | `{"minimum":1}` |
| `max_summary_source_tokens` | `integer` | No | `24000` | `{"minimum":1}` |

`max_summary_source_tokens` 作为已有配置字段被 schema 接受；当前内置 reducer 工厂不以它控制输入长度。需要配置摘要源预算时，使用所选 summarizer 能力的正式Parameter。

### sage.context.reducer.window

Drops complete historical units only when explicitly requested.

Version: `2.0.0`; scope: agent, run; ownership: `owned`。

Provides: `context.reducer:default` (API `2`)。

No fixed configuration fields; consult the public schema for additional parameters.

### sage.context.summarizer.extractive

Preserves bounded task state and Tool outcomes without a model call.

Version: `2.0.0`; scope: agent, process; ownership: `owned`。

Provides: `context.summarizer:default` (API `2`)。

No fixed configuration fields; consult the public schema for additional parameters.

### sage.context.summarizer.model

Uses a model binding to write conversation summaries.

Version: `2.0.0`; scope: agent, run; ownership: `owned`。

Provides: `context.summarizer:default` (API `2`)。

Dependencies: `model.provider`.

| Parameter | Type | Required | Schema Default | Constraints |
| --- | --- | --- | --- | --- |
| `model_binding` | `string` | No | `"primary"` | `{"const":"primary"}` |
| `max_source_tokens` | `integer` | No | `24000` | `{"minimum":1}` |
| `timeout_seconds` | `number` | No | `300.0` | `{"exclusiveMinimum":0}` |
| `idle_timeout_seconds` | `number` | No | `60.0` | `{"exclusiveMinimum":0}` |

### sage.context.summary-store.ephemeral

In-memory conversation summaries without restart durability.

Version: `2.0.0`; scope: agent, process; ownership: `owned`。

Provides: `context.summary-store:default` (API `2`)。

No fixed configuration fields; consult the public schema for additional parameters.

### sage.context.summary-store.session-derived

Persists conversation summaries through the selected SessionStore.

Version: `2.0.0`; scope: agent, process; ownership: `owned`。

Provides: `context.summary-store:default` (API `2`)。

Dependencies: `derived-state.store`.

No fixed configuration fields; the public schema determines whether extra parameters are allowed.

### sage.context.unit-compactor.reference

Compacts oversized units into durable references instead of dropping them.

Version: `2.0.0`; scope: agent, process; ownership: `owned`。

Provides: `context.unit-compactor:default` (API `2`)。

No fixed configuration fields; consult the public schema for additional parameters.

### sage.credentials.environment

Resolves credentials from process environment variables.

Version: `2.0.0`; scope: process, tenant; ownership: `owned`。

Provides: `credentials.provider:default` (API `2`)。

| Parameter | Type | Required | Schema Default | Constraints |
| --- | --- | --- | --- | --- |
| `declarations` | `object` | No | Not declared | `{}` |
| `environment` | `['object', 'null']` | No | Not declared | `{}` |

### sage.credentials.mapping

Resolves credentials from an in-memory host-supplied mapping.

Version: `2.0.0`; scope: process, tenant; ownership: `owned`。

Provides: `credentials.provider:default` (API `2`)。

| Parameter | Type | Required | Schema Default | Constraints |
| --- | --- | --- | --- | --- |
| `values` | `object` | No | Not declared | `{}` |
| `source` | `string` | No | `"host"` | `{"minLength":1}` |

### sage.derived-state.ephemeral

Standard derived-state.store implementation with declared dependencies and lifecycle.

Version: `2.0.0`; scope: process; ownership: `owned`。

Provides: `derived-state.store:default` (API `2`)。

No fixed configuration fields; consult the public schema for additional parameters.

### sage.derived-state.session

Standard derived-state.store implementation with declared dependencies and lifecycle.

Version: `2.0.0`; scope: process; ownership: `borrowed`。

Provides: `derived-state.store:default` (API `2`)。

Dependencies: `session.store` (API `>=2,<3`)。

No fixed configuration fields; consult the public schema for additional parameters.

### sage.execution.binding.ephemeral

Independent virtual files with explicit process-local recovery limits.

Version: `1.0.0`; scope: process; ownership: `owned`。

Provides: `execution.binding:default` (API `2`)。

Dependencies: `session.store` (API `>=2,<3`)。

| Parameter | Type | Required | Schema Default | Constraints |
| --- | --- | --- | --- | --- |
| `workspace_root` | `string` | No | `"/workspace"` | `{}` |
| `policy` | `object` | No | Not declared | `{"additionalProperties":false}` |
| `policy.filesystem` | `object` | No | Not declared | `{"additionalProperties":false}` |
| `policy.filesystem.allowed_operations` | `array` | Yes | Not declared | `{}` |
| `policy.filesystem.allowed_roots` | `array` | No | `["/workspace"]` | `{}` |
| `policy.filesystem.protected_paths` | `array` | No | `[]` | `{}` |
| `policy.filesystem.max_file_bytes` | `integer / null` | No | `null` | `{}` |
| `policy.filesystem.max_total_bytes` | `integer / null` | No | `null` | `{}` |
| `policy.filesystem.allow_symlinks` | `boolean` | No | `false` | `{}` |
| `policy.process` | `object` | No | Not declared | `{"additionalProperties":false}` |
| `policy.process.enabled` | `boolean` | No | `false` | `{}` |
| `policy.process.read_only` | `boolean` | No | `false` | `{}` |
| `policy.process.allowed_executables` | `array` | No | `[]` | `{}` |
| `policy.process.allow_shell` | `boolean` | No | `false` | `{}` |
| `policy.process.allowed_env_names` | `array` | No | `[]` | `{}` |
| `policy.process.max_processes` | `integer` | No | `1` | `{"exclusiveMinimum":0}` |
| `policy.process.max_wall_time_seconds` | `number / null` | No | `null` | `{}` |
| `policy.process.max_output_bytes` | `integer` | No | `1048576` | `{"exclusiveMinimum":0}` |
| `policy.process.allow_background_jobs` | `boolean` | No | `false` | `{}` |
| `policy.resources` | `object` | No | Not declared | `{"additionalProperties":false}` |
| `policy.resources.cpu_percent` | `number` | No | `100` | `{"minimum":1}` |
| `policy.resources.memory_mb` | `integer` | No | `1024` | `{"exclusiveMinimum":0}` |
| `policy.resources.disk_mb` | `integer` | No | `4096` | `{"exclusiveMinimum":0}` |
| `policy.resources.max_processes` | `integer` | No | `64` | `{"minimum":4}` |
| `policy.resources.require_hard_limits` | `boolean` | No | `true` | `{}` |
| `policy.network` | `object` | No | Not declared | `{"additionalProperties":false}` |
| `policy.network.mode` | `string` | No | `"none"` | `{"enum":["none","allowlist","proxy","unrestricted"]}` |
| `policy.network.proxy_url` | `string / null` | No | `null` | `{}` |
| `policy.network.allowed_hosts` | `array` | No | `[]` | `{}` |
| `policy.network.allowed_ports` | `array` | No | `[]` | `{}` |
| `policy.network.allowed_schemes` | `array` | No | `["https"]` | `{}` |
| `policy.network.allowed_methods` | `array` | No | `["GET","HEAD"]` | `{}` |
| `policy.network.allowed_request_headers` | `array` | No | `["accept","content-type","user-agent"]` | `{}` |
| `policy.network.allow_listen` | `boolean` | No | `false` | `{}` |
| `policy.network.deny_private_networks` | `boolean` | No | `true` | `{}` |
| `policy.network.max_redirects` | `integer` | No | `5` | `{"minimum":0,"maximum":20}` |
| `policy.network.max_request_body_bytes` | `integer` | No | `1048576` | `{"minimum":0}` |
| `policy.network.max_response_bytes` | `integer` | No | `10485760` | `{"exclusiveMinimum":0}` |
| `policy.network.max_wall_time_seconds` | `number` | No | `30` | `{"exclusiveMinimum":0}` |

### sage.execution.binding.local-workspace

Run-owned sandbox leases with admitted execution policy.

Version: `1.0.0`; scope: process; ownership: `owned`。

Provides: `execution.binding:default` (API `2`)。

| Parameter | Type | Required | Schema Default | Constraints |
| --- | --- | --- | --- | --- |
| `workspace` | `string` | Yes | Not declared | `{}` |
| `private_workspace_root` | `string / null` | No | `null` | `{}` |
| `policy` | `object` | No | Not declared | `{"additionalProperties":false}` |
| `policy.filesystem` | `object` | No | Not declared | `{"additionalProperties":false}` |
| `policy.filesystem.allowed_operations` | `array` | Yes | Not declared | `{}` |
| `policy.filesystem.allowed_roots` | `array` | No | `["/workspace"]` | `{}` |
| `policy.filesystem.protected_paths` | `array` | No | `[]` | `{}` |
| `policy.filesystem.max_file_bytes` | `integer / null` | No | `null` | `{}` |
| `policy.filesystem.max_total_bytes` | `integer / null` | No | `null` | `{}` |
| `policy.filesystem.allow_symlinks` | `boolean` | No | `false` | `{}` |
| `policy.process` | `object` | No | Not declared | `{"additionalProperties":false}` |
| `policy.process.enabled` | `boolean` | No | `false` | `{}` |
| `policy.process.read_only` | `boolean` | No | `false` | `{}` |
| `policy.process.allowed_executables` | `array` | No | `[]` | `{}` |
| `policy.process.allow_shell` | `boolean` | No | `false` | `{}` |
| `policy.process.allowed_env_names` | `array` | No | `[]` | `{}` |
| `policy.process.max_processes` | `integer` | No | `1` | `{"exclusiveMinimum":0}` |
| `policy.process.max_wall_time_seconds` | `number / null` | No | `null` | `{}` |
| `policy.process.max_output_bytes` | `integer` | No | `1048576` | `{"exclusiveMinimum":0}` |
| `policy.process.allow_background_jobs` | `boolean` | No | `false` | `{}` |
| `policy.resources` | `object` | No | Not declared | `{"additionalProperties":false}` |
| `policy.resources.cpu_percent` | `number` | No | `100` | `{"minimum":1}` |
| `policy.resources.memory_mb` | `integer` | No | `1024` | `{"exclusiveMinimum":0}` |
| `policy.resources.disk_mb` | `integer` | No | `4096` | `{"exclusiveMinimum":0}` |
| `policy.resources.max_processes` | `integer` | No | `64` | `{"minimum":4}` |
| `policy.resources.require_hard_limits` | `boolean` | No | `true` | `{}` |
| `policy.network` | `object` | No | Not declared | `{"additionalProperties":false}` |
| `policy.network.mode` | `string` | No | `"none"` | `{"enum":["none","allowlist","proxy","unrestricted"]}` |
| `policy.network.proxy_url` | `string / null` | No | `null` | `{}` |
| `policy.network.allowed_hosts` | `array` | No | `[]` | `{}` |
| `policy.network.allowed_ports` | `array` | No | `[]` | `{}` |
| `policy.network.allowed_schemes` | `array` | No | `["https"]` | `{}` |
| `policy.network.allowed_methods` | `array` | No | `["GET","HEAD"]` | `{}` |
| `policy.network.allowed_request_headers` | `array` | No | `["accept","content-type","user-agent"]` | `{}` |
| `policy.network.allow_listen` | `boolean` | No | `false` | `{}` |
| `policy.network.deny_private_networks` | `boolean` | No | `true` | `{}` |
| `policy.network.max_redirects` | `integer` | No | `5` | `{"minimum":0,"maximum":20}` |
| `policy.network.max_request_body_bytes` | `integer` | No | `1048576` | `{"minimum":0}` |
| `policy.network.max_response_bytes` | `integer` | No | `10485760` | `{"exclusiveMinimum":0}` |
| `policy.network.max_wall_time_seconds` | `number` | No | `30` | `{"exclusiveMinimum":0}` |
| `command_path` | `string / null` | No | `null` | `{}` |
| `read_paths` | `array` | No | `[]` | `{}` |
| `isolation_python` | `string / null` | No | `null` | `{}` |
| `child_workspace_policy` | `string` | No | `"shared_parent"` | `{"enum":["shared_parent","private_child","read_only_parent"]}` |
| `linux_cgroup_root` | `string / null` | No | `null` | `{}` |
| `linux_quota_mount` | `string / null` | No | `null` | `{}` |
| `linux_execution_uid` | `integer / null` | No | `null` | `{}` |
| `linux_execution_gid` | `integer / null` | No | `null` | `{}` |

### sage.execution.environment

Authenticated identity and borrowed resources of the actual Run.

Version: `2.0.0`; scope: run; ownership: `borrowed`。

Provides: `execution.environment:default` (API `2`)。

No fixed configuration fields; consult the public schema for additional parameters.

### sage.execution.tool-runtime

Official tools bound to the accepted Run sandbox and shared services.

Version: `2.0.0`; scope: run; ownership: `owned`。

Provides: `execution.tool-runtime:default` (API `2`)。

Dependencies: `execution.environment` (API `>=2,<3`)、`execution.job-runtime` (API `>=2,<3`)、`artifact.store` (API `>=2,<3`)、`tool.selection-policy` (API `>=2,<3`)。

No fixed configuration fields; consult the public schema for additional parameters.

### sage.flow.agent

Runs a child Agent through the shared AgentLoopEngine.

Version: `2.0.0`; scope: run; ownership: `owned`。

Provides: `flow.node:agent` (API `2`)。

Dependencies: `runtime.kernel`, `agent.child-executor`.

| Parameter | Type | Required | Schema Default | Constraints |
| --- | --- | --- | --- | --- |
| `descriptor` | `object` | Yes | Not declared | `{}` |
| `workspace_policy` | `string` | No | Not declared | `{"enum":["private_child","shared_parent","read_only_parent"]}` |

### sage.job.ephemeral

Process-local background Job runtime without restart durability.

Version: `2.0.0`; scope: process; ownership: `owned`。

Provides: `execution.job-runtime:default` (API `2`)。

| Parameter | Type | Required | Schema Default | Constraints |
| --- | --- | --- | --- | --- |
| `runners` | `object` | No | Not declared | `{}` |
| `max_concurrent_jobs` | `integer` | No | `32` | `{"minimum":1}` |
| `max_admitted_jobs` | `integer` | No | `1024` | `{"minimum":1}` |
| `max_job_output_bytes` | `integer` | No | `8388608` | `{"minimum":1}` |
| `max_job_output_chunks` | `integer` | No | `8192` | `{"minimum":1}` |
| `max_buffered_output_bytes` | `integer` | No | `268435456` | `{"minimum":1}` |
| `max_buffered_output_chunks` | `integer` | No | `65536` | `{"minimum":1}` |
| `terminal_ttl_seconds` | `integer` | No | `86400` | `{"minimum":1}` |
| `max_retained_terminal_jobs` | `integer` | No | `4096` | `{"minimum":0}` |
| `max_retained_output_bytes` | `integer` | No | `268435456` | `{"minimum":0}` |
| `output_reconnect_window_seconds` | `integer` | No | `300` | `{"minimum":0}` |

### sage.logging.filesystem

Writes rotating structured operational logs to disk.

Version: `2.0.0`; scope: process; ownership: `owned`。

Provides: `observability.log-sink:default` (API `2`)。

| Parameter | Type | Required | Schema Default | Constraints |
| --- | --- | --- | --- | --- |
| `root` | `string` | Yes | Not declared | `{"minLength":1}` |
| `filename` | `string` | No | `"sage.jsonl"` | `{"minLength":1}` |
| `max_bytes` | `integer` | No | `10485760` | `{"minimum":1024}` |
| `backup_count` | `integer` | No | `5` | `{"minimum":1}` |
| `min_level` | `string` | No | `"info"` | `{"enum":["debug","info","warning","error","critical"]}` |

### sage.logging.noop

Discards structured operational logs.

Version: `2.0.0`; scope: process; ownership: `owned`。

Provides: `observability.log-sink:default` (API `2`)。

No fixed configuration fields; consult the public schema for additional parameters.

### sage.logging.stdout

Writes one JSONL or console line per record to stdout or stderr.

Version: `2.0.0`; scope: process; ownership: `owned`。

Provides: `observability.log-sink:default` (API `2`)。

| Parameter | Type | Required | Schema Default | Constraints |
| --- | --- | --- | --- | --- |
| `stream` | `string` | No | `"stdout"` | `{"enum":["stdout","stderr"]}` |
| `min_level` | `string` | No | `"info"` | `{"enum":["debug","info","warning","error","critical"]}` |
| `format` | `string` | No | `"json"` | `{"enum":["json","text"]}` |

### sage.memory.filesystem-bm25

Durable scoped Memory records with incremental SQLite FTS5 BM25 recall.

Version: `2.1.0`; scope: agent, process, tenant; ownership: `owned`。

Provides: `memory.provider:default` (API `2`)。

| Parameter | Type | Required | Schema Default | Constraints |
| --- | --- | --- | --- | --- |
| `root` | `string` | Yes | Not declared | `{"minLength":1}` |

### sage.memory.noop

Disables long-term Memory without changing Agent logic.

Version: `2.0.0`; scope: agent, process, tenant; ownership: `owned`。

Provides: `memory.provider:default` (API `2`)。

No fixed configuration fields; consult the public schema for additional parameters.

### sage.memory.recall-query.direct

Uses the current user input as the search_memory query without an additional model request.

Version: `2.0.0`; scope: agent, process, run; ownership: `owned`。

Provides: `memory.recall-query:default` (API `2`)。

No fixed configuration fields; consult the public schema for additional parameters.

### sage.memory.recall-query.llm

Uses a fast model to generate compact keywords before calling search_memory.

Version: `2.0.0`; scope: agent, run; ownership: `owned`。

Provides: `memory.recall-query:default` (API `2`)。

Dependencies: `model.provider`.

| Parameter | Type | Required | Schema Default | Constraints |
| --- | --- | --- | --- | --- |
| `language` | `string` | No | Not declared | `{}` |
| `timeout_seconds` | `number` | No | `60.0` | `{"exclusiveMinimum":0}` |

### sage.model.anthropic-messages

Uses Claude system, content-block, tool-use, and SSE semantics.

Version: `3.0.0`; scope: agent, run; ownership: `owned`。

Provides: `model.provider:anthropic-messages` (API `2`)。

Dependencies: `credentials.provider`, `model.client:default` (optional).

| Parameter | Type | Required | Schema Default | Constraints |
| --- | --- | --- | --- | --- |
| `route` | `object` | Yes | Not declared | `{}` |
| `provider_instance_id` | `string` | No | Not declared | `{}` |

### sage.model.concurrency-budget

Standard execution.model-budget implementation with declared dependencies and lifecycle.

Version: `2.0.0`; scope: process; ownership: `owned`。

Provides: `execution.model-budget:default` (API `2`)。

| Parameter | Type | Required | Schema Default | Constraints |
| --- | --- | --- | --- | --- |
| `limit` | `integer` | No | `8` | `{"exclusiveMinimum":0}` |
| `max_waiting` | `integer` | No | `128` | `{"minimum":0}` |
| `wait_timeout_seconds` | `number` | No | `60` | `{"exclusiveMinimum":0}` |

### sage.model.gemini-generate-content

Uses native Gemini Parts, function calls, thought signatures, and SSE.

Version: `1.0.0`; scope: agent, run; ownership: `owned`。

Provides: `model.provider:gemini-generate-content` (API `2`)。

Dependencies: `credentials.provider`, `model.client:default` (optional).

| Parameter | Type | Required | Schema Default | Constraints |
| --- | --- | --- | --- | --- |
| `route` | `object` | Yes | Not declared | `{}` |
| `provider_instance_id` | `string` | No | Not declared | `{}` |

### sage.model.openai-chat-completions

Streams chat messages and function calls through /chat/completions.

Version: `3.0.0`; scope: agent, run; ownership: `owned`。

Provides: `model.provider:openai-chat-completions` (API `2`)。

Dependencies: `credentials.provider`, `model.client:default` (optional).

| Parameter | Type | Required | Schema Default | Constraints |
| --- | --- | --- | --- | --- |
| `route` | `object` | Yes | Not declared | `{}` |
| `provider_instance_id` | `string` | No | Not declared | `{}` |

### sage.model.openai-responses

Uses typed input/output items and Responses streaming events.

Version: `3.0.0`; scope: agent, run; ownership: `owned`。

Provides: `model.provider:openai-responses` (API `2`)。

Dependencies: `credentials.provider`, `model.client:default` (optional).

| Parameter | Type | Required | Schema Default | Constraints |
| --- | --- | --- | --- | --- |
| `route` | `object` | Yes | Not declared | `{}` |
| `provider_instance_id` | `string` | No | Not declared | `{}` |

### sage.observability.filesystem

Writes model diagnostics under a filesystem root.

Version: `2.0.0`; scope: process; ownership: `owned`。

Provides: `observability.diagnostic-sink:default` (API `2`)。

| Parameter | Type | Required | Schema Default | Constraints |
| --- | --- | --- | --- | --- |
| `root` | `string` | Yes | Not declared | `{"minLength":1}` |
| `legacy_root` | `['string', 'null']` | No | Not declared | `{"minLength":1}` |

### sage.observability.noop

Discards model diagnostics.

Version: `2.0.0`; scope: process; ownership: `owned`。

Provides: `observability.diagnostic-sink:default` (API `2`)。

No fixed configuration fields; consult the public schema for additional parameters.

### sage.package-registry.ephemeral

Process-local AgentPackage inventory without restart durability.

Version: `2.0.0`; scope: process; ownership: `owned`。

Provides: `package.registry:default` (API `2`)。

Dependencies: `package.resolver`.

No fixed configuration fields; the public schema determines whether extra parameters are allowed.

### sage.protocol.a2a

Projects Sage events into A2A frames.

Version: `2.0.0`; scope: process, run; ownership: `owned`。

Provides: `interface.protocol-adapter:a2a` (API `2`)。

No fixed configuration fields; consult the public schema for additional parameters.

### sage.protocol.acp

Projects Sage events into ACP frames.

Version: `2.0.0`; scope: process, run; ownership: `owned`。

Provides: `interface.protocol-adapter:acp` (API `2`)。

No fixed configuration fields; consult the public schema for additional parameters.

### sage.protocol.ag-ui

Projects Sage events into AG-UI frames.

Version: `2.0.0`; scope: process, run; ownership: `owned`。

Provides: `interface.protocol-adapter:ag-ui` (API `2`)。

| Parameter | Type | Required | Schema Default | Constraints |
| --- | --- | --- | --- | --- |
| `enable_sage_extensions` | `boolean` | No | `true` | `{}` |

### sage.protocol.mcp

Projects Sage events into MCP progress and elicitation frames.

Version: `2.0.0`; scope: process, run; ownership: `owned`。

Provides: `interface.protocol-adapter:mcp` (API `2`)。

No fixed configuration fields; consult the public schema for additional parameters.

### sage.protocol.native

Exposes the native Sage event stream without protocol translation.

Version: `2.0.0`; scope: process, run; ownership: `owned`。

Provides: `interface.protocol-adapter:native` (API `2`)。

No fixed configuration fields; consult the public schema for additional parameters.

### sage.sandbox.cube-volume

Remote VM execution with a persistent Cube Volume workspace.

Version: `3.0.0`; scope: process; ownership: `owned`。

Provides: `execution.sandbox:default` (API `3`)。

| Parameter | Type | Required | Schema Default | Constraints |
| --- | --- | --- | --- | --- |
| `verification_key` | `object` | Yes | Not declared | `{}` |
| `api_url` | `string` | Yes | `""` | `{"minLength":1}` |
| `template_id` | `string` | Yes | `""` | `{"minLength":1}` |
| `proxy_node_ip` | `string` | Yes | `""` | `{"minLength":1}` |
| `api_key` | `string` | No | Not declared | `{}` |
| `volume_driver` | `string` | No | Not declared | `{}` |

### sage.sandbox.ephemeral

In-process sandbox for tests and ephemeral runs.

Version: `3.0.0`; scope: process; ownership: `owned`。

Provides: `execution.sandbox:default` (API `3`)。

Dependencies: `execution.sandbox.process-handlers:default` (optional), `execution.sandbox.network-handlers:default` (optional).

| Parameter | Type | Required | Schema Default | Constraints |
| --- | --- | --- | --- | --- |
| `verification_key` | `object` | Yes | Not declared | `{}` |
| `terminal_ttl_seconds` | `integer` | No | `86400` | `{"minimum":1}` |
| `max_retained_terminal_items` | `integer` | No | `1024` | `{"minimum":0}` |

### sage.sandbox.local-workspace

Isolates local execution with Linux cgroups/quotas or macOS Seatbelt.

Version: `3.0.0`; scope: process; ownership: `owned`。

Provides: `execution.sandbox:default` (API `3`)。

| Parameter | Type | Required | Schema Default | Constraints |
| --- | --- | --- | --- | --- |
| `verification_key` | `object` | Yes | Not declared | `{}` |
| `terminal_ttl_seconds` | `integer` | No | `86400` | `{"minimum":1}` |
| `max_retained_terminal_items` | `integer` | No | `1024` | `{"minimum":0}` |
| `network` | `object` | No | Not declared | `{"additionalProperties":true}` |
| `network.mode` | `string` | No | Not declared | `{"enum":["none","unrestricted","allowlist","proxy"]}` |
| `network.deny_private_networks` | `boolean` | No | Not declared | `{}` |
| `network.allowed_hosts` | `array` | No | Not declared | `{}` |
| `network.allowed_ports` | `array` | No | Not declared | `{}` |
| `network.allowed_schemes` | `array` | No | Not declared | `{}` |
| `network.proxy_url` | `string` | No | Not declared | `{}` |
| `command_path` | `string` | No | Not declared | `{"minLength":1}` |
| `read_paths` | `array` | No | Not declared | `{}` |
| `linux_cgroup_root` | `string` | No | Not declared | `{}` |
| `linux_quota_mount` | `string` | No | Not declared | `{}` |
| `linux_execution_uid` | `integer` | No | Not declared | `{"minimum":1}` |
| `linux_execution_gid` | `integer` | No | Not declared | `{"minimum":1}` |

### sage.scheduler.ephemeral

Process-local scheduler without restart durability.

Version: `2.0.0`; scope: process; ownership: `owned`。

Provides: `execution.scheduler:default` (API `2`)。

| Parameter | Type | Required | Schema Default | Constraints |
| --- | --- | --- | --- | --- |
| `preserve_runs_on_shutdown` | `boolean` | No | `true` | `{}` |
| `max_pending_items` | `integer` | No | `1024` | `{"minimum":1}` |
| `max_retained_terminal_items` | `integer` | No | `4096` | `{"minimum":0}` |
| `max_concurrent_runs` | `integer` | No | Not declared | `{"minimum":1}` |
| `max_concurrent_runs_per_tenant` | `integer` | No | Not declared | `{"minimum":1}` |
| `lease_seconds` | `number` | No | `172800` | `{"exclusiveMinimum":0}` |

### sage.scheduler.filesystem

Persists scheduler items on the local filesystem.

Version: `2.0.0`; scope: process; ownership: `owned`。

Provides: `execution.scheduler:default` (API `2`)。

| Parameter | Type | Required | Schema Default | Constraints |
| --- | --- | --- | --- | --- |
| `preserve_runs_on_shutdown` | `boolean` | No | `true` | `{}` |
| `max_pending_items` | `integer` | No | Not declared | `{"minimum":1}` |
| `max_retained_terminal_items` | `integer` | No | Not declared | `{"minimum":0}` |
| `max_concurrent_runs` | `integer` | No | Not declared | `{"minimum":1}` |
| `max_concurrent_runs_per_tenant` | `integer` | No | Not declared | `{"minimum":1}` |
| `lease_seconds` | `number` | No | `172800` | `{"exclusiveMinimum":0}` |
| `root` | `string` | Yes | Not declared | `{"minLength":1}` |

### sage.session-memory.noop

Disables searchable Session history without changing Agent logic.

Version: `2.0.0`; scope: agent, process; ownership: `owned`。

Provides: `session-memory.provider:default` (API `2`)。

No fixed configuration fields; consult the public schema for additional parameters.

### sage.session-memory.sqlite-bm25

Durable per-session BM25 index over canonical Session history.

Version: `2.0.0`; scope: agent, process; ownership: `owned`。

Provides: `session-memory.provider:default` (API `2`)。

| Parameter | Type | Required | Schema Default | Constraints |
| --- | --- | --- | --- | --- |
| `root` | `string` | Yes | Not declared | `{"minLength":1}` |

### sage.session.ephemeral

Full lifecycle semantics without restart durability.

Version: `2.0.0`; scope: process; ownership: `owned`。

Provides: `session.store:default` (API `2`)。

No fixed configuration fields; consult the public schema for additional parameters.

### sage.session.filesystem

Compact authoritative checksummed state per Session.

Version: `2.1.0`; scope: process; ownership: `owned`。

Provides: `session.store:default` (API `2`)。

| Parameter | Type | Required | Schema Default | Constraints |
| --- | --- | --- | --- | --- |
| `root` | `string` | Yes | Not declared | `{"minLength":1}` |

### sage.session.mysql

Durable per-Session MySQL store with appended Run events. No global Session index.

Version: `2.0.0`; scope: process; ownership: `owned`。

Provides: `session.store:default` (API `2`)。

| Parameter | Type | Required | Schema Default | Constraints |
| --- | --- | --- | --- | --- |
| `dsn` | `string` | Yes | Not declared | `{"minLength":1}` |
| `table_prefix` | `string` | No | Not declared | `{}` |

### sage.session.redis-mysql

Redis execution state shared by Sage instances, with canonical history and attachment bytes archived to MySQL. Supports multi-process writes, cross-process subscriptions and atomic worker fencing. Redis requires AOF and noeviction. Scheduling is selected independently.

Version: `3.0.0`; scope: process; ownership: `owned`。

Provides: `session.store:default` (API `2`)。

| Parameter | Type | Required | Schema Default | Constraints |
| --- | --- | --- | --- | --- |
| `dsn` | `string` | Yes | Not declared | MySQL DSN |
| `redis_url` | `string` | Yes | Not declared | Redis URL |
| `table_prefix` | `string` | No | Not declared | MySQL table namespace |
| `key_prefix` | `string` | No | Derived from MySQL identity with `:distributed` suffix | Redis namespace |
| `archive_interval_seconds` | `number` | No | `1` | Positive |
| `retention_seconds` | `integer` | No | `3600` | At least 1 |
| `coordination_ttl_seconds` | `number` | No | `30` | Positive |
| `coordination_wait_seconds` | `number` | No | `10` | Positive |
| `event_poll_seconds` | `number` | No | `0.1` | Positive |
| `max_preview_events` | `integer` | No | `2048` | At least 1 |
| `preview_retention_seconds` | `integer` | No | `300` | At least 1 |

### sage.skill.filesystem

Lazy, bounded, symlink-safe Skill catalog and source.

Version: `2.0.0`; scope: agent, process; ownership: `owned`。

Provides: `skill.catalog:filesystem` (API `2`)、`skill.source:filesystem` (API `2`)。

| Parameter | Type | Required | Schema Default | Constraints |
| --- | --- | --- | --- | --- |
| `roots` | `array` | Yes | Not declared | `{"minItems":1}` |
| `max_files` | `integer` | No | Not declared | `{"minimum":1}` |
| `max_total_bytes` | `integer` | No | Not declared | `{"minimum":1}` |

### sage.skill.loading.lazy

Loads Skill material only when it is asked for, within a character storage limit.

Version: `2.0.0`; scope: agent, run; ownership: `owned`。

Provides: `skill.loading:default` (API `2`)。

| Parameter | Type | Required | Schema Default | Constraints |
| --- | --- | --- | --- | --- |
| `max_active_characters` | `integer` | No | `24000` | `{"minimum":1}` |

### sage.skill.repository.sqlite / sage.skill.repository.memory

Version `2.0.0`; process scope. Provides `skill.management`, `skill.catalog` and `skill.source`.
SQLite stores immutable packages, current versions and durable Run pins; memory
retains them only for the process lifetime. SQLite requires `path`. Both accept
`max_files` (default 2000) and `max_total_bytes` (default 67108864). Publishing
supports `expected_version` compare-and-swap in the package transaction.

### sage.skill.workspace.readonly-mount / sage.skill.workspace.auto-sync / sage.skill.workspace.fixed-copy

Version `2.0.0`; Run scope. Provides `skill.workspace` and depends on the accepted
Run's `execution.environment`. All expose `skills/<name>/`. Auto-sync is the
default: archive local Agent modifications in hidden `.catalog`, then synchronize
manager contents without retaining manager-only history. Fixed-copy never updates
its initial working copy. Readonly-mount requires real sandbox support and fails
clearly on the current built-in backends. Parameters are `max_files` (default 2000)
and `max_total_bytes` (default 67108864). See
[Skill management and usage](sagents-skill-management-and-usage.md) for configuration
and recovery behavior.

### sage.tool-selection.direct

Sends every policy-allowed Tool to the model. Best for small catalogs.

Version: `2.0.0`; scope: agent, run; ownership: `owned`。

Provides: `tool.selection-policy:default` (API `2`)。

No fixed configuration fields; consult the public schema for additional parameters.

### sage.tool-selection.lexical

Ranks Tool names, descriptions, and parameters locally like a search engine.

Version: `2.0.0`; scope: agent, run; ownership: `owned`。

Provides: `tool.selection-policy:default` (API `2`)。

| Parameter | Type | Required | Schema Default | Constraints |
| --- | --- | --- | --- | --- |
| `max_visible_tools` | `integer` | No | `24` | `{"minimum":1,"maximum":10000}` |
| `model_timeout_seconds` | `number` | No | `60.0` | `{"maximum":120,"exclusiveMinimum":0}` |

### sage.tool-selection.llm

Uses a fast model and recent context to select relevant Tools.

Version: `2.0.0`; scope: agent, run; ownership: `owned`。

Provides: `tool.selection-policy:default` (API `2`)。

| Parameter | Type | Required | Schema Default | Constraints |
| --- | --- | --- | --- | --- |
| `max_visible_tools` | `integer` | No | `24` | `{"minimum":1,"maximum":10000}` |
| `model_timeout_seconds` | `number` | No | `60.0` | `{"maximum":120,"exclusiveMinimum":0}` |

### sage.tool-selection.recent

Keeps recently called Tools first, then fills the remaining count deterministically.

Version: `2.0.0`; scope: agent, run; ownership: `owned`。

Provides: `tool.selection-policy:default` (API `2`)。

| Parameter | Type | Required | Schema Default | Constraints |
| --- | --- | --- | --- | --- |
| `max_visible_tools` | `integer` | No | `24` | `{"minimum":1,"maximum":10000}` |
| `model_timeout_seconds` | `number` | No | `60.0` | `{"maximum":120,"exclusiveMinimum":0}` |

### sage.tool.ephemeral

In-memory Tool catalog and executor without restart durability.

Version: `2.0.0`; scope: agent, process, run; ownership: `owned`。

Provides: `tool.catalog:ephemeral` (API `2`)、`tool.executor:ephemeral` (API `2`)。

Dependencies: `tool.handlers:default` (optional).

| Parameter | Type | Required | Schema Default | Constraints |
| --- | --- | --- | --- | --- |
| `tools` | `object` | No | Not declared | `{}` |

### sage.tool.mcp

Bridges configured MCP servers into the Sage Tool catalog and executor.

Version: `2.0.0`; scope: agent, process, run; ownership: `owned`。

Provides: `tool.catalog:mcp` (API `2`)、`tool.executor:mcp` (API `2`)。

Dependencies: `mcp.session-factory:default` (optional).

| Parameter | Type | Required | Schema Default | Constraints |
| --- | --- | --- | --- | --- |
| `servers` | `array` | No | Not declared | `{}` |
| `servers[].name` | `string` | Yes | Not declared | `{"minLength":1,"maxLength":255}` |
| `servers[].protocol` | `string` | Yes | Not declared | `{"enum":["stdio","sse","streamable_http"]}` |
| `servers[].url` | `string / null` | No | `null` | `{}` |
| `servers[].api_key` | `string / null` | No | `null` | `{}` |
| `servers[].command` | `string / null` | No | `null` | `{}` |
| `servers[].args` | `array` | No | `[]` | `{}` |
| `servers[].env` | `object` | No | Not declared | `{"additionalProperties":{"type":"string"}}` |
| `servers[].timeout_seconds` | `number` | No | `30` | `{"exclusiveMinimum":0}` |
| `servers[].call_timeout_seconds` | `number` | No | `7200` | `{"exclusiveMinimum":0}` |
| `servers[].required` | `boolean` | No | `true` | `{}` |
| `servers[].max_tools` | `integer` | No | `256` | `{"maximum":10000,"exclusiveMinimum":0}` |
| `servers[].max_pages` | `integer` | No | `64` | `{"maximum":1024,"exclusiveMinimum":0}` |
| `servers[].max_schema_bytes` | `integer` | No | `262144` | `{"maximum":16777216,"exclusiveMinimum":0}` |
| `servers[].max_result_bytes` | `integer` | No | `4194304` | `{"maximum":67108864,"exclusiveMinimum":0}` |

### sage.tool.multi-agent

V2-native Fibre and Team delegation tools.

Version: `2.0.0`; scope: agent, run; ownership: `owned`。

Provides: `tool.catalog:multi-agent` (API `2`)、`tool.executor:multi-agent` (API `2`)。

Dependencies: `agent.coordinator`, `runtime.kernel`.

No fixed configuration fields; the public schema determines whether extra parameters are allowed.

### sage.tool.official

V2-native decorator-backed workspace and runtime tools.

Version: `2.0.0`; scope: run; ownership: `owned`。

Provides: `tool.catalog:official` (API `2`)、`tool.executor:official` (API `2`)。

Dependencies: `execution.tool-runtime` (API `>=2,<3`)。

No fixed configuration fields; consult the public schema for additional parameters.

### sage.tool.skill

Decorator-backed Tool operations owned by the Skill module.

Version: `2.0.0`; scope: agent, run; ownership: `owned`。

Provides: `tool.catalog:skill` (API `2`)、`tool.executor:skill` (API `2`)。

Dependencies: `skill.loader`.

| Parameter | Type | Required | Schema Default | Constraints |
| --- | --- | --- | --- | --- |
| `language` | `string` | No | Not declared | `{}` |

### sage.trace.langfuse

Exports Agent, model and tool observations to Langfuse.

Version: `2.0.0`; scope: process; ownership: `owned`。

Provides: `observability.trace-sink:default` (API `2`)。

| Parameter | Type | Required | Schema Default | Constraints |
| --- | --- | --- | --- | --- |
| `base_url` | `string` | Yes | Not declared | `{"minLength":1}` |
| `public_key_env` | `string` | No | `"LANGFUSE_PUBLIC_KEY"` | `{}` |
| `secret_key_env` | `string` | No | `"LANGFUSE_SECRET_KEY"` | `{}` |
| `service_name` | `string` | No | `"sage"` | `{}` |
| `ingestion_version` | `integer` | No | `4` | `{"enum":[3,4]}` |
| `environment` | `string` | No | `"production"` | `{}` |
| `content_mode` | `string` | No | `"redacted"` | `{"enum":["metadata","redacted"]}` |
| `max_content_chars` | `integer` | No | `16384` | `{"minimum":256,"maximum":65536}` |
| `sample_rate` | `number` | No | `1.0` | `{"minimum":0,"maximum":1}` |
| `max_queue_size` | `integer` | No | `2048` | `{"minimum":1}` |
| `max_active_spans` | `integer` | No | `4096` | `{"minimum":1}` |
| `timeout_seconds` | `number` | No | `3.0` | `{"maximum":30,"exclusiveMinimum":0}` |

### sage.trace.noop

Discards trace spans.

Version: `2.0.0`; scope: process; ownership: `owned`。

Provides: `observability.trace-sink:default` (API `2`)。

No fixed configuration fields; consult the public schema for additional parameters.

### sage.trace.otlp

Exports traces over OTLP to Jaeger or a compatible collector.

Version: `2.0.0`; scope: process; ownership: `owned`。

Provides: `observability.trace-sink:default` (API `2`)。

| Parameter | Type | Required | Schema Default | Constraints |
| --- | --- | --- | --- | --- |
| `endpoint` | `string` | No | `"http://127.0.0.1:4317"` | `{"minLength":1}` |
| `service_name` | `string` | No | `"sage"` | `{"minLength":1}` |
| `protocol` | `string` | No | `"grpc"` | `{"enum":["grpc","http"]}` |
| `insecure` | `boolean` | No | `true` | `{}` |
| `environment` | `string` | No | `"production"` | `{}` |
| `content_mode` | `string` | No | `"redacted"` | `{"enum":["metadata","redacted"]}` |
| `max_content_chars` | `integer` | No | `16384` | `{"minimum":256,"maximum":65536}` |
| `sample_rate` | `number` | No | `1.0` | `{"minimum":0,"maximum":1}` |
| `max_queue_size` | `integer` | No | `2048` | `{"minimum":1}` |
| `max_active_spans` | `integer` | No | `4096` | `{"minimum":1}` |
| `timeout_seconds` | `number` | No | `3.0` | `{"maximum":30,"exclusiveMinimum":0}` |

### sage.workspace.initializer.bare

Creates an empty workspace root without starter files.

Version: `2.0.0`; scope: agent, process; ownership: `owned`。

Provides: `workspace.initializer:default` (API `2`)。

No fixed configuration fields; consult the public schema for additional parameters.

### sage.workspace.initializer.claw

Seeds a Claw-style workspace layout and starter files.

Version: `2.0.0`; scope: agent, process; ownership: `owned`。

Provides: `workspace.initializer:default` (API `2`)。

| Parameter | Type | Required | Schema Default | Constraints |
| --- | --- | --- | --- | --- |
| `language` | `string` | No | `"en"` | `{"minLength":1}` |

## Automatic Run recovery from network failures

RunConfig.transient_retry_limit defaults to null. Retryable provider_transient/rate_limited errors in inference or request preparation retry automatically rather than asking for intervention after three failures. Set a nonnegative integer to cap consecutive retries; zero disables transparent retry. Empty semantic responses, invalid arguments, authentication failures and unknown tool effects are excluded.

Backoff is 1, 2, 4, 8… seconds, capped at 60. Each wait atomically persists step.retry_scheduled and a checkpoint with attempts and next retry time. Recovery resumes the same inference step, preserving completed tools and normal step allowance. Successful inference resets consecutive failures. Pause, cancellation and deadline_seconds still apply.

Built-in schedulers persist automatic_resume_at, return the Worker lease and tenant slot, then requeue for that time. The Run and observer completion Future remain pending. Team/Fibre members report deferred tasks through verifiable delegation IDs so an idle tree can release the root Worker; completed siblings are reused. Pause wakes waits early and cancellation settles callers. Direct Loop hosts may wait in-process. Custom schedulers implement release(..., requeue=True, available_at=...) to yield Workers.

Retryable, safely resumable provider/rate/resource failures from recovery drivers or sandbox restoration requeue with delay rather than being rewritten into terminal uncertain effects. Deadlines remain enforced. Durable queue/lease transactions settle before Worker cancellation to avoid interrupted fsync corrupting scheduler state.

RunConfig.automatic_stage_continuation defaults to true: max_steps boundaries checkpoint and reset stage step counters while continuing the same goal in the same Run/Session. History, tool results, total token usage and repetition detection persist. max_stages defaults to null and accepts a positive cap. Set automatic_stage_continuation=false for manual recovery at step limits. Deadlines, total token limits and explicit interactions remain effective.

Flow nodes keep independent checkpoints, in-process waits and explicit node boundaries. Unfinished nodes cannot be treated as completed delegation results. Automatic Worker yielding and stage continuation apply to native Agent Loops and Team/Fibre delegation trees.

Scheduler preserve_runs_on_shutdown defaults to true. Clean shutdown retains unfinished Runs/checkpoints and returns leases for takeover after restart. false restores fail-on-shutdown behavior. Filesystem Scheduler holds an exclusive writer lock; a new owner reclaims old leases immediately. A crash between checkpoint and delayed requeue recovers from the recorded wake time without waiting for the 48-hour lease.

Desktop and Server use standard App recovery of archived Agent revisions and admitted execution configuration. Set the top-level runtime field `start_workers: false` when product startup must finish before workers start, then use the public dispatcher `start()` method. No host recovery driver is installed. Existing local workspaces restore leases under their admitted owner and policy without replaying tools. Cross-process recovery requires a durable SessionStore.

Unknown writes cannot be resent as ordinary network retries. Authentication, invalid resource config, disk quota and uncertain effects require their own resolution. Recovery does not delete artifacts, raise explicit limits or claim an unverified goal complete.

MCP tools use resume_strategy=agent_recovery. Connection loss, timeout or missing response first checks local receipts. If still unknown, persist raw diagnostics, operation ID, idempotency key and arguments as a tool error for the model, without blocking for manual reconciliation. execution_outcome=unknown and recovery_action=check_status_before_retry instruct the Agent to inspect status/artifacts: reuse completed results, wait for active work, and retry only after proving no execution or safe repetition. The framework does not replay unknown writes or assume a universal MCP status API. This applies to root/child Agents and interrupted recovery without memory receipts. Explicit isError remains an ordinary failure; valid empty content is accepted, while None is not success. Other explicit manual recovery policies remain supported.

Before launch, an over-quota workspace returns sandbox.workspace_quota_exceeded with used/quota bytes and a not-executed marker. The UI shows capacity without deleting artifacts or exceeding limits. This differs from invalid requests and physically full disks.

Desktop/Server FileSystemPolicy.max_total_bytes derives from effective resources.disk_mb * 1024 * 1024 rather than a separate fixed 4 GB. CLI also derives it when omitted, preserving explicit independent limits. disk_mb still defaults to 4096; increase it deliberately, for example to 32768. Desktop uses component_configs["execution.sandbox"]["resources"]["disk_mb"].

Children inherit the parent's admitted runtime_components snapshot for creation and recovery. Global settings do not retroactively change existing Runs/sandboxes. Adopt new configuration through new Runs and sandboxes.

<a id="源码与维护"></a>

## Source and maintenance

Field contract: [runtime.py](../../../sagents/v2/package/manifest/runtime.py); defaults: [defaults.py](../../../sagents/v2/composition/defaults.py); schemas/factories: [official.py](../../../sagents/v2/runtime/extensions/official.py); precedence: [assembler.py](../../../sagents/v2/composition/assembler.py); Agent dependencies: [agent_components.py](../../../sagents/v2/composition/agent_components.py).

Update registration schemas, this reference and tests together when adding plugins or changing defaults. Registered schema does not replace provider runtime capability checks.

Some omitted options become Python None in factories even though their JSON Schema rejects explicit null. Omit those fields instead of writing field: null. Tables describing None when omitted refer to factory behavior.
