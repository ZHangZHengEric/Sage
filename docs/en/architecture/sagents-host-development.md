<a id="基于-sagents-v2-开发宿主项目"></a>

# Developing a host with SAgents v2

[English](../../en/architecture/sagents-host-development.md) · [Code reading guide](code-reading-guide.md) · [Runnable starter](../../../examples/sagents_v2_host/)

**Start with one composition root, one Agent manifest and shared Run correlation identifiers.**

[This guide](sagents-host-development.md) covers integration, debugging and custom plugin contracts. The [Runtime reference](sagents-runtime-reference.md) lists component parameters and defaults; the [sage.yaml reference](sagents-manifest-reference.md) covers all Agent Package fields.

For custom plugins, start with the [protocol inventory](#哪些模块支持插件各自是什么协议) and [complete example](#一个完整独立的插件). CLI, HTTP and desktop hosts may differ in product behavior while sharing model budgets, plugin loading, Session history and recovery. Command-line flags in this guide belong to the starter, rather than global SDK environment settings.

<a id="现在的开发入口"></a>

## Current entry points

```text
SAgentBuilder.build(runtime=..., models=...) → App
    ↓ app.load_agent(Package)       一个 Package 一个 Agent，加载结果可复用
    ↓ app.entrypoint().run_stream(command, context, agent=agent)
    ↓ stream.events / stream.wait()
    ↓ app.update_agent(agent=agent, package=...)  发布新版本
await app.close()                   统一关闭所有版本及资源
```

The starter separates responsibilities:

| File | Responsibility |
| --- | --- |
| [sage.yaml](../../../examples/sagents_v2_host/sage.yaml) | Versioned Agent configuration referencing App model IDs |
| [models.yaml](../../../examples/sagents_v2_host/models.yaml) | App model routes, request options, capabilities and credential references |
| [plugins.py](../../../examples/sagents_v2_host/plugins.py) | Independent plugin implementation, config model and registration |
| [bootstrap.py](../../../examples/sagents_v2_host/bootstrap.py) | HostSettings, loading, Builder and host injection |
| [__main__.py](../../../examples/sagents_v2_host/__main__.py) | CLI arguments, actor identity, StartRun, events and shutdown |

The core call sequence is:

```python
app = await build_application(settings)
try:
    agent = app.loaded_agents[0]  # bootstrap 中 load_agent 的结果
    stream = await app.entrypoint().run_stream(command, context, agent=agent)
    async for event in stream.events:
        render(event)
    result = await stream.wait()
finally:
    await app.close()
```

This snippet illustrates host wiring; the starter contains the executable implementation. Long-lived services create one Application at startup and close it at shutdown, reusing it across HTTP requests. Generate `RequestContext` after host authentication; client-supplied principal and tenant values are untrusted.

<a id="app模型和-agent-的边界"></a>

## App, model and Agent boundaries

| Configuration | Owner | Contents |
| --- | --- | --- |
| runtime.yaml | App | Storage, execution and observability component choices |
| models.yaml | App | Model IDs, protocols, connections, credentials, options, capabilities and limits |
| sage.yaml | One Agent Package | Instructions, model IDs, tools, Skills, budgets and subagent declarations |

Desktop converts model settings into an App model catalog. Server injects the catalog authorized for the current user. CLI accepts `--models ./models.yaml`, and TUI reuses CLI. Hosts retain their authentication, secrets and persistence; third-party integrations need not reproduce those product services.

See [App model configuration](sagents-runtime-reference.md#app-模型配置) for fields and update APIs. Runtime updates use `update_models` / `update_model` on App. Builder does not manage live state. A custom model plugin implements `model.provider`, is registered in advance and is selected through the model configuration's `plugin`; it does not inherit Desktop or Server implementations.

<a id="加载输入复用和更新"></a>

## Loading inputs, reuse and updates

```python
from pathlib import Path
from sagents.v2 import SAgentBuilder

app = await SAgentBuilder().with_defaults(session_root="./runtime").build(models="./models.yaml")
try:
    agent = await app.load_agent("./agents/assistant")  # 目录中的 sage.yaml
    # 也支持 Path("./assistant.yaml")、SageManifest 或配置字典。
    # 文本显式写为 app.load_agent(config_text=yaml_or_json, base_path=package_root)。
    # runtime 同样支持 RuntimeConfig、字典、路径，文本使用 runtime_config_text=。
    newer = await app.update_agent(agent=agent, package="./agents/assistant")
finally:
    await app.close()
```

Path strings are never guessed to be YAML. `package` / `config_text`, `runtime` / `runtime_config_text`, and `models` / `models_config_text` are mutually exclusive pairs. In-memory instructions referencing files require `base_path`, and files cannot escape it. Each Package defines exactly one Agent. SDK `agent.id` comes from the Package ID, so separate Packages may both use the internal name main. Commands use the loaded `agent.id` and `agent.composition_hash` for `StartRun.agent_id` and `resolved_spec_hash`; the entrypoint validates both.

Loading identical Package and model configuration reuses a handle. After updating the App model catalog, load the original Package again to obtain a new revision; Package edits require explicit update. Updates preserve logical identity and return a new handle. Existing handles and admitted Runs keep their revision. Invalid or stale concurrent updates leave the current revision intact. App owns the dispatcher and all revisions, stopping dispatch before closing revisions and shared storage. Revisions remain until shutdown; frequent updates require memory planning.

The local SDK persists resolved snapshots under `agent-revisions/` in the runtime root and restores original revisions after restart. For manual continuation, obtain the authorized original handle with `await app.agent_for_run(run_id, context)` and pass it to `entrypoint().continue_run(..., agent=agent)`. Missing or incompatible snapshots cannot be replaced by current Packages. Retain snapshots with Session data and treat them as private configuration. This is local persistence, rather than a distributed registry. Desktop and Server inject `HostAgentExecution` and recover their persisted admission contracts; each Run driver still owns its model, sandbox and grants. Reusing loaded handles does not reuse Run resources. `build(package)` is removed and public loading rejects multi-Agent Packages. Every host uses build → load_agent → explicit execution.

Load child Packages independently, then bind them by the names declared in the parent:

```python
reviewer = await app.load_agent("./agents/reviewer")
coder = await app.load_agent("./agents/coder", subagents={"reviewer": reviewer})
```

Default delegation passes only the task message. Without `child_session_id`, it starts an independent serial Session whose first user message is the parent's task. With a child Session ID, it appends a user task while retaining that child's own history. Parent Run/tool identifiers and Session ancestry support tracing, routing and layout; they do not copy parent history or attachments. Provide required background and references in `content`. `original_task` is tracing metadata, not an implicit child message. Explicit low-level `FORK` retains its snapshot behavior and is not the default.

Bindings pin exact revisions. Updating reviewer does not change an already loaded coder; adopt it explicitly with `app.update_agent(agent=coder, package="./agents/coder", subagents={"reviewer": updated_reviewer})`. Internal recovery snapshots preserve the complete graph. Public Packages still define one Agent. Managed `AgentPackageBundle.dependencies` persists independent child Packages loaded through the same API.

CLI presets follow this loading path; TUI uses the same implementation through `sage v2 chat --json`.

<a id="先离线跑通再接真实模型"></a>

## Start offline, then connect a real model

Run from the repository root with Python 3.12+:

```bash
# 打印真实装配计划与 readiness；不创建或执行 Run
.venv/bin/python -m examples.sagents_v2_host --offline --inspect

# 跑完一个确定性 Run，不需要模型 API Key，也不调用网络
.venv/bin/python -m examples.sagents_v2_host --offline

# 相同入口切换调试级别、运行数据目录
.venv/bin/python -m examples.sagents_v2_host --offline --log-level debug --runtime-root /tmp/my-sagents-debug
```

For a real model, configure provider/base_url/model in the starter model catalog, provide `MODEL_API_KEY` and omit `--offline`. Invalid model names or gateways do not trigger an implementation fallback. Scripted models are for development and must not resume Runs admitted against real models.

`--inspect` builds App, opens configured services, checks readiness and closes App. It is not an I/O-free YAML validator. Offline mode replaces the model port only. The default starter has no network tools; edited manifests may introduce network activity.

<a id="配置应放在哪里"></a>

## Where configuration belongs

| Setting | Location | Examples |
| --- | --- | --- |
| Agent definition | `sage.yaml` | Instructions, models, tool/Skill allowlists and budgets |
| Capabilities | App runtime.capabilities and Package plugins | Plugin IDs, scopes and config; pass selected manifest.runtime to build |
| Host deployment | HostSettings / host config | Runtime root, log level and configuration paths |
| Host objects | Builder.with_*() in one bootstrap | SessionStore, model budget, bindings and diagnostic sinks |
| One Run | StartRun and config | Input, Session, idempotency and admitted configuration identity |
| Request identity | RequestContext | Principal, tenant and authorization context |
| Secrets | Environment/credential providers referenced by config | The starter uses MODEL_API_KEY |

`SageManifestLoader.load(path, environment=...)` supports declared overlays for `runtime / policies / interfaces` only. It cannot override arbitrary fields, and there is no universal environment-to-YAML override rule.

Explicit `with_*()` calls replace host ports. Composition combines plugin selections, declarations and locked dependencies; user config cannot impersonate injected model or storage objects. **Use `agent.resolved_plan` for the final revision bindings; `app.resolved_plan` is the initial process view.** Custom host Run plans appear in composition diagnostics. A loaded handle does not fabricate them in advance. `with_shared_runtime()` borrows its declared process services, rather than copying all Builder settings or host policies.

<a id="各项目保持一致的调试方式"></a>

## A consistent debugging contract

The starter writes events and final state to stdout, and `sage.log/v1` logs to stderr. `FilesystemDiagnosticSink` writes model diagnostics under the corresponding Session/Run directory in `runtime_root/sessions`. These files may contain business inputs and remain private host data even after redaction.

Keep these inspection paths in other hosts:

1. **Inspect composition:** report capability, plugin_id, scope, source and `composition_hash` from `app.resolved_plan`, excluding raw secrets.
2. **Inspect readiness:** enable `with_readiness_check()` and inspect `app.resource_readiness`; this does not prove a real model or tool execution.
3. **Trace one Run:** correlate `session_id → run_id → step_id / request_id / tool_call_id` as each record exposes them.
4. **Read events before diagnostics:** Session events, state and checkpoints are authoritative. Logs and model diagnostics cannot become recovery inputs.
5. **Keep the same entrypoint:** inject `ScriptedModelProvider` offline and remove that injection for production, preserving bootstrap and event consumption.

Start investigations here:

| Symptom | Inspect first |
| --- | --- |
| Wrong plugin or ineffective configuration | source and plugin_id in resolved_plan.providers, then manifest and injection |
| Wrong model request or budget | Model diagnostics and AgentCompositionFactory.create_context() |
| Suspended Run or pending approval | Run events and interaction state; do not resubmit effects |
| Recovery identity mismatch | Persisted admission snapshot, composition hash and bindings; never substitute the latest hash |
| Shutdown or sandbox cleanup failure | Application/Run ownership, then execution lifecycle; cleanup and durable reconciliation differ |

<a id="一个入口参数表达差异"></a>

## One entry point with explicit host parameters

Desktop, Server and third-party hosts use `SAgentBuilder.build()` and `AgentCompositionFactory.create_loop()`. Hosts still own authentication, catalogs, approvals and sandbox policies, supplied through parameters or existing ports.

**Agent definitions are Agent Packages.** `sage.yaml` describes the Agent, model bindings, tools, Skills and policies, and may include runtime declarations. Deployment runtime parameters use the same `RuntimeConfig` as YAML.

```python
from sagents.v2 import SAgentBuilder
from examples.sagents_v2_host.plugins import compactor_registration

builder = SAgentBuilder().with_defaults(session_root="./runtime")
builder.register(compactor_registration())  # 先注册，再装配
app = await builder.build(runtime={
    "capabilities": {
        "context.unit-compactor": {
            "plugin": "example.context.reference-compactor",
            "scope": "agent",
            "config": {"minimum_characters": 4},
        },
    },
})
agent = await app.load_agent("examples/sagents_v2_host/sage.yaml")
# 使用完成后 await app.close()；真实模型仍需要对应的凭据。
```

Omitting runtime selects the SDK/Desktop shared defaults without personal settings or keys. Explicit runtime is a complete configuration, not an implicit deep merge. To customize defaults, use `from sagents.v2 import default_runtime`, call `default_runtime(session_root)` and edit its capabilities. App runtime takes precedence over legacy Package runtime declarations. Resources open lazily on first Agent load; closing immediately after build is valid. Resolved Packages cannot silently change runtime, and recovery retains admission configuration. Server merges deployment settings and Package capability choices in its adapter.

Every plugin uses `CapabilitySelection` (`plugin / name / scope / config`). `ExtensionRegistration` declares capabilities, scopes, JSON Schema, an optional config model and a factory. Validation precedes factory calls. The starter rejects unknown fields. Trusted injected dependencies remain separate from user config and cannot be overridden. Implementations remain independent and do not import sibling plugins. The starter compactor demonstrates the contract rather than providing a vendor tokenizer.

Both hosts accept preregistration through `DesktopV2Service(..., extensions=(registration,))` and `ServerHost(..., extensions=(registration,))`; `package_extensions` is removed. Registration supplies implementation, while `runtime.capabilities` chooses it and its parameters. Keep factory calls at composition boundaries.

Hosts with their own admission path use these existing interfaces rather than internal assemblers:

| Interface | Purpose |
| --- | --- |
| `application.compose_run(callback)` | Composition and ownership boundary; does not admit, run or recover |
| `application.materialize_agent(..., runtime=...)` | Resolve scoped components on an existing Application |
| `SAgentBuilder.with_shared_runtime(application)` | Borrow process services for a Package application |
| `AgentCompositionFactory.create_loop(...)` | Shared authorization, context, history and loop wiring |
| `application.process_provider(capability, selection, dependencies=...)` | Create App-owned process providers with shared validation and caching |

`create_loop()` accepts `context_providers` (replacing the default order), `developer_instructions`, `context_agent_id`, `completion_gates` and `automatic_memory_recall`. Desktop preserves its prompt ordering, root Agent budgets and root plan/goal gates. These are host policy inputs; frozen recovery inputs still require validation.

Desktop obtains its sandbox provider through `process_provider()`. App owns provider reuse and shutdown. Custom constructor arguments belong in host `execution.sandbox.provider_config`; per-sandbox network and resource settings remain in the sandbox spec. Provider shutdown and durable sandbox pause/release have separate lifetimes, with durable operations handled by execution lifecycle.

Server reading path: `bootstrap.py → packages/builder.py → runtime/loop.py → runtime/driver.py`. Desktop: `backend/composition.py → run_composition.py`, with configuration translation in `component_plan.py` and model routes in `model_providers.py`. Product policies and implementations remain independent.

<a id="生命周期与恢复约定"></a>

## Lifecycle and recovery

- Injected objects remain host-owned unless ownership is transferred with `with_owned_resources()`. The host cleans up objects not yet transferred when build fails.
- A `compose_run()` callback registers only newly created Run-owned resources with `resources.own(service)`; execution dependencies can use `dependency=True`.
- On success, the host closes `ComposedRun`. Composition failures roll back. Borrowed process services must not be registered as Run-owned.
- Services close before their dependencies, with failed cleanup retryable. Durable sandbox pause/release remains in execution lifecycle.
- Disconnecting an observation stream does not cancel a Run; use explicit control.
- Admission retries reuse idempotency keys; new user operations use new keys. The starter generates a fresh key per launch and is not a production deduplication store.
- Retain admitted snapshots and identities. Reconcile or suspend uncertain external effects rather than replaying them.
- Local defaults and persisted Sessions do not imply distributed or cross-process support for every scheduler, Job or plugin.

<a id="项目应具备的测试"></a>

## Required project tests

Cover configuration and final bindings, offline execution, shutdown and build failure, request idempotency, approval suspension/resume, stable recovery configuration and non-replay of uncertain effects. Add child isolation, delegation and recovery when using subagents. Test each new plugin contract independently.

```bash
.venv/bin/pytest -q tests/sagents/v2/test_host_starter_example.py tests/sagents/v2/test_unified_host_configuration.py
.venv/bin/pytest -q tests/sagents/v2/test_builder_matrix.py tests/sagents/v2/test_run_composition_lifecycle.py
```

Repository tests have a 30-second hang guard. Use separate assertions for performance contracts and `pytest.mark.timeout(...)` for individual limits.

Desktop and Server create sandbox providers through App plugin lifecycle. Server configuration and Agent validation share the host-registered registry.

<a id="验证入口"></a>

## Verification entry points

- Python: `.venv/bin/python -m pytest tests/sagents/v2 tests/app/v2/server tests/app/v2/desktop tests/app/clients/cli --ignore=tests/sagents/v2/live`.
- Desktop: run `flutter test` in `app/v2/desktop`. `unified_sidecar_test.dart` uses a real Python sidecar, replacing only model responses by default.
- Real models: run `SAGE_DESKTOP_LIVE_CATALOG="$HOME/sage/runtime/desktop-catalog.json" flutter test test/unified_sidecar_test.dart` there. It uses the first Agent's model, or `SAGE_DESKTOP_LIVE_MODEL` when specified, and isolated data to verify two turns and recall. This incurs API costs.
- TUI: run `cargo test --offline` in `app/clients/terminal` for CLI v2 launch arguments, events and interactions.

Internal graph tests use private `_build_package`. Third-party integration tests must use public `build()` / `load_agent()` rather than private assemblers.

<a id="自己实现插件从契约开始"></a>

## Implement plugins from their contracts

Read this guide with the [Runtime reference](sagents-runtime-reference.md) and [sage.yaml reference](sagents-manifest-reference.md).

Plugins have two contract layers:

1. **Composition:** ExtensionDescriptor declares identity, capabilities, API versions, config and scopes; ExtensionRegistration supplies factory/start/stop.
2. **Domain:** the returned object implements the capability's methods, such as ContextUnitCompactor.compact or ToolExecutor.execute/reconcile. Registration validation alone does not establish runtime or recovery correctness.

Structural Protocol implementations need not inherit a shared base or built-in plugin. Share SDK contracts, not sibling implementation internals. A plugin offering multiple capabilities must return a correct object for every offer.

<a id="哪些模块支持插件各自是什么协议"></a>

### Supported plugin modules and protocols

The table covers capabilities in the current built-in registry. **Follow the linked public contracts for full signatures, return values and async requirements.** Implement the complete protocol. Where no independent Protocol exists, the table describes the actual adapter contract without promising more stability.

| Capability | Protocol / source | Methods | Required semantics |
| --- | --- | --- | --- |
| `agent.continuation-policy` | [ContinuationPolicy](../../../sagents/v2/agent/policy/continuation.py) | `decide` | Continue, finish or request interaction without bypassing budgets/authorization |
| `artifact.store` | [ArtifactStore](../../../sagents/v2/runtime/artifact/contracts.py) | `put`, `get`, `delete` | Immutable artifact streams and references; separate from Session storage |
| `context.reducer` | [ContextReducer](../../../sagents/v2/context/contracts.py) | `reduce` | Project context without rewriting canonical history |
| `context.summarizer` | [ConversationSummarizer](../../../sagents/v2/context/summary.py) | `summarize` | Generate summary text from the request |
| `context.summary-store` | [ConversationSummaryStore](../../../sagents/v2/context/summary.py) | `get`, `save`, `delete` | Enforce expected_revision on concurrent updates |
| `context.unit-compactor` | [ContextUnitCompactor](../../../sagents/v2/context/contracts.py) | `compact` | Async and side-effect-free; use genuine durable references |
| `context.unit-compactor` | [ContextUnitCompactor](../../../sagents/v2/context/contracts.py) | `compact` | Replace indivisible units without breaking tool-call pairing |
| `credentials.provider` | [CredentialProvider](../../../sagents/v2/runtime/credentials/provider.py) | `resolve` | Resolve CredentialMaterial without logging secrets |
| `execution.job-runtime` | [JobRuntime](../../../sagents/v2/runtime/execution/jobs/provider.py) | `capabilities`, `submit`, `inspect`, `wait`, `cancel`, `read_output`, `handle_run_pause`, `list_run_jobs`, `mark_orphaned`, `adopt`, `purge_terminal`, `close` | Manage background state, output cursors, cancellation, adoption and cleanup |
| `execution.sandbox` | [SandboxProvider](../../../sagents/v2/runtime/execution/sandbox/provider.py) | `capabilities`, `provision`, `attach`, `inspect`, `snapshot`, `restore`, `release`, `terminate`, `purge_terminated` | API v3; return filesystem/process/network ports with host-authorized binding |
| `execution.scheduler` | [Scheduler](../../../sagents/v2/runtime/execution/scheduler/provider.py) | `capabilities`, `submit`, `claim`, `renew`, `release`, `assert_fence`, `execute_fenced`, `cancel`, `close` | Enforce leases, fencing and atomic execution semantics |
| `flow.node` | [RunnableNode](../../../sagents/v2/flow/contracts.py) | `run` | Express completion/suspension/failure with checkpoint and replay boundaries |
| `interface.protocol-adapter` | [ProtocolAdapter](../../../sagents/v2/interfaces/protocols/contracts.py) | `capabilities`, `translate` | Project RuntimeEvent while retaining source identity and reporting loss |
| `memory.provider` | [MemoryProvider](../../../sagents/v2/memory/contracts.py) | `capabilities`, `recall`, `remember`, `forget`, `get`, `health` | Long-term memory with scoped access and idempotent writes |
| `memory.recall-query` | [MemoryRecallQueryGenerator](../../../sagents/v2/memory/query.py) | `generate` | Generate recall queries from user input |
| `model.provider` | [ModelProvider](../../../sagents/v2/model/provider.py) | `capabilities`, `probe_capabilities`, `stream` | Expose capabilities/probes and stream ModelStreamEvent, not RuntimeEvent |
| `observability.diagnostic-sink` | [DiagnosticSink](../../../sagents/v2/runtime/observability/contracts.py) | `begin_model_request`, `complete_model_request`, `record_model_first_token`, `fail_model_request` | Model request/response diagnostics; never authoritative recovery input |
| `observability.log-sink` | [LogSink](../../../sagents/v2/runtime/observability/contracts.py) | `write`, `close` | Synchronous logs with format_version and bounded execution cost |
| `observability.trace-sink` | [TraceSink](../../../sagents/v2/runtime/observability/contracts.py) | `start_span`, `add_event`, `end_span`, `close` | Synchronous spans/events with format_version; bound async export queues |
| `package.registry` | [InMemoryAgentPackageRegistry](../../../sagents/v2/package/registry/registry.py) | `capabilities`, `save_draft`, `validate`, `test`, `publish`, `retire`, `get`, `list` | Registry object adapter, without a separate Protocol or distributed guarantee |
| `session-memory.provider` | [SessionMemoryProvider](../../../sagents/v2/session_memory/contracts.py) | `capabilities`, `sync`, `recall`, `forget_session`, `health` | Synchronize, retrieve and clean Session memory indexes |
| `session.store` | [SessionStore](../../../sagents/v2/runtime/session/contracts.py) | `capabilities`, `create_run`, `get_run`, `list_dispatchable_runs`, `get_run_result`, `get_session`, `get_start_command`, `get_run_context`, `put_attachment`, `get_attachment`, `copy_attachment`, `export_session_backup`, `restore_session_backup`, `get_checkpoint`, `get_suspension`, `get_interaction`, `get_execution_resource`, `list_pending_execution_releases`, `list_execution_resources`, `get_interaction_resolution`, `authorize_session_actor`, `delete_session`, `list_descendant_sessions`, `list_session_runs`, `propose_session_commit`, `publish_session_commit`, `reject_session_commit`, `get_session_commit_proposal`, `list_session_commit_proposals`, `read_session_events`, `read_events`, `read_stream_previews`, `read_fork_base_events`, `subscribe_events`, `publish_stream_preview`, `commit_model_stream_batch`, `commit_run`, `commit_execution_resource`, `enqueue_steer`, `claim_steers`, `resolve_interaction`, `request_resume` | Authoritative Run/Session/event/checkpoint transactions; not arbitrary key-value storage |
| `skill.catalog` | [SkillCatalog](../../../sagents/v2/skill/contracts.py) | `list_skills`, `get_skill` | Discover authorized Skill descriptions |
| `skill.loading` | [SkillLoadingPlugin](../../../sagents/v2/skill/plugins/loading.py) | `create_loader` | create_loader(**ports) factory adapter returning a SkillLoader-compatible object |
| `skill.source` | [SkillSource](../../../sagents/v2/skill/contracts.py) | `fetch` | Fetch SkillBundle; another workspace port handles materialization |
| `tool.catalog` | [ToolCatalog](../../../sagents/v2/tool/provider.py) | `list_tools`, `get_tool` | Tool schemas and side-effect metadata within host/Agent allowlists |
| `tool.executor` | [ToolExecutor](../../../sagents/v2/tool/provider.py) | `execute`, `reconcile` | Implement execute and reconcile together; see CancellableToolExecutor for cancellation |
| `tool.selection-policy` | [ToolSelectionPolicy](../../../sagents/v2/tool/selection.py) | `prepare`, `select`, `expand_tools`, `expanded_tools`, `restore_expanded_tools`, `release_run` | Select visible tools without expanding authorization |
| `workspace.initializer` | [WorkspaceInitializer](../../../sagents/v2/workspace/contracts.py) | `initialize` | Synchronous initialize(root) returning created files without importing private host state |

Some ports are injected through Builder and **are not additional capability plugin names**:

| Port | Injection / contract | Boundary |
| --- | --- | --- |
| DerivedStateStore | `with_derived_state_store`; [Contract](../../../sagents/v2/runtime/session/contracts.py) | Rebuildable state such as summaries, with revision concurrency |
| SkillWorkspace | `with_skill_provider(catalog, source, workspace)`; [Contract](../../../sagents/v2/skill/contracts.py) | Controlled materialization without implicit host-path grants |
| ExecutionBindingProvider | `with_execution_binding_provider`; [Contract](../../../sagents/v2/runtime/execution/binding.py) | Host-granted workspace/sandbox binding, recovery and release |
| Model concurrency budget | `with_model_budget` | Shared host inference concurrency |
| Run driver | `with_run_driver_factory` / HostAgentExecution | Advanced admission snapshot/driver integration; unnecessary for ordinary hosts |

<a id="一个完整独立的插件"></a>

### A complete independent plugin

This compactor uses durable references returned by tools and does not estimate tokens.

```python
"""Standalone compactor example using exact characters and durable references."""
from pydantic import BaseModel, ConfigDict, Field
from sagents.v2.contracts.items import TextBlock
from sagents.v2.runtime.extensions import CapabilityOffer, ExtensionDescriptor, ExtensionRegistration, ExtensionScope


class ReferenceConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    minimum_characters: int = Field(default=4, gt=0)


class ReferenceCompactor:
    def __init__(self, *, minimum_characters=4):
        self.minimum_characters = minimum_characters

    async def compact(self, messages):
        projected = []
        for message in messages:
            reference = message.metadata.get("context_reference", {})
            uri = reference.get("uri") if isinstance(reference, dict) else None
            if message.role == "tool" and uri and len(message.model_dump_json()) >= self.minimum_characters:
                projected.append(message.model_copy(update={"content": (TextBlock(text=f"[Stored tool result: {uri}]"),)}))
            else:
                projected.append(message)
        return tuple(projected) if tuple(projected) != messages else None


def compactor_registration() -> ExtensionRegistration:
    return ExtensionRegistration(
        descriptor=ExtensionDescriptor(
            plugin_id="example.context.reference-compactor", version="2.0.0", name="Example reference compactor",
            provides=(CapabilityOffer(capability="context.unit-compactor", api_version="2"),),
            supported_scopes=frozenset({ExtensionScope.AGENT}), config_schema=ReferenceConfig.model_json_schema(),
        ), config_model=ReferenceConfig,
        factory=lambda context, dependencies: ReferenceCompactor(**context.config),
    )
```

Register before building App; configuration follows the standard runtime schema:

```python
from sagents.v2 import SAgentBuilder
from sagents.v2.composition.defaults import default_runtime

builder = SAgentBuilder()
builder.register(compactor_registration())
config = default_runtime("./runtime").model_dump(mode="json")
config["capabilities"]["context.unit-compactor"] = {
    "plugin": "myproject.context.reference-compactor",
    "config": {"minimum_characters": 3},
}
app = await builder.build(runtime=config)
try:
    agent = await app.load_agent("./agents/assistant")
finally:
    await app.close()
```

See runnable [plugins.py](../../../examples/sagents_v2_host/plugins.py) and its [bootstrap wiring](../../../examples/sagents_v2_host/bootstrap.py). A Python package name in YAML is insufficient; the registry needs a real factory.

<a id="注册协议逐项说明"></a>

### Registration fields

| Object / field | Required / default | Responsibility |
| --- | --- | --- |
| `ExtensionDescriptor.plugin_id` | required Identifier | Stable unique plugin ID |
| `version` | required string | Implementation version, distinct from capability API version |
| `api_version` | `2` | Descriptor API identifier |
| `name` / `description` | name required; description="" | Display name and purpose |
| `provides` | nonempty CapabilityOffer array | Capabilities actually offered |
| `dependencies` | `[]` | Declared resolvable dependency graph |
| `supported_scopes` | nonempty set | Supported lifetimes |
| `default_scope` | null | Must be supported; default selection can prefer process→tenant→agent→run, subject to the composition point |
| `config_schema` | `{}` | JSON Schema; prefer additionalProperties=false |
| `capabilities` | `{}` | Real provider guarantees |
| `built_in` | false | Metadata; self-declaring true does not grant built-in trust |
| `availability` | available=true, reason=null | Availability probe including missing optional dependencies |
| `ExtensionRegistration.factory` | required | (context, dependencies) → instance, sync or async |
| `start` | null | Optional (instance, context, dependencies) → provider map, may be async |
| `stop` | null | Optional (instance, reason) → None, may be async |
| `config_model` | null | Recommended Pydantic model for defaults and validation, consistent with schema |

CapabilityOffer requires capability and api_version. name defaults to default and multi_provider to false. A descriptor cannot repeat `(capability, name)`. Most capability APIs use version 2; sandbox uses 3. Follow each offer and host requirement.

ExtensionDependency requires capability; api_version defaults to `>=2,<3`, name to null and optional to false. Obtain declared dependencies through ProviderSet instead of creating another App or finding implicit singletons. Long-lived providers cannot retain destroyed short-lived dependencies.

ExtensionScopeContext requires scope and scope_id. tenant_id/agent_id/run_id default to null and config to `{}`. Scope identity is not authorization to reuse the first observed run_id for all requests in a process plugin.

<a id="多端口插件和资源清理"></a>

### Multiple ports and resource cleanup

A plugin offering ToolCatalog and ToolExecutor can return a container and map both ports explicitly:

```python
from sagents.v2.runtime.extensions import CapabilityKey

def start_tools(instance, context, dependencies):
    return {
        CapabilityKey(capability="tool.catalog", name="custom"): instance.catalog,
        CapabilityKey(capability="tool.executor", name="custom"): instance.executor,
    }

async def stop_tools(instance, reason):
    await instance.close()
```

Pass start_tools and stop_tools to ExtensionRegistration and declare the same keys in descriptor.provides. Catalog and executor names must match. A single-port plugin without registration.start or instance.start exposes its instance directly.

Startup and shutdown order:

1. Validate schema/config_model, resolve dependencies and scope, then call the factory. A failed factory cleans its own not-yet-returned resources.
2. Prefer registration.start, then instance.start; otherwise expose the instance. Returned keys must match provides.
3. Successful instances belong to their scope; later startup failure rolls them back.
4. Shutdown prefers registration.stop, then instance.stop(reason), then instance.close(). Awaitables are supported and dependency order is respected.
5. StopReason includes scope_closed, start_failed, host_shutdown and reload. Cleanup must tolerate retries and must not rely on destructors.

Process, tenant and Agent scopes may serve multiple Runs. Isolate bounded temporary state by run_id, keep external I/O outside long-held shared locks, and never double-close borrowed host objects.

<a id="不同领域必须守住的语义"></a>

### Domain semantics to preserve

- **Models:** report real capabilities, preserve stream deltas, tool-call IDs and completion semantics, and translate provider errors accurately. Cancellation or disconnect is not success.
- **Tools:** declare real side effects, idempotency and cancellation. Use operation_id for external idempotency/reconciliation. Unknown effects must remain uncertain rather than being replayed.
- **SessionStore:** implement transactions/CAS, event sequences, idempotency, actor authorization, checkpoints and recovery. A messages-only backend is insufficient; derived indexes cannot replace canonical events.
- **Scheduler:** execute_fenced prevents lease replacement until mutation completes. An unlocked callback after assert_fence is insufficient. Tenant concurrency must match declared guarantees.
- **Sandbox/Jobs:** expose real inspectable state and reconnect/cancel/release outcomes. Returning success cannot stand in for terminating a process. Hosts authorize paths/network; plugins enforce them.
- **Context:** alter inference projections only, retaining tool pairs and required references. Canonical history is immutable; persistent summaries enforce revision competition.
- **Protocols:** project RuntimeEvent and report lost information. AG-UI/MCP/A2A presentation frames are not canonical state.
- **Logs/Trace:** use bounded buffering, protect credentials and keep observations separate from recovery and business state.

<a id="插件应如何测试"></a>

### Plugin testing

Verify domain contracts before composition. Most tests can remain offline:

| Layer | Coverage | Repository reference |
| --- | --- | --- |
| Parameters | Defaults, bounds, unknown fields, missing dependencies and unsupported scopes | [Extension tests](../../../tests/sagents/v2/test_extension_discovery_matrix.py) |
| Composition | Preregister → build → load_agent; validate choices and preserve the current revision on error | [Loading tests](../../../tests/sagents/v2/test_loaded_agents.py) |
| Lifecycle | Factory/start rollback, stop/close and no double-close of borrowed objects | [Resource lifetime tests](../../../tests/sagents/v2/test_run_composition_lifecycle.py) |
| Domain semantics | Contracts, concurrency, idempotency, cancellation, errors and uncertain outcomes | Domain contracts/providers and their tests/sagents/v2 suites |
| Recovery | Resume the original revision after restart without replaying effects with new config | [Loading tests](../../../tests/sagents/v2/test_loaded_agents.py), Session/execution recovery tests |
| Independence | No sibling internals or cross-layer host UI imports | [Boundary tests](../../../tests/sagents/v2/test_source_boundary_matrix.py) |

For pure compaction, cover empty messages, Unicode, long inputs and invalid parameters. Tools, storage and schedulers need failure injection and recovery tests. Finish through the real host entrypoint; a successful factory return is insufficient.

<a id="旧数据升级与部署"></a>

## Legacy migration and deployment

Top-level `models` / `credentials` in old `sage.yaml` are rejected. New hosts use separate App model configuration; existing deployments must migrate persisted Packages, not just disk examples. Never delete Sessions or change `resolved_spec_hash` to bypass errors.

The repository provides explicit offline migration scripts:

```bash
# Server：先审计，再停止所有写入进程并执行迁移。
python -m scripts.v2.migrate_app_models
python -m scripts.v2.migrate_app_models --writers-stopped --backup /secure/app-models-before.json

# Desktop：root 是实际 runtime 目录，不是工作区。
python -m scripts.v2.migrate_desktop_app_models --root /path/to/sage/runtime
python -m scripts.v2.migrate_desktop_app_models --root /path/to/sage/runtime --apply --writers-stopped
```

The Server script reads deployment database settings and writes transactionally. It first saves original records to an exclusively created backup file, then updates Packages, Bundle references and indexes. Only legacy standard Server model references are accepted; extra connections or request options abort until a mapping is defined. Existing Run identities remain unchanged. Runs without historical model snapshots retain their authorized-catalog recovery rules; migration cannot reconstruct a missing snapshot.

The Desktop script converts `llm-provider:` references to App model IDs across RSI, catalog and Session Packages while preserving actual model settings and provider snapshots. It backs up affected JSON files and the entire RSI database to runtime/backups. This is not a cross-file transaction: after interruption, stop the client and restore that backup before retrying. Both scripts support repeat audits; remaining changes must reach zero.

Validate a backup copy first and stop all old writers during deployment. Rollback restores both old code and pre-migration data; mixed schemas are unsupported. Verify two real-model turns, history and suspended-run recovery in addition to health checks.
