---
layout: default
title: Agent Manifest Reference
parent: Architecture
nav_order: 14
lang: en
ref: v2-detail-sagents-manifest-reference
---

{% include lang_switcher.html %}

<a id="sagents-v2-sageyaml-配置参考"></a>

# SAgents sage.yaml reference

[Host development](sagents-host-development.md) · [Runtime reference](sagents-runtime-reference.md) · [Code reading guide](code-reading-guide.md)

`sage.yaml` defines an Agent Package. **One Package defines exactly one Agent; one App can load multiple Packages.** App owns runtime and lifecycle; Packages own instructions, App model references, capabilities and budgets. Loading returns a handle without a second name-based selection.

<a id="目录"></a>

## Contents

- [Minimal configuration and loading](#最小配置与加载)
- [Files, text and paths](#文件字符串与路径)
- [Top-level fields](#顶层字段总表)
- [metadata](#metadata)
- [Model ID references](#模型-id-引用)
- [agents](#agents)
- [Budgets and policies](#预算与策略)
- [entrypoint and flows](#entrypoint-与-flows)
- [runtime and plugins](#runtime-与-plugins)
- [interfaces](#interfaces)
- [tests and environments](#tests-与-environments)
- [Subagents, reuse, updates and recovery](#子-agent复用更新与恢复)
- [Complete example](#完整配置示例)
- [Validation and common errors](#校验和常见错误)

<a id="最小配置与加载"></a>

## Minimal configuration and loading

This complete text-chat Package requires App model ID `primary`. Connection settings and credentials belong in a separate `models.yaml`.

```yaml
schema_version: sage/v2
kind: agent-package
metadata:
  id: example.assistant
  version: "1.0.0"
  name: Assistant
agents:
  main:
    name: Assistant
    instructions:
      inline: "请准确回答用户问题。需要澄清时说明缺少的信息。"
    models:
      primary: primary
entrypoint:
  agent: main
```

```python
from sagents.v2 import SAgentBuilder

app = await SAgentBuilder().build(models="./models.yaml")
try:
    agent = await app.load_agent("./agents/assistant")
    # StartRun.agent_id = agent.id
    # StartRun.resolved_spec_hash = agent.composition_hash
    # stream = await app.entrypoint().run_stream(command, context, agent=agent)
finally:
    await app.close()
```

See the [runnable starter](../../../examples/v2/host/) for commands, identity and event consumption. Offline verification needs no model API key:

```bash
.venv/bin/python -m examples.v2.host --offline
```

`main` is an internal key referenced by entrypoint.agent; metadata.id identifies the Package. The SDK loaded agent.id comes from the Package ID. Use that loaded ID in StartRun, rather than main. Desktop/Server can retain their persisted product Agent IDs; always use actual loading/admission results.

<a id="文件字符串与路径"></a>

## Files, text and paths

| Input | Call | Rule |
| --- | --- | --- |
| Package directory | `app.load_agent("./agents/assistant")` | Read sage.yaml |
| File path | `app.load_agent("./assistant.yaml")` | Load the selected file; path strings are not config text |
| Path | `app.load_agent(Path("./agents/assistant/sage.yaml"))` | Same as a path string |
| Dictionary | `app.load_agent({...})` | Validate as SageManifest |
| Validated manifest | `app.load_agent(manifest)` | Deep-copy input; later changes do not alter loaded revisions |
| YAML/JSON text | `app.load_agent(config_text=text)` | Named config_text required; root must be an object |
| In-memory file references | `app.load_agent(config_text=text, base_path=package_root)` | instructions.path must be a real file within base_path |

Provide exactly one of package and config_text. File-path input determines its own base directory and cannot also supply base_path. Low-level SageManifestLoader.load requires the filename sage.yaml; public load_agent accepts a specific manifest file.

Arbitrary strings do not expand `${VAR}`. App credential declarations resolve environment secrets. Duplicate YAML keys and unknown model fields are rejected. Explicit null must match the field type: budgets permit null, while tools should be an array or omitted.

<a id="顶层字段总表"></a>

## Top-level fields

| Field | Type | Default / required | Purpose |
| --- | --- | --- | --- |
| `schema_version` | fixed string | `sage/v2` | Schema version |
| `kind` | `agent-package` / `application` | `agent-package` | Document kind; application still obeys one Agent per Package |
| `metadata` | object | required | Package identity, version and name |
| `runtime` | RuntimeConfig | field defaults | Optional host-selected runtime; load_agent does not override App runtime |
| `plugins` | PluginDeclaration array | `[]` | Unique plugin declarations/defaults |
| `policies` | PolicyConfig | all budgets null | Package budget ceilings |
| `agents` | internal name → AgentDefinition | {} in schema; exactly one on public load | Agent definition |
| `flows` | name → FlowDefinition | `{}` | Explicit flow graphs |
| `entrypoint` | ApplicationEntrypoint | required | Package entrypoint selecting the unique Agent |
| `interfaces` | name → InterfaceDeclaration | `{}` | Protocol adapters |
| `tests` | TestDeclaration | scenarios=[], gates={} | Test metadata; not executed by loading |
| `environments` | name → overlay object | `{}` | Explicitly host-selected overlays |

Identifier is 1–192 characters, starts with a letter/digit and otherwise permits letters, digits and `._:@/-`. ToolName starts with a letter and permits letters, digits and underscores, up to 192 characters. SkillName permits spaces, but rejects `/`, `\` and NUL, also up to 192 characters. Instructions preserve surrounding whitespace; ordinary strings are generally trimmed.

## metadata

| Field | Type | Default | Meaning |
| --- | --- | --- | --- |
| `id` | Identifier | required | Stable Package ID retained on update |
| `version` | string | required | Version label; quote values such as "1.0.0" |
| `name` | string | required | Display name |
| `description` | string / null | null | Optional description |

metadata.version alone does not identify cached revisions. Resolved content and the pinned subagent graph contribute to `agent.composition_hash`. Changing version alone cannot move an old Run to new configuration.

<a id="模型-id-引用"></a>

## Model ID references

App manages routes and credentials in `models.yaml`. `sage.yaml` binds usage slots to App model IDs:

```yaml
agents:
  main:
    name: Assistant
    instructions: {inline: "准确回答问题。"}
    models: {primary: primary, fast: primary}
```

Multiple Packages may reference the same model ID. primary and fast on the left are usage slots; right-hand values identify App models. Missing models fail loading without fallback. delegation_model_bindings also references App IDs.

Top-level models and credentials are removed and rejected even when empty. Do not copy connection configuration into Packages. See [App model configuration](sagents-runtime-reference.md#app-模型配置) for fields, defaults, reasoning options, probing and updates.

## agents

Although agents remains a mapping, public Packages contain exactly one entry. Store additional Agents in separate Packages.

| AgentDefinition field | Type | Default / required | Meaning |
| --- | --- | --- | --- |
| `name` | string | required | Agent display name |
| `description` | string / null | null | Optional description |
| `instructions` | Instructions | required | Choose exactly inline or path |
| `mode` | simple / fibre / team | simple | Execution mode; subagent declarations do not grant delegation |
| `models` | slot → App model ID | `{}` | Agent model bindings |
| `delegation_model_bindings` | slot → App model ID | `{}` | Explicit child model overrides of parent Run choices |
| `entrypoint` | AgentEntrypoint | loop/react | Internal execution entrypoint |
| `tools` | ToolName array | `[]` | Tool allowlist, not an installation declaration |
| `tool_approval` | ToolApprovalConfig / null | null | Approval preference, subordinate to host authorization |
| `skills` | SkillName array | `[]` | Skill allowlist requiring catalog/source |
| `preload_skills` | SkillName array | `[]` | Preload once before first inference in each Run; subset of skills |
| `subagents` | Identifier array | `[]` | Child aliases requiring independent bound handles |
| `budgets` | AgentBudgets | all fields null | Agent budgets merged with Package ceilings |
| `memory` | AgentMemoryBehavior | see below | Memory behavior flags |
| `sandbox` | AgentSandboxConfig | network=none | Requested network scope, not execution authorization |

`preload_skills` is independent per Agent:

```yaml
skills: [python, testing]
preload_skills: [testing]
```

Parents, nested children and new Runs continuing a Session initialize their configured Skills before the first inference, including auxiliary model calls. Preloading remains within Run grants. Failures report skill.preload_failed with Agent, Run, Skill and cause. Preloaded and manually loaded Skills share a budget and can be evicted; they are not permanently resident or automatically reloaded. Call load_skill when needed. Declaration order determines initialization; later loads may evict earlier ones. A single oversized Skill fails initialization.

Resuming the same Run restores persisted initialization progress and active Skills without reloading evicted entries. Interrupted initialization resumes only unfinished work. Omitted configuration preserves lazy loading.

Instructions choose exactly one of inline and path:

```yaml
instructions:
  path: prompts/assistant.md
```

path must identify a file inside the Package. Traversal, directories and symlink escapes are rejected. Loading freezes file contents; later edits require update_agent.

| memory field | Type | Default | Meaning |
| --- | --- | --- | --- |
| `recall` | boolean | false | Enable long-term recall |
| `auto_write` | boolean | false | Enable automatic memory writes |
| `scope` | string | agent | Scope identifier constrained by host/memory service |

sandbox.network accepts none/unrestricted and defaults to none. unrestricted is a request that the host may deny. It does not configure directory mappings, keys or process grants.

ToolApprovalConfig defaults to auto_approve (or ask); tools defaults to `{}` with inherit/ask/auto_approve values. inherit uses default. null means no explicit Agent preference. Preferences cannot expand tool/model grants, sandbox scope or admitted Run permissions.

```yaml
tool_approval:
  default: ask
  tools:
    Read: auto_approve
    Execute: inherit
```

Tool names here illustrate structure; replace them with registered authorized names.

<a id="预算与策略"></a>

## Budgets and policies

policies currently contains budgets only. policies.budgets and agents.main.budgets have the same fields, defaulting to null for an unspecified bound at that layer.

| Field | Type / range | Unit | Purpose |
| --- | --- | --- | --- |
| `max_steps` | positive integer / null | steps | Agent step ceiling |
| `input_tokens` | positive integer / null | tokens | Input-context usage threshold |
| `system_tokens` | positive integer / null | tokens | System reserve |
| `protected_recent_tokens` | nonnegative integer / null | tokens | Recent-history reserve; permits zero |
| `output_tokens` | positive integer / null | tokens | Output budget |
| `total_tokens` | positive integer / null | tokens | Total token budget |
| `wall_time_seconds` | positive number / null | seconds | Execution wall-time budget |

When Package and Agent both set a bound, the smaller non-null value forms the policy ceiling, also constrained by host and Run limits. If Agent max_steps is omitted, the resolver also reads entrypoint.config.max_steps; new configs should use budgets.max_steps consistently. null does not guarantee unlimited service, and execution budgets differ from HTTP observation timeouts.

```yaml
policies:
  budgets: {max_steps: 40, total_tokens: 100000}
agents:
  main:
    name: Assistant
    instructions: {inline: "完成用户任务。"}
    budgets: {max_steps: 20}
```

This fragment demonstrates merging: the resulting max_steps ceiling is 20. It is not a standalone Package.

<a id="entrypoint-与-flows"></a>

## entrypoint and flows

The top-level schema permits exactly one agent or flow, but **public app.load_agent requires the unique Package Agent as entrypoint**. To use Flow, point that Agent's internal entrypoint at a flow rather than expecting a top-level flow to create an Agent handle.

AgentEntrypoint defaults: type=loop (or flow), loop=react (nullable), flow=null, config={}. Standard loop composition supports react. config is not an arbitrary feature registry; unsupported values need not affect execution.

```yaml
agents:
  main:
    name: Workflow
    instructions: {inline: "按显式流程执行。"}
    entrypoint: {type: flow, loop: null, flow: work}
flows:
  work:
    version: "1"
    start: done
    nodes:
      - {id: done, type: end}
entrypoint: {agent: main}
```

This flow fragment has no external node dependencies. Real tool, interaction and subflow nodes require corresponding registrations and execution contracts.

| FlowDefinition field | Type | Default | Purpose |
| --- | --- | --- | --- |
| `version` | string | required | Flow version |
| `start` | Identifier | required | Start node ID |
| `nodes` | FlowNode array | required | Node collection |
| `edges` | FlowEdge array | `[]` | Graph edges |

| FlowNode field | Type | Default | Purpose |
| --- | --- | --- | --- |
| `id` | Identifier | required | Node ID |
| `type` | agent/tool/interaction/parallel/join/subflow/end | required | Node type |
| `agent` | Identifier / null | null | Agent target; external Agents bind through load_agent subagents |
| `tool` | ToolName / null | null | Tool target |
| `interaction` | Identifier / null | null | Interaction reference |
| `flow` | Identifier / null | null | Subflow reference |
| `blocking_scope` | string / null | null | Blocking scope interpreted by node implementation |
| `config` | object | `{}` | Node-specific config; meanings differ between implementations |

FlowEdge requires from/to Identifiers, with optional when=null and integer priority=0. from/to alias source/target in Python; prefer from/to in YAML. Compilation/runtime validates conditions and graph legality. Schema validity alone does not prove nodes can execute.

<a id="runtime-与-plugins"></a>

## runtime and plugins

See the [Runtime reference](sagents-runtime-reference.md) for fields, defaults and plugin settings. load_agent uses App runtime and cannot reconfigure shared process services through later Packages. To adopt manifest.runtime, load it first and pass build(runtime=manifest.runtime).

PluginDeclaration requires id; version defaults to null and config to {}. IDs must be unique. Version declarations participate in matching/discovery, not automatic pip installation. Preregister implementations in the host.

```yaml
plugins:
  - id: example.context.reference-reducer
    config: {minimum_characters: 4}
runtime:
  capabilities:
    context.reducer:
      plugin: example.context.reference-reducer
      config: {minimum_characters: 3}
```

When the host selects this runtime and registers the plugin, selection.config value 3 overrides declaration value 4. Ordinary load_agent does not replace App runtime. Custom configuration follows schema/config_model validation and scoped lifetime; implementations remain independent.

## interfaces

```yaml
interfaces:
  chat:
    plugin: sage.protocol.ag-ui
    enabled: true
    config: {enable_sage_extensions: true}
```

| Field | Type | Default | Purpose |
| --- | --- | --- | --- |
| `plugin` | Identifier | required | Protocol adapter plugin |
| `name` | Identifier / null | null | Optional provider name |
| `enabled` | boolean | true | Enable declaration |
| `scope` | process/tenant/agent/run/null | null | Use composition default; explicit scopes must be supported |
| `config` | object | `{}` | Plugin config |

Built-in adapters include native, ag-ui, acp, a2a and mcp, named sage.protocol.<name>. Declarations do not start HTTP listeners, login services or routes. Those remain host-owned, including Server routes.

<a id="tests-与-environments"></a>

## tests and environments

TestDeclaration contains scenarios (object array, default []) and gates (object, default {}). These are metadata. load_agent does not execute tests or convert gates into production permissions or release blockers.

```yaml
environments:
  development:
    policies:
      budgets: {max_steps: 5}
    runtime:
      capabilities:
        observability.provider:
          plugin: sage.observability.local
          config: {min_level: debug}
```

Hosts select overlays explicitly:

```python
from sagents.v2.package.manifest import SageManifestLoader
manifest = SageManifestLoader().load(
    "./agents/assistant/sage.yaml", environment="development"
)
# 然后 build(runtime=manifest.runtime)，再 load_agent(manifest)。
```

Overlays may change runtime, policies and interfaces only, not agents, metadata or App models. Objects merge recursively and other values replace. Unknown environments fail. app.load_agent has no environment parameter, and process environment variables do not implicitly select overlays.

<a id="子-agent复用更新与恢复"></a>

## Subagents, reuse, updates and recovery

The parent Package still defines only main:

```yaml
agents:
  main:
    name: Coder
    instructions: {inline: "完成任务，必要时委派 reviewer 审核。"}
    mode: fibre
    subagents: [reviewer]
```

Store reviewer as a separate Package and bind its handle:

```python
reviewer = await app.load_agent("./agents/reviewer")
coder = await app.load_agent("./agents/coder", subagents={"reviewer": reviewer})
# 相同配置及绑定重复加载，复用同一个 handle。
reviewer_v2 = await app.update_agent(agent=reviewer, package="./agents/reviewer")
# 子版本更新不会静默改变父版本，明确发布父版本才采用新的 reviewer。
coder_v2 = await app.update_agent(
    agent=coder, package="./agents/coder", subagents={"reviewer": reviewer_v2}
)
```

Binding keys must exactly match declared child aliases, including external Flow Agents, with no missing or extra entries. Handles belong to the same App. Declaring subagents does not grant simple mode delegation; fibre/team still follows host, tool and authorization policies.

Managed Bundle structure differs from sage.yaml: AgentPackageBundle contains manifest, files and dependencies, with independent Bundles under dependencies. **dependencies is not a SageManifest top-level field.** The host manages file transport and source-plugin authorization.

Updates preserve Package/Agent identity. Changed Packages require update_agent; failed or stale updates leave the current revision intact. Existing handles and admitted Runs keep their revision. Recover with await app.agent_for_run(run_id, context), then pass that handle to continue_run. Missing/incompatible archives cannot be replaced with the latest Agent. Revisions currently remain until App shutdown.

<a id="完整配置示例"></a>

## Complete configuration example

This complete single-Agent declaration includes explicit budgets and a log adapter. Configure App model primary before execution and explicitly pass its runtime to build if adopting it. Tools and Skills are empty because names alone do not install implementations.

```yaml
schema_version: sage/v2
kind: agent-package
metadata:
  id: example.support
  version: "1.0.0"
  name: Support Assistant
runtime:
  deployment_profile: controlled_host
  capabilities:
    session.store:
      plugin: sage.session.filesystem
      config: {root: /srv/support/runtime}
    observability.provider:
      plugin: sage.observability.local
      config: {log_stream: stderr, log_level: info, log_format: json}
policies:
  budgets: {max_steps: 30, total_tokens: 100000, wall_time_seconds: 600}
agents:
  main:
    name: Support Assistant
    instructions: {inline: "准确回答问题；缺少事实时明确说明。"}
    mode: simple
    models: {primary: primary, fast: primary}
    tools: []
    skills: []
    budgets: {max_steps: 20, output_tokens: 4096}
    memory: {recall: false, auto_write: false, scope: agent}
    sandbox: {network: none}
entrypoint: {agent: main}
interfaces:
  chat:
    plugin: sage.protocol.ag-ui
    config: {enable_sage_extensions: true}
```

Capabilities and window sizes are example declarations rather than provider guarantees. Validate against the target model probe.

<a id="校验和常见错误"></a>

## Validation and common errors

Validate three layers, beyond YAML parsing:

1. **Structure/references:** SageManifestLoader validates fields; CompositionResolver checks model IDs, entrypoints and policies against the App catalog. Public loading enforces one Agent per Package.
2. **Composition:** preregister plugins, build, load, and inspect resolved plans/readiness. This can open storage and external services.
3. **Execution:** use the real entrypoint for chat, tools and suspension/resume. Some provider errors appear only on actual requests.

Structure-only inspection:

```python
from sagents.v2.package.manifest import SageManifestLoader
manifest = SageManifestLoader().load("./agents/assistant/sage.yaml")
assert len(manifest.agents) == 1
assert manifest.entrypoint.agent in manifest.agents
```

| Symptom | Cause / action |
| --- | --- |
| Two Agents in one Package rejected | Split Packages and bind subagents |
| Editing sage.yaml.runtime has no effect | App runtime is fixed; change host build settings while preserving recovery |
| Changed Package requires update | Expected revision protection; use current handle with update_agent |
| Instructions file missing | Check Package base; in-memory config needs base_path |
| Credential declaration exists but calls fail | Check environment/provider; declarations are not actual keys |
| Tool declared but unavailable | Provide catalog/executor, grants and a valid execution binding |
| Subagents declared but not delegated | Check mode, explicit bindings and authorization |
| Profile claims support but provider rejects | Check route_fingerprint, protocol and probe freshness |
| scope/required_guarantees rejected | Implementation lacks guarantees; do not remove validation to pretend otherwise |

Source: [manifest](../../../sagents/v2/package/manifest/), [public input parsing](../../../sagents/v2/composition/inputs.py), [child graphs](../../../sagents/v2/composition/agent_graph.py), [loading and revisions](../../../sagents/v2/composition/loaded_agents.py).
