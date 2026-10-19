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

# SAgents v2 Runtime reference

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
    plugin: sage.session.postgres
    config:
      dsn: postgresql://user:password@localhost/sage
      schema_name: sage_v2
      table_prefix: sagent
```

DSNs illustrate syntax; never commit passwords. Runtime text has no universal ${ENV} interpolation. Hosts should read secrets and build config or inject SessionStore. Postgres requires asyncpg and MySQL aiomysql. SQL storage does not make in-memory Jobs or schedulers durable/distributed.

<a id="自定义插件校验和生命周期"></a>

## Custom plugins, validation and lifecycle

Use the same registration and configuration path as built-ins; register before build:

```python
from sagents.v2 import SAgentBuilder
from examples.sagents_v2_host.plugins import compactor_registration

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

See independent [plugins.py](../../../examples/sagents_v2_host/plugins.py). Registration supplies descriptor, schema/config model, factory and optional start/stop. Depend on SDK contracts rather than other implementations; inheritance from a shared base is unnecessary.

build fixes registry/configuration and Agent loading performs composition/validation. Unknown options, missing dependencies, unavailable plugins, incompatible scope/API and unsupported guarantees must fail there. Accepted parameters alone do not prove activation. Plugin declarations do not install dependencies, and YAML does not perform arbitrary Python imports.

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

The tables cover every registered plugin, including parameterless ones. Schema-required fields are construction requirements, **not necessarily user YAML**: host objects are injected. Defaults come from registered schema and verified factories/schedulers. No fixed value means context-dependent, rather than null or disabled.

Ranges are validation constraints. Bytes and seconds are literal units. Tokens mean API output budgets or measured provider usage thresholds, without local input estimates. Strings cannot replace Python dependency objects. Registration does not mean any capability entry creates a plugin: tool/model/Flow/interface composition has dedicated paths. Check offered capabilities and consumption points.

<a id="插件索引"></a>

### Plugin index

| Capability | Built-in implementations (parameter links) |
| --- | --- |
| `agent.continuation-policy` | [sage.agent.continuation.deterministic](#sageagentcontinuationdeterministic), [sage.agent.continuation.explicit-status](#sageagentcontinuationexplicit-status), [sage.agent.continuation.hybrid](#sageagentcontinuationhybrid), [sage.agent.continuation.llm-judge](#sageagentcontinuationllm-judge) |
| `artifact.store` | [sage.artifact.ephemeral](#sageartifactephemeral), [sage.artifact.filesystem](#sageartifactfilesystem), [sage.artifact.session](#sageartifactsession) |
| `context.reducer` | [sage.context.reducer.persistent-summary](#sagecontextreducerpersistent-summary), [sage.context.reducer.window](#sagecontextreducerwindow) |
| `context.summarizer` | [sage.context.summarizer.extractive](#sagecontextsummarizerextractive), [sage.context.summarizer.model](#sagecontextsummarizermodel) |
| `context.summary-store` | [sage.context.summary-store.ephemeral](#sagecontextsummary-storeephemeral), [sage.context.summary-store.session-derived](#sagecontextsummary-storesession-derived) |
| `context.unit-compactor` | [sage.context.unit-compactor.reference](#sagecontextunit-compactorreference) |
| `credentials.provider` | [sage.credentials.environment](#sagecredentialsenvironment), [sage.credentials.mapping](#sagecredentialsmapping) |
| `execution.job-runtime` | [sage.job.ephemeral](#sagejobephemeral) |
| `execution.sandbox` | [sage.sandbox.cube-volume](#sagesandboxcube-volume), [sage.sandbox.ephemeral](#sagesandboxephemeral), [sage.sandbox.local-workspace](#sagesandboxlocal-workspace) |
| `execution.scheduler` | [sage.scheduler.ephemeral](#sageschedulerephemeral), [sage.scheduler.filesystem](#sageschedulerfilesystem) |
| `flow.node` | [sage.flow.agent](#sageflowagent) |
| `interface.protocol-adapter` | [sage.protocol.a2a](#sageprotocola2a), [sage.protocol.acp](#sageprotocolacp), [sage.protocol.ag-ui](#sageprotocolag-ui), [sage.protocol.mcp](#sageprotocolmcp), [sage.protocol.native](#sageprotocolnative) |
| `memory.provider` | [sage.memory.filesystem-bm25](#sagememoryfilesystem-bm25), [sage.memory.noop](#sagememorynoop) |
| `memory.recall-query` | [sage.memory.recall-query.direct](#sagememoryrecall-querydirect), [sage.memory.recall-query.llm](#sagememoryrecall-queryllm) |
| `model.provider` | [sage.model.anthropic-messages](#sagemodelanthropic-messages), [sage.model.gemini-generate-content](#sagemodelgemini-generate-content), [sage.model.openai-chat-completions](#sagemodelopenai-chat-completions), [sage.model.openai-responses](#sagemodelopenai-responses) |
| `observability.diagnostic-sink` | [sage.observability.filesystem](#sageobservabilityfilesystem), [sage.observability.noop](#sageobservabilitynoop) |
| `observability.log-sink` | [sage.logging.filesystem](#sageloggingfilesystem), [sage.logging.noop](#sageloggingnoop), [sage.logging.stdout](#sageloggingstdout) |
| `observability.trace-sink` | [sage.trace.langfuse](#sagetracelangfuse), [sage.trace.noop](#sagetracenoop), [sage.trace.otlp](#sagetraceotlp) |
| `package.registry` | [sage.package-registry.ephemeral](#sagepackage-registryephemeral) |
| `session-memory.provider` | [sage.session-memory.noop](#sagesession-memorynoop), [sage.session-memory.sqlite-bm25](#sagesession-memorysqlite-bm25) |
| `session.store` | [sage.session.ephemeral](#sagesessionephemeral), [sage.session.filesystem](#sagesessionfilesystem), [sage.session.mysql](#sagesessionmysql), [sage.session.postgres](#sagesessionpostgres) |
| `skill.catalog` | [sage.skill.filesystem](#sageskillfilesystem) |
| `skill.loading` | [sage.skill.loading.lazy](#sageskillloadinglazy) |
| `skill.source` | [sage.skill.filesystem](#sageskillfilesystem) |
| `tool.catalog` | [sage.tool.ephemeral](#sagetoolephemeral), [sage.tool.mcp](#sagetoolmcp), [sage.tool.multi-agent](#sagetoolmulti-agent), [sage.tool.official](#sagetoolofficial), [sage.tool.skill](#sagetoolskill) |
| `tool.executor` | [sage.tool.ephemeral](#sagetoolephemeral), [sage.tool.mcp](#sagetoolmcp), [sage.tool.multi-agent](#sagetoolmulti-agent), [sage.tool.official](#sagetoolofficial), [sage.tool.skill](#sagetoolskill) |
| `tool.selection-policy` | [sage.tool-selection.direct](#sagetool-selectiondirect), [sage.tool-selection.lexical](#sagetool-selectionlexical), [sage.tool-selection.llm](#sagetool-selectionllm), [sage.tool-selection.recent](#sagetool-selectionrecent) |
| `workspace.initializer` | [sage.workspace.initializer.bare](#sageworkspaceinitializerbare), [sage.workspace.initializer.claw](#sageworkspaceinitializerclaw) |

### sage.agent.continuation.deterministic

Applies ordered safety, budget, and completion rules without a model call.

Offers: `agent.continuation-policy:default`; scopes: agent, run.

| Parameter | Type / range | Default | Schema required | Purpose |
| --- | --- | --- | --- | --- |
| `repeat_threshold` | integer; minimum=1 | `3` | No | Repeated behavior/loop threshold |

### sage.agent.continuation.explicit-status

Completes only when the model emits an explicit turn_status.

Offers: `agent.continuation-policy:default`; scopes: agent, run.

| Parameter | Type / range | Default | Schema required | Purpose |
| --- | --- | --- | --- | --- |
| `repeat_threshold` | integer; minimum=1 | `3` | No | Repeated behavior/loop threshold |

### sage.agent.continuation.hybrid

Combines deterministic safety rules with an LLM judge for completion.

Offers: `agent.continuation-policy:default`; scopes: agent, run.

| Parameter | Type / range | Default | Schema required | Purpose |
| --- | --- | --- | --- | --- |
| `repeat_threshold` | integer; minimum=1 | `3` | No | Repeated behavior/loop threshold |
| `model` | Host object | No fixed value; requires input/injection | Yes | Model dependency, normally host ModelProvider; tokenizer model name for legacy tiktoken config |
| `model_binding` | string; minLength=1 | `"fast"` | No | Model slot; summarization is locked to primary |
| `timeout_seconds` | number; exclusiveMinimum=0 | `60.0` | No | Component-operation timeout in seconds, not total Run budget |

### sage.agent.continuation.llm-judge

Uses a judge model to decide completion when no tool call is pending.

Offers: `agent.continuation-policy:default`; scopes: agent, run.

| Parameter | Type / range | Default | Schema required | Purpose |
| --- | --- | --- | --- | --- |
| `repeat_threshold` | integer; minimum=1 | `3` | No | Repeated behavior/loop threshold |
| `model` | Host object | No fixed value; requires input/injection | Yes | Model dependency, normally host ModelProvider; tokenizer model name for legacy tiktoken config |
| `model_binding` | string; minLength=1 | `"fast"` | No | Model slot; summarization is locked to primary |
| `timeout_seconds` | number; exclusiveMinimum=0 | `60.0` | No | Component-operation timeout in seconds, not total Run budget |

### sage.artifact.ephemeral

Process-local artifact bytes without restart durability.

Offers: `artifact.store:default`; scopes: process, run.

No configurable parameters; use `config: {}`.

### sage.artifact.filesystem

Immutable binary artifact files with local restart durability.

Offers: `artifact.store:default`; scopes: process.

| Parameter | Type / range | Default | Schema required | Purpose |
| --- | --- | --- | --- | --- |
| `root` | string; minLength=1 | No fixed value; requires input/injection | Yes | Storage root; use the component-specific directory |

### sage.artifact.session

Artifacts retained by the owning Session store.

Offers: `artifact.store:default`; scopes: process.

| Parameter | Type / range | Default | Schema required | Purpose |
| --- | --- | --- | --- | --- |
| `session_store` | Host object | No fixed value; requires input/injection | Yes | Host SessionStore |

### sage.context.reducer.persistent-summary

Summarizes older units into a durable rolling conversation summary.

Offers: `context.reducer:default`; scopes: agent, run.

| Parameter | Type / range | Default | Schema required | Purpose |
| --- | --- | --- | --- | --- |
| `store` | Host object | No fixed value; requires input/injection | Yes | Host summary store |
| `summarizer` | Host object | No fixed value | No | Host summarizer |
| `summary_target_tokens` | integer; minimum=1 | `1024` | No | Target summary output tokens |
| `protected_recent_units` | integer; minimum=1 | `4` | No | Compatibility option; API recovery retains complete batches and latest user text |
| `max_summary_calls` | integer; minimum=1 | `64` | No | Summary calls per compression operation |
| `max_summary_source_tokens` | integer; minimum=1 | `24000` | No | Deprecated compatibility option; API overflow controls input splitting |
| `unit_compactor` | Host object | No fixed value | No | Host context unit compactor |

### sage.context.reducer.window

Drops complete old units only on API feedback or an exact message-count trigger.

Offers: `context.reducer:default`; scopes: agent, run.

| Parameter | Type / range | Default | Schema required | Purpose |
| --- | --- | --- | --- | --- |

### sage.context.summarizer.extractive

Preserves bounded task state and Tool outcomes without a model call.

Offers: `context.summarizer:default`; scopes: agent, process.

No configurable parameters; use `config: {}`.

### sage.context.summarizer.model

Uses a model binding to write conversation summaries.

Offers: `context.summarizer:default`; scopes: agent.

| Parameter | Type / range | Default | Schema required | Purpose |
| --- | --- | --- | --- | --- |
| `model` | Host object | No fixed value; requires input/injection | Yes | Model dependency, normally host ModelProvider; tokenizer model name for legacy tiktoken config |
| `model_binding` | string; const="primary" | `"primary"` | No | Model slot; summarization is locked to primary |
| `max_source_tokens` | integer; minimum=1 | `24000` | No | Source-token bound for one summary |
| `timeout_seconds` | number; exclusiveMinimum=0 | `300.0` | No | Component-operation timeout in seconds, not total Run budget |
| `idle_timeout_seconds` | number; exclusiveMinimum=0 | `60.0` | No | Summary stream idle timeout in seconds |

### sage.context.summary-store.ephemeral

In-memory conversation summaries without restart durability.

Offers: `context.summary-store:default`; scopes: agent, process.

No configurable parameters; use `config: {}`.

### sage.context.summary-store.session-derived

Persists conversation summaries through the selected SessionStore.

Offers: `context.summary-store:default`; scopes: agent, process.

| Parameter | Type / range | Default | Schema required | Purpose |
| --- | --- | --- | --- | --- |
| `derived_state` | Host object | No fixed value; requires input/injection | Yes | Host derived-state store |

### sage.context.unit-compactor.reference

Compacts oversized units into durable references instead of dropping them.

Offers: `context.unit-compactor:default`; scopes: agent, process.

| Parameter | Type / range | Default | Schema required | Purpose |
| --- | --- | --- | --- | --- |

### sage.credentials.environment

Resolves credentials from process environment variables.

Offers: `credentials.provider:default`; scopes: process, tenant.

| Parameter | Type / range | Default | Schema required | Purpose |
| --- | --- | --- | --- | --- |
| `declarations` | object | `{}` | No | Credential declarations, normally App model credentials |
| `environment` | object / null | Read host os.environ when omitted | No | Trace environment label; credential provider host environment map |

### sage.credentials.mapping

Resolves credentials from an in-memory host-supplied mapping.

Offers: `credentials.provider:default`; scopes: process, tenant.

| Parameter | Type / range | Default | Schema required | Purpose |
| --- | --- | --- | --- | --- |
| `values` | object | `{}` | No | Host credential value map; never hardcode secrets in public config |
| `source` | string; minLength=1 | `"host"` | No | Credential source ID |

### sage.flow.agent

Runs a child Agent through the shared AgentLoopEngine.

Offers: `flow.node:agent`; scopes: run.

| Parameter | Type / range | Default | Schema required | Purpose |
| --- | --- | --- | --- | --- |
| `runtime` | Host object | No fixed value; requires input/injection | Yes | Host RuntimePort |
| `descriptor` | Host object | No fixed value; requires input/injection | Yes | Host Agent descriptor |
| `child_executor` | Host object | No fixed value; requires input/injection | Yes | Host child-Agent executor |
| `workspace_policy` | string; enum=["private_child", "shared_parent", "read_only_parent"] | `"shared_parent"` | No | Parent/child workspace sharing policy |

### sage.job.ephemeral

Process-local background Job runtime without restart durability.

Offers: `execution.job-runtime:default`; scopes: process.

| Parameter | Type / range | Default | Schema required | Purpose |
| --- | --- | --- | --- | --- |
| `runners` | object | `{}` | No | Host background Job runner map |
| `max_concurrent_jobs` | integer; minimum=1 | `32` | No | Maximum running Jobs |
| `max_admitted_jobs` | integer; minimum=1 | `1024` | No | Maximum admitted Jobs |
| `max_job_output_bytes` | integer; minimum=1 | `8388608` | No | Output bytes per Job |
| `max_job_output_chunks` | integer; minimum=1 | `8192` | No | Output chunks per Job |
| `max_buffered_output_bytes` | integer; minimum=1 | `268435456` | No | Total buffered Job bytes |
| `max_buffered_output_chunks` | integer; minimum=1 | `65536` | No | Total buffered Job chunks |
| `terminal_ttl_seconds` | integer; minimum=1 | `86400` | No | Terminal retention seconds, not execution timeout |
| `max_retained_terminal_jobs` | integer; minimum=0 | `4096` | No | Maximum retained terminal Jobs |
| `max_retained_output_bytes` | integer; minimum=0 | `268435456` | No | Maximum retained terminal output bytes |
| `output_reconnect_window_seconds` | integer; minimum=0 | `300` | No | Output reconnection window in seconds |

### sage.logging.filesystem

Writes rotating structured operational logs to disk.

Offers: `observability.log-sink:default`; scopes: process.

| Parameter | Type / range | Default | Schema required | Purpose |
| --- | --- | --- | --- | --- |
| `root` | string; minLength=1 | No fixed value; requires input/injection | Yes | Storage root; use the component-specific directory |
| `filename` | string; minLength=1 | `"sage.jsonl"` | No | Log filename |
| `max_bytes` | integer; minimum=1024 | `10485760` | No | Log rotation size in bytes |
| `backup_count` | integer; minimum=1 | `5` | No | Rotated log backup count |
| `min_level` | string; enum=["debug", "info", "warning", "error", "critical"] | `"info"` | No | Minimum log level |

### sage.logging.noop

Discards structured operational logs.

Offers: `observability.log-sink:default`; scopes: process.

No configurable parameters; use `config: {}`.

### sage.logging.stdout

Writes one JSONL or console line per record to stdout or stderr.

Offers: `observability.log-sink:default`; scopes: process.

| Parameter | Type / range | Default | Schema required | Purpose |
| --- | --- | --- | --- | --- |
| `stream` | string; enum=["stdout", "stderr"] | `"stdout"` | No | Log output stream |
| `min_level` | string; enum=["debug", "info", "warning", "error", "critical"] | `"info"` | No | Minimum log level |
| `format` | string; enum=["json", "text"] | `"json"` | No | Log format |

### sage.memory.filesystem-bm25

Durable scoped Memory records with incremental SQLite FTS5 BM25 recall.

Offers: `memory.provider:default`; scopes: agent, process, tenant.

| Parameter | Type / range | Default | Schema required | Purpose |
| --- | --- | --- | --- | --- |
| `root` | string; minLength=1 | No fixed value; requires input/injection | Yes | Storage root; use the component-specific directory |

### sage.memory.noop

Disables long-term Memory without changing Agent logic.

Offers: `memory.provider:default`; scopes: agent, process, tenant.

No configurable parameters; use `config: {}`.

### sage.memory.recall-query.direct

Uses the current user input as the search_memory query without an additional model request.

Offers: `memory.recall-query:default`; scopes: agent, process, run.

No configurable parameters; use `config: {}`.

### sage.memory.recall-query.llm

Uses a fast model to generate compact keywords before calling search_memory.

Offers: `memory.recall-query:default`; scopes: agent, run.

| Parameter | Type / range | Default | Schema required | Purpose |
| --- | --- | --- | --- | --- |
| `model` | Host object | No fixed value; requires input/injection | Yes | Model dependency, normally host ModelProvider; tokenizer model name for legacy tiktoken config |
| `language` | string | `"en"` | No | Workspace/query/Skill prompt language |
| `timeout_seconds` | number; exclusiveMinimum=0 | `60.0` | No | Component-operation timeout in seconds, not total Run budget |

### sage.model.anthropic-messages

Uses Claude system, content-block, tool-use, and SSE semantics.

Offers: `model.provider:anthropic-messages`; scopes: agent, run.

| Parameter | Type / range | Default | Schema required | Purpose |
| --- | --- | --- | --- | --- |
| `route` | object | No fixed value; requires input/injection | Yes | Model routes from App catalog |
| `credential` | Host object | None when omitted; normally injected by host | No | Host resolved credential |
| `client` | Host object | None when omitted; protocol default client | No | Host model protocol client |
| `provider_instance_id` | string | None when omitted; generated/selected by implementation | No | Host provider instance identity |

### sage.model.gemini-generate-content

Uses native Gemini Parts, function calls, thought signatures, and SSE.

Offers: `model.provider:gemini-generate-content`; scopes: agent, run.

| Parameter | Type / range | Default | Schema required | Purpose |
| --- | --- | --- | --- | --- |
| `route` | object | No fixed value; requires input/injection | Yes | Model routes from App catalog |
| `credential` | Host object | None when omitted; normally injected by host | No | Host resolved credential |
| `client` | Host object | None when omitted; protocol default client | No | Host model protocol client |
| `provider_instance_id` | string | None when omitted; generated/selected by implementation | No | Host provider instance identity |

### sage.model.openai-chat-completions

Streams chat messages and function calls through /chat/completions.

Offers: `model.provider:openai-chat-completions`; scopes: agent, run.

| Parameter | Type / range | Default | Schema required | Purpose |
| --- | --- | --- | --- | --- |
| `route` | object | No fixed value; requires input/injection | Yes | Model routes from App catalog |
| `credential` | Host object | None when omitted; normally injected by host | No | Host resolved credential |
| `client` | Host object | None when omitted; protocol default client | No | Host model protocol client |
| `provider_instance_id` | string | None when omitted; generated/selected by implementation | No | Host provider instance identity |

### sage.model.openai-responses

Uses typed input/output items and Responses streaming events.

Offers: `model.provider:openai-responses`; scopes: agent, run.

| Parameter | Type / range | Default | Schema required | Purpose |
| --- | --- | --- | --- | --- |
| `route` | object | No fixed value; requires input/injection | Yes | Model routes from App catalog |
| `credential` | Host object | None when omitted; normally injected by host | No | Host resolved credential |
| `client` | Host object | None when omitted; protocol default client | No | Host model protocol client |
| `provider_instance_id` | string | None when omitted; generated/selected by implementation | No | Host provider instance identity |

### sage.observability.filesystem

Writes model diagnostics under a filesystem root.

Offers: `observability.diagnostic-sink:default`; scopes: process.

| Parameter | Type / range | Default | Schema required | Purpose |
| --- | --- | --- | --- | --- |
| `root` | string; minLength=1 | No fixed value; requires input/injection | Yes | Storage root; use the component-specific directory |
| `legacy_root` | string / null; minLength=1 | None when omitted; no legacy directory | No | Legacy diagnostic read path |

### sage.observability.noop

Discards model diagnostics.

Offers: `observability.diagnostic-sink:default`; scopes: process.

No configurable parameters; use `config: {}`.

### sage.package-registry.ephemeral

Process-local AgentPackage inventory without restart durability.

Offers: `package.registry:default`; scopes: process.

Use config: {}. resolver is an injected dependency, not YAML. The shared entrypoint binds it to the current App model catalog so new Packages validate against the same models.

### sage.protocol.a2a

Projects Sage events into A2A frames.

Offers: `interface.protocol-adapter:a2a`; scopes: process, run.

No configurable parameters; use `config: {}`.

### sage.protocol.acp

Projects Sage events into ACP frames.

Offers: `interface.protocol-adapter:acp`; scopes: process, run.

No configurable parameters; use `config: {}`.

### sage.protocol.ag-ui

Projects Sage events into AG-UI frames.

Offers: `interface.protocol-adapter:ag-ui`; scopes: process, run.

| Parameter | Type / range | Default | Schema required | Purpose |
| --- | --- | --- | --- | --- |
| `enable_sage_extensions` | boolean | `true` | No | Expose Sage extension events in AG-UI |

### sage.protocol.mcp

Projects Sage events into MCP progress and elicitation frames.

Offers: `interface.protocol-adapter:mcp`; scopes: process, run.

No configurable parameters; use `config: {}`.

### sage.protocol.native

Exposes the native Sage event stream without protocol translation.

Offers: `interface.protocol-adapter:native`; scopes: process, run.

No configurable parameters; use `config: {}`.

### sage.sandbox.cube-volume

Remote VM execution with a persistent Cube Volume workspace.

Offers: `execution.sandbox:default`; scopes: process.

| Parameter | Type / range | Default | Schema required | Purpose |
| --- | --- | --- | --- | --- |
| `verification_key` | Host object | No fixed value; requires input/injection | Yes | Host object/private verification key; keep out of shared Packages |
| `api_url` | string; minLength=1 | `""`; still requires input/injection | Yes | Cube service address |
| `template_id` | string; minLength=1 | `""`; still requires input/injection | Yes | Valid nonempty Cube template ID |
| `proxy_node_ip` | string; minLength=1 | `""`; still requires input/injection | Yes | Nonempty Cube proxy node address |
| `api_key` | string | None when omitted | No | Private connection credential; never commit real values |
| `volume_driver` | string | None when omitted | No | Cube volume driver options |

Empty constructor placeholders for address/template fields fail nonempty schema constraints. Hosts must supply actual values.

### sage.sandbox.ephemeral

In-process sandbox for tests and ephemeral runs.

Offers: `execution.sandbox:default`; scopes: process.

| Parameter | Type / range | Default | Schema required | Purpose |
| --- | --- | --- | --- | --- |
| `verification_key` | Host object | No fixed value; requires input/injection | Yes | Host object/private verification key; keep out of shared Packages |
| `terminal_ttl_seconds` | integer; minimum=1 | `86400` | No | Terminal retention seconds, not execution timeout |
| `max_retained_terminal_items` | integer; minimum=0 | `1024` | No | Maximum retained terminal scheduler/sandbox entries |
| `process_handlers` | object | None when omitted; implementation uses an empty map | No | Host process-handler map for memory sandbox |
| `network_handlers` | object | None when omitted; implementation uses an empty map | No | Host network-handler map for memory sandbox |

### sage.sandbox.local-workspace

Isolates local execution with Linux cgroups/quotas or macOS Seatbelt.

Offers: `execution.sandbox:default`; scopes: process.

| Parameter | Type / range | Default | Schema required | Purpose |
| --- | --- | --- | --- | --- |
| `verification_key` | Host object | No fixed value; requires input/injection | Yes | Host object/private verification key; keep out of shared Packages |
| `terminal_ttl_seconds` | integer; minimum=1 | `86400` | No | Terminal retention seconds, not execution timeout |
| `max_retained_terminal_items` | integer; minimum=0 | `1024` | No | Maximum retained terminal scheduler/sandbox entries |
| `network` | object | Not consumed by current factory | No | Network config not passed by local plugin factory; execution bindings grant network policy |
| `command_path` | string; minLength=1 | os.environ[PATH] or os.defpath when omitted | No | Sandbox command-search PATH |
| `read_paths` | array | Empty tuple when omitted | No | Host-authorized additional read paths |
| `linux_cgroup_root` | string | None when omitted | No | Linux cgroup resource root |
| `linux_quota_mount` | string | None when omitted | No | Linux quota mount |
| `linux_execution_uid` | integer; minimum=1 | None when omitted | No | Linux execution UID |
| `linux_execution_gid` | integer; minimum=1 | None when omitted | No | Linux execution GID |

The network schema is shown below, but the current factory does not consume it as authorization. Configure network policy through the host execution binding.

| Parameter | Type / range | Default | Schema required | Purpose |
| --- | --- | --- | --- | --- |
| `mode` | string; enum=["none", "unrestricted", "allowlist", "proxy"] | No fixed value | No | Network mode |
| `deny_private_networks` | boolean | No fixed value | No | Deny private network targets |
| `allowed_hosts` | array | No fixed value | No | Allowed hosts |
| `allowed_ports` | array | No fixed value | No | Allowed ports |
| `allowed_schemes` | array | No fixed value | No | Allowed URL schemes |
| `proxy_url` | string | No fixed value | No | Network proxy URL |

### sage.scheduler.ephemeral

Process-local scheduler without restart durability.

Offers: `execution.scheduler:default`; scopes: process.

| Parameter | Type / range | Default | Schema required | Purpose |
| --- | --- | --- | --- | --- |
| `max_pending_items` | integer; minimum=1 | `1024` | No | Pending scheduler queue limit |
| `max_retained_terminal_items` | integer; minimum=0 | `4096` | No | Maximum retained terminal scheduler/sandbox entries |
| `max_concurrent_runs` | integer; minimum=1 | `8` | No | Maximum concurrent App Runs |
| `max_concurrent_runs_per_tenant` | integer; minimum=1 | `2` | No | Maximum concurrent Runs per tenant |
| `lease_seconds` | number; exclusiveMinimum=0 | `172800` (48 hours) | No | Execution lease seconds; dispatcher renews periodically |

### sage.scheduler.filesystem

Persists scheduler items on the local filesystem.

Offers: `execution.scheduler:default`; scopes: process.

| Parameter | Type / range | Default | Schema required | Purpose |
| --- | --- | --- | --- | --- |
| `max_pending_items` | integer; minimum=1 | `1024` | No | Pending scheduler queue limit |
| `max_retained_terminal_items` | integer; minimum=0 | `4096` | No | Maximum retained terminal scheduler/sandbox entries |
| `max_concurrent_runs` | integer; minimum=1 | `8` | No | Maximum concurrent App Runs |
| `max_concurrent_runs_per_tenant` | integer; minimum=1 | `2` | No | Maximum concurrent Runs per tenant |
| `lease_seconds` | number; exclusiveMinimum=0 | `172800` (48 hours) | No | Execution lease seconds; dispatcher renews periodically |
| `root` | string; minLength=1 | No fixed value; requires input/injection | Yes | Storage root; use the component-specific directory |

### sage.session-memory.noop

Disables searchable Session history without changing Agent logic.

Offers: `session-memory.provider:default`; scopes: agent, process.

No configurable parameters; use `config: {}`.

### sage.session-memory.sqlite-bm25

Durable per-session BM25 index over canonical Session history.

Offers: `session-memory.provider:default`; scopes: agent, process.

| Parameter | Type / range | Default | Schema required | Purpose |
| --- | --- | --- | --- | --- |
| `root` | string; minLength=1 | No fixed value; requires input/injection | Yes | Storage root; use the component-specific directory |

### sage.session.ephemeral

Full lifecycle semantics without restart durability.

Offers: `session.store:default`; scopes: process.

No configurable parameters; use `config: {}`.

### sage.session.filesystem

Compact authoritative checksummed state per Session.

Offers: `session.store:default`; scopes: process.

| Parameter | Type / range | Default | Schema required | Purpose |
| --- | --- | --- | --- | --- |
| `root` | string; minLength=1 | No fixed value; requires input/injection | Yes | Storage root; use the component-specific directory |

### sage.session.mysql

Durable per-Session MySQL store with appended Run events. No global Session index.

Offers: `session.store:default`; scopes: process.

| Parameter | Type / range | Default | Schema required | Purpose |
| --- | --- | --- | --- | --- |
| `dsn` | string; minLength=1 | No fixed value; requires input/injection | Yes | Database connection string |
| `table_prefix` | string | `"sagent"` | No | Database table prefix |

### sage.session.postgres

Durable per-Session PostgreSQL store with appended Run events. Single-process writers; no global Session index.

Offers: `session.store:default`; scopes: process.

| Parameter | Type / range | Default | Schema required | Purpose |
| --- | --- | --- | --- | --- |
| `dsn` | string; minLength=1 | No fixed value; requires input/injection | Yes | Database connection string |
| `schema_name` | string; minLength=1 | `"sage_v2"` | No | Postgres schema name |
| `table_prefix` | string; minLength=1 | `"sagent"` | No | Database table prefix |

### sage.skill.filesystem

Lazy, bounded, symlink-safe Skill catalog and source.

Offers: `skill.catalog:filesystem`、`skill.source:filesystem`; scopes: agent, process.

| Parameter | Type / range | Default | Schema required | Purpose |
| --- | --- | --- | --- | --- |
| `roots` | array; minItems=1 | No fixed value; requires input/injection | Yes | Skill search root directories |
| `max_files` | integer; minimum=1 | `2000` | No | Maximum discovered/read Skill files |
| `max_total_bytes` | integer; minimum=1 | `67108864` | No | Total Skill file bytes |

### sage.skill.loading.lazy

Loads Skill material only when it is asked for, within a token budget.

Offers: `skill.loading:default`; scopes: agent, run.

| Parameter | Type / range | Default | Schema required | Purpose |
| --- | --- | --- | --- | --- |
| `max_active_characters` | integer; minimum=1 | `24000` | No | Exact active Skill content character limit |

### sage.tool-selection.direct

Sends every policy-allowed Tool to the model. Best for small catalogs.

Offers: `tool.selection-policy:default`; scopes: agent, run.

No configurable parameters; use `config: {}`.

### sage.tool-selection.lexical

Ranks Tool names, descriptions, and parameters locally like a search engine.

Offers: `tool.selection-policy:default`; scopes: agent, run.

| Parameter | Type / range | Default | Schema required | Purpose |
| --- | --- | --- | --- | --- |
| `max_visible_tools` | integer; minimum=1, maximum=10000 | `24` | No | Maximum full tool schemas visible to the model |
| `model_timeout_seconds` | number; exclusiveMinimum=0, maximum=120 | `60.0` | No | Auxiliary tool-selection timeout in seconds |

### sage.tool-selection.llm

Uses a fast model and recent context to select relevant Tools.

Offers: `tool.selection-policy:default`; scopes: agent, run.

| Parameter | Type / range | Default | Schema required | Purpose |
| --- | --- | --- | --- | --- |
| `max_visible_tools` | integer; minimum=1, maximum=10000 | `24` | No | Maximum full tool schemas visible to the model |
| `model_timeout_seconds` | number; exclusiveMinimum=0, maximum=120 | `60.0` | No | Auxiliary tool-selection timeout in seconds |

### sage.tool-selection.recent

Keeps recently called Tools first, then fills the remaining count deterministically.

Offers: `tool.selection-policy:default`; scopes: agent, run.

| Parameter | Type / range | Default | Schema required | Purpose |
| --- | --- | --- | --- | --- |
| `max_visible_tools` | integer; minimum=1, maximum=10000 | `24` | No | Maximum full tool schemas visible to the model |
| `model_timeout_seconds` | number; exclusiveMinimum=0, maximum=120 | `60.0` | No | Auxiliary tool-selection timeout in seconds |

### sage.tool.ephemeral

In-memory Tool catalog and executor without restart durability.

Offers: `tool.catalog:ephemeral`、`tool.executor:ephemeral`; scopes: agent, process, run.

| Parameter | Type / range | Default | Schema required | Purpose |
| --- | --- | --- | --- | --- |
| `tools` | Host object | `[]` | No | Host tool definitions |
| `handlers` | Host object | `{}` | No | Host tool-handler map |

### sage.tool.mcp

Bridges configured MCP servers into the Sage Tool catalog and executor.

Offers: `tool.catalog:mcp`、`tool.executor:mcp`; scopes: agent, process.

| Parameter | Type / range | Default | Schema required | Purpose |
| --- | --- | --- | --- | --- |
| `servers` | array | `[]` | No | MCP servers; nested fields below |
| `session_factory` | Host object | None when omitted; default session factory | No | Host MCP session factory |

Complete servers[] fields:

| Parameter | Type / range | Default | Schema required | Purpose |
| --- | --- | --- | --- | --- |
| `name` | string; minLength=1, maxLength=255 | No fixed value; requires input/injection | Yes | Unique MCP server name |
| `protocol` | string; enum=["stdio", "sse", "streamable_http"] | No fixed value; requires input/injection | Yes | OTLP protocol or MCP transport |
| `url` | string / null | `null` | No | HTTP/SSE MCP server URL |
| `api_key` | string / null | `null` | No | Private connection credential; never commit real values |
| `command` | string / null | `null` | No | stdio MCP command |
| `args` | array | `[]` | No | stdio argument array |
| `env` | object | `{}` | No | stdio subprocess environment map |
| `timeout_seconds` | number; exclusiveMinimum=0 | `30` | No | MCP connection, initialization and discovery timeout in seconds, excluding tool execution |
| `call_timeout_seconds` | number / null; exclusiveMinimum=0 | `null` | No | Tool execution timeout in seconds; default waits until completion with cancellation. HTTP/SSE read timeout follows this value rather than interrupting long tasks |
| `required` | boolean | `true` | No | Whether this MCP server is required |
| `max_tools` | integer; exclusiveMinimum=0, maximum=10000 | `256` | No | Discovered tool limit |
| `max_pages` | integer; exclusiveMinimum=0, maximum=1024 | `64` | No | Discovery page limit |
| `max_schema_bytes` | integer; exclusiveMinimum=0, maximum=16777216 | `262144` | No | Tool schema byte limit |
| `max_result_bytes` | integer; exclusiveMinimum=0, maximum=67108864 | `4194304` | No | Tool result byte limit |

env defaults to {}. stdio requires command; HTTP/SSE requires url. Transport-specific validation also applies.

### sage.tool.multi-agent

V2-native Fibre and Team delegation tools.

Offers: `tool.catalog:multi-agent`、`tool.executor:multi-agent`; scopes: agent, run.

| Parameter | Type / range | Default | Schema required | Purpose |
| --- | --- | --- | --- | --- |
| `coordinator` | Host object | No fixed value; requires input/injection | Yes | Host multi-Agent coordinator |
| `runtime` | Host object | No fixed value; requires input/injection | Yes | Host RuntimePort |

### sage.tool.official

V2-native decorator-backed workspace and runtime tools.

Offers: `tool.catalog:official`、`tool.executor:official`; scopes: agent, process, run.

| Parameter | Type / range | Default | Schema required | Purpose |
| --- | --- | --- | --- | --- |
| `runtime` | Host object | No fixed value; requires input/injection | Yes | Host RuntimePort |

### sage.tool.skill

Decorator-backed Tool operations owned by the Skill module.

Offers: `tool.catalog:skill`、`tool.executor:skill`; scopes: agent, run.

| Parameter | Type / range | Default | Schema required | Purpose |
| --- | --- | --- | --- | --- |
| `loader` | Host object | No fixed value; requires input/injection | Yes | Host SkillLoader |
| `language` | string | None when omitted; resolved by prompt-language rules | No | Workspace/query/Skill prompt language |

### sage.trace.langfuse

Exports Agent, model and tool observations to Langfuse.

Offers: `observability.trace-sink:default`; scopes: process.

| Parameter | Type / range | Default | Schema required | Purpose |
| --- | --- | --- | --- | --- |
| `base_url` | string; minLength=1 | No fixed value; requires input/injection | Yes | Service endpoint |
| `public_key_env` | string | `"LANGFUSE_PUBLIC_KEY"` | No | Public-key environment variable name |
| `secret_key_env` | string | `"LANGFUSE_SECRET_KEY"` | No | Secret-key environment variable name |
| `service_name` | string | `"sage"` | No | Trace service name |
| `ingestion_version` | integer; enum=[3, 4] | `4` | No | Langfuse ingestion protocol version |
| `environment` | string | `"production"` | No | Trace environment label; credential provider host environment map |
| `content_mode` | string; enum=["metadata", "redacted"] | `"redacted"` | No | metadata records metadata only; redacted records sanitized content |
| `max_content_chars` | integer; minimum=256, maximum=65536 | `16384` | No | Trace content character limit |
| `sample_rate` | number; minimum=0, maximum=1 | `1.0` | No | Trace sampling ratio 0–1 |
| `max_queue_size` | integer; minimum=1 | `2048` | No | Trace export queue limit |
| `max_active_spans` | integer; minimum=1 | `4096` | No | Maximum active Trace spans |
| `timeout_seconds` | number; exclusiveMinimum=0, maximum=30 | `3.0` | No | Component-operation timeout in seconds, not total Run budget |

### sage.trace.noop

Discards trace spans.

Offers: `observability.trace-sink:default`; scopes: process.

No configurable parameters; use `config: {}`.

### sage.trace.otlp

Exports traces over OTLP to Jaeger or a compatible collector.

Offers: `observability.trace-sink:default`; scopes: process.

| Parameter | Type / range | Default | Schema required | Purpose |
| --- | --- | --- | --- | --- |
| `endpoint` | string; minLength=1 | `"http://127.0.0.1:4317"` | No | OTLP collector endpoint |
| `service_name` | string; minLength=1 | `"sage"` | No | Trace service name |
| `protocol` | string; enum=["grpc", "http"] | `"grpc"` | No | OTLP protocol or MCP transport |
| `insecure` | boolean | `true` | No | Use non-TLS OTLP connection |
| `environment` | string | `"production"` | No | Trace environment label; credential provider host environment map |
| `content_mode` | string; enum=["metadata", "redacted"] | `"redacted"` | No | metadata records metadata only; redacted records sanitized content |
| `max_content_chars` | integer; minimum=256, maximum=65536 | `16384` | No | Trace content character limit |
| `sample_rate` | number; minimum=0, maximum=1 | `1.0` | No | Trace sampling ratio 0–1 |
| `max_queue_size` | integer; minimum=1 | `2048` | No | Trace export queue limit |
| `max_active_spans` | integer; minimum=1 | `4096` | No | Maximum active Trace spans |
| `timeout_seconds` | number; exclusiveMinimum=0, maximum=30 | `3.0` | No | Component-operation timeout in seconds, not total Run budget |

### sage.workspace.initializer.bare

Creates an empty workspace root without starter files.

Offers: `workspace.initializer:default`; scopes: agent, process.

No configurable parameters; use `config: {}`.

### sage.workspace.initializer.claw

Seeds a Claw-style workspace layout and starter files.

Offers: `workspace.initializer:default`; scopes: agent, process.

| Parameter | Type / range | Default | Schema required | Purpose |
| --- | --- | --- | --- | --- |
| `language` | string; minLength=1 | `"en"` | No | Workspace/query/Skill prompt language |

<a id="run-的网络故障自动恢复"></a>

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
