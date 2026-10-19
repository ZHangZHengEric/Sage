# SAgents v2 Runtime 配置参考

[接入开发指南](sagents-host-development.md) · [sage.yaml 配置参考](sagents-manifest-reference.md) · [代码阅读指南](code-reading-guide.md)

本文面向使用 `SAgentBuilder.build()`、`app.load_agent()` 的项目，解释当前代码实际支持的配置。Runtime 决定 App 使用哪些组件；App 的模型目录管理模型路由与凭据；Agent Package 决定指令、模型 ID 引用、工具范围和预算。Desktop、Server 的数据库地址、登录配置、监听端口、工作区选择属于宿主设置，不是这里的 RuntimeConfig 字段。

## App 模型配置

App 分别接收两份配置：`runtime.yaml` 选择组件及参数，`models.yaml` 管理模型及凭据引用。`models` 不是 RuntimeConfig 字段，不要把它塞进 `runtime.yaml`。Agent Package 只引用 App 模型 ID。

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

`models` 支持文件路径字符串、Path、配置字典、ModelCatalogConfig。YAML/JSON 正文使用 `models_config_text=`；两种参数互斥。省略时目录为空，不会自动提供模型或读取当前电脑的密钥。默认运行组件仍采用标准组件方案；Desktop/Server 的宿主层负责把自身模型配置传入 App。

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

`your-model`、窗口数值和推理力度只是配置示例，需按实际供应商模型填写。能力声明不会让模型获得原本不支持的功能。不要复制其他模型的探测结果。顶层只有 `models` 和 `credentials`，默认都是空映射；未知字段、重复 YAML 键、无效凭据引用会被拒绝。

### 更新与版本

Builder 的 `build(models=...)` 用于创建前配置；已经 build 的 App 通过以下接口更新：

```python
await app.update_models("./models.yaml")  # 原子替换整个目录
route = app.models.models["primary"].model_copy(deep=True)
route.request.reasoning_effort = "high"
await app.update_model("primary", route)  # 替换单个模型的完整配置
agent_v2 = await app.load_agent("./agents/assistant")
```

`update_model` 接收完整 ModelRoute 或同结构字典，不是局部补丁；新凭据声明应通过 `update_models` 一并提交。`app.models` 返回副本，修改副本不会更新 App。更新先校验再发布，失败不会损坏当前目录。

模型更新后重新 load 同一 Package 才会得到引用新模型配置的 handle；旧 handle 和已受理 Run 继续使用原快照。Package 自身改变时仍须 `update_agent`。未被 Agent 引用的模型更新不改变它的装配身份。恢复使用已受理版本，不能把“读取最新模型配置”当作恢复步骤。密钥材料仍由凭据服务提供，不写入 Package 或模型快照。

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

| 字段 | 类型 | 默认 | 含义 |
| --- | --- | --- | --- |
| `source` | `env` / `host` | 必填 | 从环境或宿主凭据服务取得密钥 |
| `key` | string / null | null | env 使用的环境变量名 |
| `ref` | string / null | null | host 使用的凭据引用 |

不要把真实密钥写成 key/ref 的内容。env 声明应提供 key；host 声明应提供宿主能够解析的 ref。模型 schema 本身允许 key/ref 为 null，并不证明凭据能解析；最终由对应凭据 provider 校验。默认环境 provider 不会自动读取 Server 数据库中的 host 凭据。

### models

App 的 `models.<id>` 定义路由，Package 的 `agents.main.models.<slot>` 引用该 ID。常用槽位为 primary、fast；路由名可以自定义。

| ModelRoute 字段 | 类型 | 默认 | 含义 |
| --- | --- | --- | --- |
| `provider` | Identifier | 必填 | 供应商协议 ID，不是模型名 |
| `plugin` | Identifier / null | null | 指定已注册 model.provider 插件；省略按 provider 协议解析 |
| `base_url` | string / null | null | 绝对 HTTP(S) URL；不能含用户名密码、query 或 fragment |
| `credential` | Identifier / null | null | 顶层 credentials 的键 |
| `model` | string | 必填 | 供应商的模型 ID |
| `request` | ModelRequestDefaults | 见下表 | 请求默认值 |
| `limits` | ModelLimits | 见下表 | 模型上下文和输出限制 |
| `capabilities` | ModelCapabilityDeclaration | 见下表 | 能力声明，不能替代探测事实 |
| `capability_profile` | ModelCapabilityProfile / null | null | 宿主保存的版本化探测结果与插件调用策略，通常由模型配置流程生成 |

内置协议：`openai-responses`、`openai-chat-completions`、`anthropic-messages`、`gemini-generate-content`，对应 `sage.model.<协议>` 插件。模型名称不存在或协议不匹配时，不会自动换供应商模型。

| request 字段 | 类型 / 范围 | 默认 | 含义 |
| --- | --- | --- | --- |
| `max_output_tokens` | 正整数 / null | null | 请求输出 token 上限 |
| `temperature` | number / null | null | 采样温度；供应商另有合法范围和模型限制 |
| `top_p` | number / null | null | nucleus sampling 参数；供应商另有约束 |
| `reasoning_effort` | string / null | null | 推理力度，由对应模型协议解释 |
| `extra` | 对象 | `{}` | 协议扩展字段，不保证任意供应商都支持 |

| limits 字段 | 类型 | 默认 | 含义 |
| --- | --- | --- | --- |
| `context_window` | 正整数 / null | null | 上下文窗口上限 |
| `max_output_tokens` | 正整数 / null | null | 模型允许的最大输出 token 数 |

null 表示没有在此处声明，不表示无限大；还受模型、宿主和 Run 预算限制。

| capabilities 字段 | 默认 | 含义 |
| --- | --- | --- |
| `multimodal` | false | 多模态输入 |
| `structured_output` | false | 结构化输出 |
| `tool_calling` | true | 工具调用 |
| `reasoning` | false | 推理能力 |
| `parallel_tool_calls` | false | 并行工具调用 |

以上类型都是 boolean。`capability_profile` 的完整结构：schema_version=1；plugin_id、plugin_version、protocol、route_fingerprint、effective_max_output_tokens（正整数）、outcomes 必填；verified_at 默认当前 UTC 时间；invocation_strategy、metadata 默认 `{}`。outcomes 必须恰好包含 connection、multimodal、structured_output、json_object、tool_calling、reasoning_control 六项且不重复。

每项 outcome：name 与 status 必填；status 为 supported/unsupported/error/skipped；response、error、error_code、error_category、provider_code 默认为 null；metadata 默认 `{}`。这些是某个路由版本的探测事实，勿复制别的模型的 profile 假装已经验证。插件拥有 invocation_strategy 的解释权。


## 目录

- [输入方式](#输入方式)
- [默认值和优先级](#默认值和优先级)
- [RuntimeConfig 全部字段](#runtimeconfig-全部字段)
- [CapabilitySelection 全部字段](#capabilityselection-全部字段)
- [默认组件](#默认组件)
- [常见配置](#常见配置)
- [自定义插件、校验和生命周期](#自定义插件校验和生命周期)
- [排查配置与恢复问题](#排查配置与恢复问题)
- [内置插件完整参数表](#内置插件完整参数表)

## 输入方式

以下都是 App 创建阶段的输入；路径和文本明确区分，不会猜测一个字符串是不是 YAML。

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

`runtime` 和 `runtime_config_text` 互斥。文件内容可以是 YAML 或 JSON，顶层必须是对象；重复 YAML 键、未知结构字段、错误类型会报错。Runtime 文件直接以 `preset`、`capabilities` 等为顶层，**不要再套一层 `runtime:`**。这与 `sage.yaml` 中的 `runtime:` 段不同。文件路径支持 `~`；组件 `config.root` 等路径由各组件/宿主解释，并没有统一“相对 runtime.yaml 所在目录”的规则。部署时建议传绝对路径。

## 默认值和优先级

必须区分以下三种情况：

| 调用 | 行为 |
| --- | --- |
| `build()`，不传 runtime | 使用共享 Desktop 组件默认方案，见下表；运行目录默认为当前工作目录下 `.runtime/sagents` |
| `build(runtime={})` / `build(runtime=RuntimeConfig())` | 使用 RuntimeConfig 的字段默认值，未选择组件走装配器基础回退；不会自动叠加整套 Desktop 默认方案 |
| `build(runtime=配置)` | 这份配置成为 App 的 runtime；随后 `load_agent` 使用 App runtime，Package 自带 runtime 不会再覆盖它 |

`with_defaults(session_root=...)` 可以改变默认运行目录。默认方案共享的是组件选择，不会读取你电脑 Desktop 的 API Key、模型目录、数据库或个人设置。

若要在默认方案上只修改少量参数，先取得默认配置再修改，不要把一份只有两项的配置误认为“自动补齐 Desktop 默认”的覆盖配置：

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

配置来源的关系：

1. App 在 `build` 时固定 runtime；改变 Agent Package 不等于改变 App 的进程资源。
2. `plugins[].config` 提供插件声明参数；同一项 `capabilities.<能力>.config` 的参数优先于声明参数。部分装配路径还填入组件默认值，最终以 resolved plan 为准。
3. 宿主通过注册工厂提供进程对象，通过 runtime 明确选择实现和参数；依赖由标准能力装配器校验，不允许 YAML 填入模型或数据库连接等进程对象。
4. Server、Desktop 会根据自己的配置、持久化存储和权限生成实际 runtime；共用 SDK 标准不意味着覆盖宿主的安全策略。

如果希望采用 `sage.yaml` 中的 runtime，需要宿主明确读取后传入，参考项目就是这样处理的：

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

## RuntimeConfig 全部字段

| 字段 | 类型 / 可选值 | 默认值 | 用途与边界 |
| --- | --- | --- | --- |
| `preset` | Identifier | `standard` | 配置中的预设标识。当前通用装配路径不根据这个字符串自动切换组件集合；具体实现仍由 capabilities/宿主决定，不要写一个名字期待自动加载 |
| `deployment_profile` | `controlled_host` / `distributed` | `controlled_host` | 选择运行保障要求。distributed 会触发更严格的能力检查，不是打开多副本支持的开关 |
| `plugin_trust_policy` | `trusted_declared` / `built_in_only` | `trusted_declared` | 是否允许宿主信任并声明的扩展；built_in_only 只接受注册表认定的内置插件，不能通过自填 built_in 绕过 |
| `capabilities` | 能力名 → Selection 或 Selection 数组 | `{}` | 选择插件实现、实例名、scope 和参数；单实例能力不能任意配置多个实现 |
| `required_guarantees` | 能力名 → 保障名 → 期望值 | `{}` | 运行要求，装配时检查实际 provider；不能证明时拒绝，不是描述性备注 |

Identifier 长度 1–192，首字符为字母或数字，后续可用字母、数字和 `._:@/-`。保障名不是任意配置开关，需对应 provider 支持的能力报告。当前内置 SessionStore/Scheduler 并不能提供完整分布式 claims/outbox/subscription 体系；仅切换到 MySQL/Postgres 不代表可多进程共同执行。

## CapabilitySelection 全部字段

```yaml
capabilities:
  context.unit-compactor:
    plugin: sage.context.unit-compactor.reference
    name: default
    scope: agent
    config: {}

```

| 字段 | 类型 | 默认值 | 含义 |
| --- | --- | --- | --- |
| `plugin` | Identifier | 必填 | 已注册的插件 ID，不是 Python import 路径 |
| `name` | Identifier | `default` | 插件提供的能力名称；一个插件仅有一个对应 offer 时，装配器可以解析隐式 default；多 offer 时应明确指定 |
| `scope` | `process` / `tenant` / `agent` / `run` / null | null | null 使用装配点默认生命周期；显式值必须在插件 supported_scopes 内，不应为了复用随意扩大作用域 |
| `config` | 对象 | `{}` | 该插件的参数，按它自己的 schema/config_model 校验；不同插件的参数不能混用 |

scope 的含义：process 与 App 进程服务同寿命；tenant 按租户隔离；agent 关联 Agent 实例/版本的装配作用域；run 关联运行作用域。scope 不自动提供跨进程共享，也不会自动给插件加锁。process/tenant/agent 插件必须能处理重叠调用。某些装配点只支持一个 scope 或需要宿主提供相应身份。

## 默认组件

下表中的 `R` 表示 `Path(session_root).expanduser().resolve()`，默认 `session_root=.runtime/sagents`。省略的 config 使用后文插件参数默认值。

| 能力 | build() 默认插件 | 默认参数 / 用途 |
| --- | --- | --- |
| `session.store` | `sage.session.filesystem` | `root=R`；持久化 Session、命令和事件 |
| `memory.provider` | `sage.memory.filesystem-bm25` | `root=R/memory`；长期记忆检索与存储 |
| `session-memory.provider` | `sage.session-memory.sqlite-bm25` | `root=R/session-memory`；会话记忆索引 |
| `skill.loading` | `sage.skill.loading.lazy` | 按需激活 Skill，默认活动内容上限 6000 tokens |
| `agent.continuation-policy` | `sage.agent.continuation.llm-judge` | 模型判断后续执行/结束 |
| `context.reducer` | `sage.context.reducer.persistent-summary` | 持久化摘要压缩上下文 |
| `context.summarizer` | `sage.context.summarizer.model` | 主模型生成摘要 |
| `context.summary-store` | `sage.context.summary-store.session-derived` | 使用会话派生状态存摘要 |
| `memory.recall-query` | `sage.memory.recall-query.llm` | 模型生成记忆检索查询 |
| `tool.selection-policy` | `sage.tool-selection.llm` | 按需选择给模型展示的工具 schema |
| `observability.diagnostic-sink` | `sage.observability.filesystem` | `root=R/sessions`，`legacy_root=R/diagnostics`；模型等诊断资料 |
| `observability.log-sink` | `sage.logging.filesystem` | `root=R/logs`；结构化运行日志 |
| `workspace.initializer` | `sage.workspace.initializer.claw` | `language=en`；工作区引导资料 |

默认运行方案未显式列出的服务仍有装配回退：调度器 `sage.scheduler.ephemeral`、后台 Job `sage.job.ephemeral`、Artifact `sage.artifact.session`、Package Registry `sage.package-registry.ephemeral`、Trace `sage.trace.noop`、凭据 `sage.credentials.environment`、上下文单元压缩 `sage.context.unit-compactor.reference`。模型实现由 App 模型目录解析 Agent 的模型 ID 引用。

显式空 runtime 与上表的重要差异：memory/session-memory 为 noop，记忆查询为 direct，continuation 为 deterministic，diagnostic/log 为 noop，workspace initializer 为 bare；会话存储仍回退 filesystem。**提供记忆组件也不会自动打开 Agent 的 `memory.recall/auto_write`，它们默认 false。**

沙箱另有边界：共享组件目录推荐 `sage.sandbox.local-workspace`，但 `default_runtime()` 有意不直接选择 `execution.sandbox`，因为它需要宿主的验证密钥、工作区与执行绑定。Desktop 使用真实工作区路径（host 模式）；`workspace_root`、`workspace_path_mode`、`workspace_mapping`、`filesystem_mode` 是宿主执行绑定的设置，不是随意塞进插件 config 的字段。普通 SDK 只调用 build() 不会自动取得任意本地目录的执行权限。

## 常见配置

### 输出日志、调整摘要和调度并发

下面是一份**显式 runtime**，未列出的组件走装配回退。要保留整套 Desktop 默认，请按前文先复制 `default_runtime()` 再覆盖。

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

调度并发限制是整个 App 的运行调度限制，不是模型供应商 QPS。租约由运行器维护，不要把 lease_seconds 当作对话总超时。`wall_time_seconds` 属于 Agent/Run 预算，模型摘要超时属于 summarizer，MCP 超时属于单个 MCP server，它们不能互相替代。

### MCP 与工具可见性

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

此片段只配置工具来源，Agent 仍需显式声明允许使用的工具名。MCP server 暴露的名称以发现结果为准，不要猜测；真实连接需检查可达性和认证。`stdio` 使用 command/args/env，HTTP/SSE 使用 url；config 中的 env 是子进程环境，不是整个应用的自动变量替换机制。required=true 时发现失败不应被当成工具源可用。

### 数据库存储

```yaml
capabilities:
  session.store:
    plugin: sage.session.postgres
    config:
      dsn: postgresql://user:password@localhost/sage
      schema_name: sage_v2
      table_prefix: sagent
```

示例 DSN 仅为格式说明，不要提交真实密码。当前 runtime 文本没有通用 `${ENV}` 插值，建议宿主读环境/Secret 后构造配置或注入 SessionStore。Postgres/MySQL 分别需要 asyncpg/aiomysql；数据库存储并不让内存 Job、Scheduler 自动变成持久化或分布式实现。

## 自定义插件、校验和生命周期

使用与内置插件相同的声明和参数入口，先注册再 build：

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

完整独立插件见 [plugins.py](../../../examples/sagents_v2_host/plugins.py)。注册提供 descriptor、config_schema/config_model、factory，以及需要时的 start/stop。插件可以依赖 SDK 公共契约，不要依赖另一个插件实现；不要求为了复用抽取共同基类。

`build` 固定注册表与配置；加载 Agent 时实际装配和校验。未知参数、缺少依赖、不可用插件、scope/API 不匹配、能力保障不满足，都应在装配阶段处理，不能靠“参数被接受”判断组件已生效。`plugins` 声明不等于安装依赖包，YAML 也不等于任意 Python 动态 import。

宿主注入的资源通常由宿主关闭；转交所有权用 `with_owned_resources`。App 持有的插件遵循作用域启动、失败回滚、关闭协议。用 try/finally 关闭 App；不要给每次请求重新创建整个 App，也不要手动关闭共享组件。

## 排查配置与恢复问题

1. 普通 SDK 看 `agent.resolved_plan` 和 `agent.resource_readiness`；`app.resolved_plan` 只是进程首次装配视图。
2. 加载句柄的 `resolved_plan` 描述选择和依赖；`app.run_configuration()` 与 `execution_diagnostics()` 查询已授权 Run 的冻结配置及实际绑定。
3. 在 Run 记录中关联 session_id、run_id、resolved_spec_hash，确认恢复使用受理时的版本。
4. `update_agent` 更新 Agent，不热替换 App 共享存储/调度器。改变 runtime 时重新创建 App，并明确旧任务的恢复/迁移策略。
5. 保留 `agent-revisions` 和 Session 数据。当前本机归档恢复要求 runtime 一致，不能把最新配置自动套到旧运行。
6. readiness 不是模型/工具真实可用性验证；还需有代表性的实际调用。

## 内置插件完整参数表

下表按当前注册表逐一列出插件，包含没有参数的插件。`schema 必填` 是插件实例化阶段的要求，**不表示这些项都应由用户写 YAML**：标为“宿主对象”的项由装配层注入。参数默认值优先取注册 schema，再补充已核实的工厂/调度器默认值；“无固定值”表示由宿主/实现按上下文决定，不等于 null 或关闭。

表中的范围是校验范围，bytes 为字节、seconds 为秒、tokens 为 API 输出预算或供应商实际 usage 阈值，不做本地输入估算。对象参数不能用名称字符串替代 Python 对象。插件注册不代表任何能力名放进 capabilities 都会自动创建它：工具、模型、Flow、接口分别由对应装配路径消费。请同时查看“提供能力”和使用位置。


### 插件索引

| 能力 | 内置实现（点击查看参数） |
| --- | --- |
| `agent.continuation-policy` | [sage.agent.continuation.deterministic](#sageagentcontinuationdeterministic)、[sage.agent.continuation.explicit-status](#sageagentcontinuationexplicit-status)、[sage.agent.continuation.hybrid](#sageagentcontinuationhybrid)、[sage.agent.continuation.llm-judge](#sageagentcontinuationllm-judge) |
| `artifact.store` | [sage.artifact.ephemeral](#sageartifactephemeral)、[sage.artifact.filesystem](#sageartifactfilesystem)、[sage.artifact.session](#sageartifactsession) |
| `context.reducer` | [sage.context.reducer.persistent-summary](#sagecontextreducerpersistent-summary)、[sage.context.reducer.window](#sagecontextreducerwindow) |
| `context.summarizer` | [sage.context.summarizer.extractive](#sagecontextsummarizerextractive)、[sage.context.summarizer.model](#sagecontextsummarizermodel) |
| `context.summary-store` | [sage.context.summary-store.ephemeral](#sagecontextsummary-storeephemeral)、[sage.context.summary-store.session-derived](#sagecontextsummary-storesession-derived) |
| `context.unit-compactor` | [sage.context.unit-compactor.reference](#sagecontextunit-compactorreference) |
| `credentials.provider` | [sage.credentials.environment](#sagecredentialsenvironment)、[sage.credentials.mapping](#sagecredentialsmapping) |
| `execution.job-runtime` | [sage.job.ephemeral](#sagejobephemeral) |
| `execution.sandbox` | [sage.sandbox.cube-volume](#sagesandboxcube-volume)、[sage.sandbox.ephemeral](#sagesandboxephemeral)、[sage.sandbox.local-workspace](#sagesandboxlocal-workspace) |
| `execution.scheduler` | [sage.scheduler.ephemeral](#sageschedulerephemeral)、[sage.scheduler.filesystem](#sageschedulerfilesystem) |
| `flow.node` | [sage.flow.agent](#sageflowagent) |
| `interface.protocol-adapter` | [sage.protocol.a2a](#sageprotocola2a)、[sage.protocol.acp](#sageprotocolacp)、[sage.protocol.ag-ui](#sageprotocolag-ui)、[sage.protocol.mcp](#sageprotocolmcp)、[sage.protocol.native](#sageprotocolnative) |
| `memory.provider` | [sage.memory.filesystem-bm25](#sagememoryfilesystem-bm25)、[sage.memory.noop](#sagememorynoop) |
| `memory.recall-query` | [sage.memory.recall-query.direct](#sagememoryrecall-querydirect)、[sage.memory.recall-query.llm](#sagememoryrecall-queryllm) |
| `model.provider` | [sage.model.anthropic-messages](#sagemodelanthropic-messages)、[sage.model.gemini-generate-content](#sagemodelgemini-generate-content)、[sage.model.openai-chat-completions](#sagemodelopenai-chat-completions)、[sage.model.openai-responses](#sagemodelopenai-responses) |
| `observability.diagnostic-sink` | [sage.observability.filesystem](#sageobservabilityfilesystem)、[sage.observability.noop](#sageobservabilitynoop) |
| `observability.log-sink` | [sage.logging.filesystem](#sageloggingfilesystem)、[sage.logging.noop](#sageloggingnoop)、[sage.logging.stdout](#sageloggingstdout) |
| `observability.trace-sink` | [sage.trace.langfuse](#sagetracelangfuse)、[sage.trace.noop](#sagetracenoop)、[sage.trace.otlp](#sagetraceotlp) |
| `package.registry` | [sage.package-registry.ephemeral](#sagepackage-registryephemeral) |
| `session-memory.provider` | [sage.session-memory.noop](#sagesession-memorynoop)、[sage.session-memory.sqlite-bm25](#sagesession-memorysqlite-bm25) |
| `session.store` | [sage.session.ephemeral](#sagesessionephemeral)、[sage.session.filesystem](#sagesessionfilesystem)、[sage.session.mysql](#sagesessionmysql)、[sage.session.postgres](#sagesessionpostgres) |
| `skill.catalog` | [sage.skill.filesystem](#sageskillfilesystem) |
| `skill.loading` | [sage.skill.loading.lazy](#sageskillloadinglazy) |
| `skill.source` | [sage.skill.filesystem](#sageskillfilesystem) |
| `tool.catalog` | [sage.tool.ephemeral](#sagetoolephemeral)、[sage.tool.mcp](#sagetoolmcp)、[sage.tool.multi-agent](#sagetoolmulti-agent)、[sage.tool.official](#sagetoolofficial)、[sage.tool.skill](#sagetoolskill) |
| `tool.executor` | [sage.tool.ephemeral](#sagetoolephemeral)、[sage.tool.mcp](#sagetoolmcp)、[sage.tool.multi-agent](#sagetoolmulti-agent)、[sage.tool.official](#sagetoolofficial)、[sage.tool.skill](#sagetoolskill) |
| `tool.selection-policy` | [sage.tool-selection.direct](#sagetool-selectiondirect)、[sage.tool-selection.lexical](#sagetool-selectionlexical)、[sage.tool-selection.llm](#sagetool-selectionllm)、[sage.tool-selection.recent](#sagetool-selectionrecent) |
| `workspace.initializer` | [sage.workspace.initializer.bare](#sageworkspaceinitializerbare)、[sage.workspace.initializer.claw](#sageworkspaceinitializerclaw) |

### sage.agent.continuation.deterministic

Applies ordered safety, budget, and completion rules without a model call.

提供能力：`agent.continuation-policy:default`。支持 scope：agent, run。

| 参数 | 类型 / 范围 | 默认值 | schema 必填 | 用途 |
| --- | --- | --- | --- | --- |
| `repeat_threshold` | integer；minimum=1 | `3` | 否 | 检测重复执行/循环的阈值 |

### sage.agent.continuation.explicit-status

Completes only when the model emits an explicit turn_status.

提供能力：`agent.continuation-policy:default`。支持 scope：agent, run。

| 参数 | 类型 / 范围 | 默认值 | schema 必填 | 用途 |
| --- | --- | --- | --- | --- |
| `repeat_threshold` | integer；minimum=1 | `3` | 否 | 检测重复执行/循环的阈值 |

### sage.agent.continuation.hybrid

Combines deterministic safety rules with an LLM judge for completion.

提供能力：`agent.continuation-policy:default`。支持 scope：agent, run。

| 参数 | 类型 / 范围 | 默认值 | schema 必填 | 用途 |
| --- | --- | --- | --- | --- |
| `repeat_threshold` | integer；minimum=1 | `3` | 否 | 检测重复执行/循环的阈值 |
| `model` | 宿主对象 | 无固定值；仍需提供/注入 | 是 | 模型依赖；通常是宿主注入的 ModelProvider；tiktoken 中则是 tokenizer 模型名 |
| `model_binding` | string；minLength=1 | `"fast"` | 否 | 选择模型槽位，摘要固定 primary |
| `timeout_seconds` | number；exclusiveMinimum=0 | `60.0` | 否 | 该组件操作的总等待上限（秒），不是整个 Run 预算 |

### sage.agent.continuation.llm-judge

Uses a judge model to decide completion when no tool call is pending.

提供能力：`agent.continuation-policy:default`。支持 scope：agent, run。

| 参数 | 类型 / 范围 | 默认值 | schema 必填 | 用途 |
| --- | --- | --- | --- | --- |
| `repeat_threshold` | integer；minimum=1 | `3` | 否 | 检测重复执行/循环的阈值 |
| `model` | 宿主对象 | 无固定值；仍需提供/注入 | 是 | 模型依赖；通常是宿主注入的 ModelProvider；tiktoken 中则是 tokenizer 模型名 |
| `model_binding` | string；minLength=1 | `"fast"` | 否 | 选择模型槽位，摘要固定 primary |
| `timeout_seconds` | number；exclusiveMinimum=0 | `60.0` | 否 | 该组件操作的总等待上限（秒），不是整个 Run 预算 |

### sage.artifact.ephemeral

Process-local artifact bytes without restart durability.

提供能力：`artifact.store:default`。支持 scope：process, run。

没有可配置参数，使用 `config: {}`。

### sage.artifact.filesystem

Immutable binary artifact files with local restart durability.

提供能力：`artifact.store:default`。支持 scope：process。

| 参数 | 类型 / 范围 | 默认值 | schema 必填 | 用途 |
| --- | --- | --- | --- | --- |
| `root` | string；minLength=1 | 无固定值；仍需提供/注入 | 是 | 存储根目录；不同组件应使用对应独立目录 |

### sage.artifact.session

Artifacts retained by the owning Session store.

提供能力：`artifact.store:default`。支持 scope：process。

| 参数 | 类型 / 范围 | 默认值 | schema 必填 | 用途 |
| --- | --- | --- | --- | --- |
| `session_store` | 宿主对象 | 无固定值；仍需提供/注入 | 是 | 宿主对象：SessionStore |

### sage.context.reducer.persistent-summary

Summarizes older units into a durable rolling conversation summary.

提供能力：`context.reducer:default`。支持 scope：agent, run。

| 参数 | 类型 / 范围 | 默认值 | schema 必填 | 用途 |
| --- | --- | --- | --- | --- |
| `store` | 宿主对象 | 无固定值；仍需提供/注入 | 是 | 宿主对象：摘要存储 |
| `summarizer` | 宿主对象 | 无固定值 | 否 | 宿主对象：摘要生成器 |
| `summary_target_tokens` | integer；minimum=1 | `1024` | 否 | 生成摘要的目标 token 数 |
| `protected_recent_units` | integer；minimum=1 | `4` | 否 | 兼容旧配置；API 恢复按完整批次保留最新用户原文 |
| `max_summary_calls` | integer；minimum=1 | `64` | 否 | 一次压缩允许的摘要调用上限 |
| `max_summary_source_tokens` | integer；minimum=1 | `24000` | 否 | 兼容旧配置，已弃用；输入仅由 API 超长反馈分批 |
| `unit_compactor` | 宿主对象 | 无固定值 | 否 | 宿主对象：上下文单元压缩器 |

### sage.context.reducer.window

Drops complete old units only on API feedback or an exact message-count trigger.

提供能力：`context.reducer:default`。支持 scope：agent, run。

| 参数 | 类型 / 范围 | 默认值 | schema 必填 | 用途 |
| --- | --- | --- | --- | --- |

### sage.context.summarizer.extractive

Preserves bounded task state and Tool outcomes without a model call.

提供能力：`context.summarizer:default`。支持 scope：agent, process。

没有可配置参数，使用 `config: {}`。

### sage.context.summarizer.model

Uses a model binding to write conversation summaries.

提供能力：`context.summarizer:default`。支持 scope：agent。

| 参数 | 类型 / 范围 | 默认值 | schema 必填 | 用途 |
| --- | --- | --- | --- | --- |
| `model` | 宿主对象 | 无固定值；仍需提供/注入 | 是 | 模型依赖；通常是宿主注入的 ModelProvider；tiktoken 中则是 tokenizer 模型名 |
| `model_binding` | string；const="primary" | `"primary"` | 否 | 选择模型槽位，摘要固定 primary |
| `max_source_tokens` | integer；minimum=1 | `24000` | 否 | 单次摘要来源 token 上限 |
| `timeout_seconds` | number；exclusiveMinimum=0 | `300.0` | 否 | 该组件操作的总等待上限（秒），不是整个 Run 预算 |
| `idle_timeout_seconds` | number；exclusiveMinimum=0 | `60.0` | 否 | 摘要流连续无进展的超时（秒） |

### sage.context.summary-store.ephemeral

In-memory conversation summaries without restart durability.

提供能力：`context.summary-store:default`。支持 scope：agent, process。

没有可配置参数，使用 `config: {}`。

### sage.context.summary-store.session-derived

Persists conversation summaries through the selected SessionStore.

提供能力：`context.summary-store:default`。支持 scope：agent, process。

| 参数 | 类型 / 范围 | 默认值 | schema 必填 | 用途 |
| --- | --- | --- | --- | --- |
| `derived_state` | 宿主对象 | 无固定值；仍需提供/注入 | 是 | 宿主对象：派生状态存储 |


### sage.context.unit-compactor.reference

Compacts oversized units into durable references instead of dropping them.

提供能力：`context.unit-compactor:default`。支持 scope：agent, process。

| 参数 | 类型 / 范围 | 默认值 | schema 必填 | 用途 |
| --- | --- | --- | --- | --- |

### sage.credentials.environment

Resolves credentials from process environment variables.

提供能力：`credentials.provider:default`。支持 scope：process, tenant。

| 参数 | 类型 / 范围 | 默认值 | schema 必填 | 用途 |
| --- | --- | --- | --- | --- |
| `declarations` | object | `{}` | 否 | 凭据声明映射，通常来自 App models 配置的 credentials |
| `environment` | object / null | 省略时读取宿主 os.environ | 否 | Trace 为环境标签；credentials.environment 为宿主环境变量映射 |

### sage.credentials.mapping

Resolves credentials from an in-memory host-supplied mapping.

提供能力：`credentials.provider:default`。支持 scope：process, tenant。

| 参数 | 类型 / 范围 | 默认值 | schema 必填 | 用途 |
| --- | --- | --- | --- | --- |
| `values` | object | `{}` | 否 | 宿主凭据值映射，不应硬编码密钥到公开配置 |
| `source` | string；minLength=1 | `"host"` | 否 | 凭据来源标识 |

### sage.flow.agent

Runs a child Agent through the shared AgentLoopEngine.

提供能力：`flow.node:agent`。支持 scope：run。

| 参数 | 类型 / 范围 | 默认值 | schema 必填 | 用途 |
| --- | --- | --- | --- | --- |
| `runtime` | 宿主对象 | 无固定值；仍需提供/注入 | 是 | 宿主对象：RuntimePort |
| `descriptor` | 宿主对象 | 无固定值；仍需提供/注入 | 是 | 宿主对象：Agent 描述 |
| `child_executor` | 宿主对象 | 无固定值；仍需提供/注入 | 是 | 宿主对象：子 Agent 执行器 |
| `workspace_policy` | string；enum=["private_child", "shared_parent", "read_only_parent"] | `"shared_parent"` | 否 | 子 Agent 与父 Agent 的工作区关系 |

### sage.job.ephemeral

Process-local background Job runtime without restart durability.

提供能力：`execution.job-runtime:default`。支持 scope：process。

| 参数 | 类型 / 范围 | 默认值 | schema 必填 | 用途 |
| --- | --- | --- | --- | --- |
| `runners` | object | `{}` | 否 | 宿主对象映射：后台 Job 执行器 |
| `max_concurrent_jobs` | integer；minimum=1 | `32` | 否 | 同时执行 Job 上限 |
| `max_admitted_jobs` | integer；minimum=1 | `1024` | 否 | 已受理 Job 数上限 |
| `max_job_output_bytes` | integer；minimum=1 | `8388608` | 否 | 单 Job 输出字节上限 |
| `max_job_output_chunks` | integer；minimum=1 | `8192` | 否 | 单 Job 输出分块数上限 |
| `max_buffered_output_bytes` | integer；minimum=1 | `268435456` | 否 | 全部 Job 缓冲输出字节上限 |
| `max_buffered_output_chunks` | integer；minimum=1 | `65536` | 否 | 全部 Job 缓冲分块上限 |
| `terminal_ttl_seconds` | integer；minimum=1 | `86400` | 否 | 终态对象保留秒数，不是执行超时 |
| `max_retained_terminal_jobs` | integer；minimum=0 | `4096` | 否 | 保留的终态 Job 数上限 |
| `max_retained_output_bytes` | integer；minimum=0 | `268435456` | 否 | 保留的终态输出字节上限 |
| `output_reconnect_window_seconds` | integer；minimum=0 | `300` | 否 | 输出重连窗口（秒） |

### sage.logging.filesystem

Writes rotating structured operational logs to disk.

提供能力：`observability.log-sink:default`。支持 scope：process。

| 参数 | 类型 / 范围 | 默认值 | schema 必填 | 用途 |
| --- | --- | --- | --- | --- |
| `root` | string；minLength=1 | 无固定值；仍需提供/注入 | 是 | 存储根目录；不同组件应使用对应独立目录 |
| `filename` | string；minLength=1 | `"sage.jsonl"` | 否 | 日志文件名 |
| `max_bytes` | integer；minimum=1024 | `10485760` | 否 | 单日志文件轮转大小（字节） |
| `backup_count` | integer；minimum=1 | `5` | 否 | 轮转日志保留份数 |
| `min_level` | string；enum=["debug", "info", "warning", "error", "critical"] | `"info"` | 否 | 最低记录日志等级 |

### sage.logging.noop

Discards structured operational logs.

提供能力：`observability.log-sink:default`。支持 scope：process。

没有可配置参数，使用 `config: {}`。

### sage.logging.stdout

Writes one JSONL or console line per record to stdout or stderr.

提供能力：`observability.log-sink:default`。支持 scope：process。

| 参数 | 类型 / 范围 | 默认值 | schema 必填 | 用途 |
| --- | --- | --- | --- | --- |
| `stream` | string；enum=["stdout", "stderr"] | `"stdout"` | 否 | 日志输出流 |
| `min_level` | string；enum=["debug", "info", "warning", "error", "critical"] | `"info"` | 否 | 最低记录日志等级 |
| `format` | string；enum=["json", "text"] | `"json"` | 否 | 日志格式 |

### sage.memory.filesystem-bm25

Durable scoped Memory records with incremental SQLite FTS5 BM25 recall.

提供能力：`memory.provider:default`。支持 scope：agent, process, tenant。

| 参数 | 类型 / 范围 | 默认值 | schema 必填 | 用途 |
| --- | --- | --- | --- | --- |
| `root` | string；minLength=1 | 无固定值；仍需提供/注入 | 是 | 存储根目录；不同组件应使用对应独立目录 |

### sage.memory.noop

Disables long-term Memory without changing Agent logic.

提供能力：`memory.provider:default`。支持 scope：agent, process, tenant。

没有可配置参数，使用 `config: {}`。

### sage.memory.recall-query.direct

Uses the current user input as the search_memory query without an additional model request.

提供能力：`memory.recall-query:default`。支持 scope：agent, process, run。

没有可配置参数，使用 `config: {}`。

### sage.memory.recall-query.llm

Uses a fast model to generate compact keywords before calling search_memory.

提供能力：`memory.recall-query:default`。支持 scope：agent, run。

| 参数 | 类型 / 范围 | 默认值 | schema 必填 | 用途 |
| --- | --- | --- | --- | --- |
| `model` | 宿主对象 | 无固定值；仍需提供/注入 | 是 | 模型依赖；通常是宿主注入的 ModelProvider；tiktoken 中则是 tokenizer 模型名 |
| `language` | string | `"en"` | 否 | 工作区模板/查询/Skill 提示语言 |
| `timeout_seconds` | number；exclusiveMinimum=0 | `60.0` | 否 | 该组件操作的总等待上限（秒），不是整个 Run 预算 |

### sage.model.anthropic-messages

Uses Claude system, content-block, tool-use, and SSE semantics.

提供能力：`model.provider:anthropic-messages`。支持 scope：agent, run。

| 参数 | 类型 / 范围 | 默认值 | schema 必填 | 用途 |
| --- | --- | --- | --- | --- |
| `route` | object | 无固定值；仍需提供/注入 | 是 | 模型路由对象，来自 App models 配置的 models |
| `credential` | 宿主对象 | 省略时 None；通常由宿主解析注入 | 否 | 宿主对象：解析后的凭据 |
| `client` | 宿主对象 | 省略时 None，使用协议默认客户端 | 否 | 宿主对象：模型协议客户端 |
| `provider_instance_id` | string | 省略时 None，由实现生成/选择 | 否 | 宿主指定 provider 实例标识 |

### sage.model.gemini-generate-content

Uses native Gemini Parts, function calls, thought signatures, and SSE.

提供能力：`model.provider:gemini-generate-content`。支持 scope：agent, run。

| 参数 | 类型 / 范围 | 默认值 | schema 必填 | 用途 |
| --- | --- | --- | --- | --- |
| `route` | object | 无固定值；仍需提供/注入 | 是 | 模型路由对象，来自 App models 配置的 models |
| `credential` | 宿主对象 | 省略时 None；通常由宿主解析注入 | 否 | 宿主对象：解析后的凭据 |
| `client` | 宿主对象 | 省略时 None，使用协议默认客户端 | 否 | 宿主对象：模型协议客户端 |
| `provider_instance_id` | string | 省略时 None，由实现生成/选择 | 否 | 宿主指定 provider 实例标识 |

### sage.model.openai-chat-completions

Streams chat messages and function calls through /chat/completions.

提供能力：`model.provider:openai-chat-completions`。支持 scope：agent, run。

| 参数 | 类型 / 范围 | 默认值 | schema 必填 | 用途 |
| --- | --- | --- | --- | --- |
| `route` | object | 无固定值；仍需提供/注入 | 是 | 模型路由对象，来自 App models 配置的 models |
| `credential` | 宿主对象 | 省略时 None；通常由宿主解析注入 | 否 | 宿主对象：解析后的凭据 |
| `client` | 宿主对象 | 省略时 None，使用协议默认客户端 | 否 | 宿主对象：模型协议客户端 |
| `provider_instance_id` | string | 省略时 None，由实现生成/选择 | 否 | 宿主指定 provider 实例标识 |

### sage.model.openai-responses

Uses typed input/output items and Responses streaming events.

提供能力：`model.provider:openai-responses`。支持 scope：agent, run。

| 参数 | 类型 / 范围 | 默认值 | schema 必填 | 用途 |
| --- | --- | --- | --- | --- |
| `route` | object | 无固定值；仍需提供/注入 | 是 | 模型路由对象，来自 App models 配置的 models |
| `credential` | 宿主对象 | 省略时 None；通常由宿主解析注入 | 否 | 宿主对象：解析后的凭据 |
| `client` | 宿主对象 | 省略时 None，使用协议默认客户端 | 否 | 宿主对象：模型协议客户端 |
| `provider_instance_id` | string | 省略时 None，由实现生成/选择 | 否 | 宿主指定 provider 实例标识 |

### sage.observability.filesystem

Writes model diagnostics under a filesystem root.

提供能力：`observability.diagnostic-sink:default`。支持 scope：process。

| 参数 | 类型 / 范围 | 默认值 | schema 必填 | 用途 |
| --- | --- | --- | --- | --- |
| `root` | string；minLength=1 | 无固定值；仍需提供/注入 | 是 | 存储根目录；不同组件应使用对应独立目录 |
| `legacy_root` | string / null；minLength=1 | 省略时 None，不配置旧目录 | 否 | 旧诊断目录的读取兼容路径 |

### sage.observability.noop

Discards model diagnostics.

提供能力：`observability.diagnostic-sink:default`。支持 scope：process。

没有可配置参数，使用 `config: {}`。

### sage.package-registry.ephemeral

Process-local AgentPackage inventory without restart durability.

提供能力：`package.registry:default`。支持 scope：process。

使用 `config: {}`。`resolver` 是宿主注入的对象依赖，不应写进 YAML；统一入口将它绑定到 App 当前模型目录，让新 Package 的模型 ID 校验使用相同配置。

### sage.protocol.a2a

Projects Sage events into A2A frames.

提供能力：`interface.protocol-adapter:a2a`。支持 scope：process, run。

没有可配置参数，使用 `config: {}`。

### sage.protocol.acp

Projects Sage events into ACP frames.

提供能力：`interface.protocol-adapter:acp`。支持 scope：process, run。

没有可配置参数，使用 `config: {}`。

### sage.protocol.ag-ui

Projects Sage events into AG-UI frames.

提供能力：`interface.protocol-adapter:ag-ui`。支持 scope：process, run。

| 参数 | 类型 / 范围 | 默认值 | schema 必填 | 用途 |
| --- | --- | --- | --- | --- |
| `enable_sage_extensions` | boolean | `true` | 否 | 是否在 AG-UI 输出 Sage 扩展事件 |

### sage.protocol.mcp

Projects Sage events into MCP progress and elicitation frames.

提供能力：`interface.protocol-adapter:mcp`。支持 scope：process, run。

没有可配置参数，使用 `config: {}`。

### sage.protocol.native

Exposes the native Sage event stream without protocol translation.

提供能力：`interface.protocol-adapter:native`。支持 scope：process, run。

没有可配置参数，使用 `config: {}`。

### sage.sandbox.cube-volume

Remote VM execution with a persistent Cube Volume workspace.

提供能力：`execution.sandbox:default`。支持 scope：process。

| 参数 | 类型 / 范围 | 默认值 | schema 必填 | 用途 |
| --- | --- | --- | --- | --- |
| `verification_key` | 宿主对象 | 无固定值；仍需提供/注入 | 是 | 宿主对象/私密值：校验执行授权，不应写入共享 Package |
| `api_url` | string；minLength=1 | `""`；仍需提供/注入 | 是 | Cube 服务地址 |
| `template_id` | string；minLength=1 | `""`；仍需提供/注入 | 是 | Cube 模板标识，必须有效且非空 |
| `proxy_node_ip` | string；minLength=1 | `""`；仍需提供/注入 | 是 | Cube 代理节点地址，必须非空 |
| `api_key` | string | 省略时 None | 否 | 连接服务的私密凭据，勿提交真实值 |
| `volume_driver` | string | 省略时 None | 否 | Cube volume 驱动选项 |

地址/模板字段的构造器占位默认空字符串不满足 schema 的非空要求；必须由宿主填充真实值。

### sage.sandbox.ephemeral

In-process sandbox for tests and ephemeral runs.

提供能力：`execution.sandbox:default`。支持 scope：process。

| 参数 | 类型 / 范围 | 默认值 | schema 必填 | 用途 |
| --- | --- | --- | --- | --- |
| `verification_key` | 宿主对象 | 无固定值；仍需提供/注入 | 是 | 宿主对象/私密值：校验执行授权，不应写入共享 Package |
| `terminal_ttl_seconds` | integer；minimum=1 | `86400` | 否 | 终态对象保留秒数，不是执行超时 |
| `max_retained_terminal_items` | integer；minimum=0 | `1024` | 否 | 保留终态调度/沙箱条目数上限 |
| `process_handlers` | object | 省略时 None，由实现使用空映射 | 否 | 宿主对象映射：内存沙箱进程处理器 |
| `network_handlers` | object | 省略时 None，由实现使用空映射 | 否 | 宿主对象映射：内存沙箱网络处理器 |

### sage.sandbox.local-workspace

Isolates local execution with Linux cgroups/quotas or macOS Seatbelt.

提供能力：`execution.sandbox:default`。支持 scope：process。

| 参数 | 类型 / 范围 | 默认值 | schema 必填 | 用途 |
| --- | --- | --- | --- | --- |
| `verification_key` | 宿主对象 | 无固定值；仍需提供/注入 | 是 | 宿主对象/私密值：校验执行授权，不应写入共享 Package |
| `terminal_ttl_seconds` | integer；minimum=1 | `86400` | 否 | 终态对象保留秒数，不是执行超时 |
| `max_retained_terminal_items` | integer；minimum=0 | `1024` | 否 | 保留终态调度/沙箱条目数上限 |
| `network` | object | 当前工厂未消费 | 否 | 网络设置对象；本地插件工厂当前未直接传递此字段，实际网络授权走执行绑定 |
| `command_path` | string；minLength=1 | 省略时 os.environ[PATH] 或 os.defpath | 否 | 沙箱命令搜索 PATH |
| `read_paths` | array | 省略时空元组 | 否 | 宿主允许额外读取的路径 |
| `linux_cgroup_root` | string | 省略时 None | 否 | Linux cgroup 资源控制根目录 |
| `linux_quota_mount` | string | 省略时 None | 否 | Linux 配额所在挂载点 |
| `linux_execution_uid` | integer；minimum=1 | 省略时 None | 否 | Linux 沙箱执行用户 ID |
| `linux_execution_gid` | integer；minimum=1 | 省略时 None | 否 | Linux 沙箱执行组 ID |

`network` 的 schema 字段如下；当前工厂未消费此对象，不应把它当成有效授权配置。请由宿主执行绑定设置网络策略。

| 参数 | 类型 / 范围 | 默认值 | schema 必填 | 用途 |
| --- | --- | --- | --- | --- |
| `mode` | string；enum=["none", "unrestricted", "allowlist", "proxy"] | 无固定值 | 否 | 网络访问模式 |
| `deny_private_networks` | boolean | 无固定值 | 否 | 是否禁止访问私有网络 |
| `allowed_hosts` | array | 无固定值 | 否 | 允许访问的主机列表 |
| `allowed_ports` | array | 无固定值 | 否 | 允许端口列表 |
| `allowed_schemes` | array | 无固定值 | 否 | 允许的 URL 协议 |
| `proxy_url` | string | 无固定值 | 否 | 网络代理地址 |

### sage.scheduler.ephemeral

Process-local scheduler without restart durability.

提供能力：`execution.scheduler:default`。支持 scope：process。

| 参数 | 类型 / 范围 | 默认值 | schema 必填 | 用途 |
| --- | --- | --- | --- | --- |
| `max_pending_items` | integer；minimum=1 | `1024` | 否 | 调度队列待处理数量上限 |
| `max_retained_terminal_items` | integer；minimum=0 | `4096` | 否 | 保留终态调度/沙箱条目数上限 |
| `max_concurrent_runs` | integer；minimum=1 | `8` | 否 | App 调度并发 Run 上限 |
| `max_concurrent_runs_per_tenant` | integer；minimum=1 | `2` | 否 | 单租户调度并发 Run 上限 |
| `lease_seconds` | number；exclusiveMinimum=0 | `172800`（48 小时） | 否 | 执行租约时长（秒），由 dispatcher 定期续租 |

### sage.scheduler.filesystem

Persists scheduler items on the local filesystem.

提供能力：`execution.scheduler:default`。支持 scope：process。

| 参数 | 类型 / 范围 | 默认值 | schema 必填 | 用途 |
| --- | --- | --- | --- | --- |
| `max_pending_items` | integer；minimum=1 | `1024` | 否 | 调度队列待处理数量上限 |
| `max_retained_terminal_items` | integer；minimum=0 | `4096` | 否 | 保留终态调度/沙箱条目数上限 |
| `max_concurrent_runs` | integer；minimum=1 | `8` | 否 | App 调度并发 Run 上限 |
| `max_concurrent_runs_per_tenant` | integer；minimum=1 | `2` | 否 | 单租户调度并发 Run 上限 |
| `lease_seconds` | number；exclusiveMinimum=0 | `172800`（48 小时） | 否 | 执行租约时长（秒），由 dispatcher 定期续租 |
| `root` | string；minLength=1 | 无固定值；仍需提供/注入 | 是 | 存储根目录；不同组件应使用对应独立目录 |

### sage.session-memory.noop

Disables searchable Session history without changing Agent logic.

提供能力：`session-memory.provider:default`。支持 scope：agent, process。

没有可配置参数，使用 `config: {}`。

### sage.session-memory.sqlite-bm25

Durable per-session BM25 index over canonical Session history.

提供能力：`session-memory.provider:default`。支持 scope：agent, process。

| 参数 | 类型 / 范围 | 默认值 | schema 必填 | 用途 |
| --- | --- | --- | --- | --- |
| `root` | string；minLength=1 | 无固定值；仍需提供/注入 | 是 | 存储根目录；不同组件应使用对应独立目录 |

### sage.session.ephemeral

Full lifecycle semantics without restart durability.

提供能力：`session.store:default`。支持 scope：process。

没有可配置参数，使用 `config: {}`。

### sage.session.filesystem

Compact authoritative checksummed state per Session.

提供能力：`session.store:default`。支持 scope：process。

| 参数 | 类型 / 范围 | 默认值 | schema 必填 | 用途 |
| --- | --- | --- | --- | --- |
| `root` | string；minLength=1 | 无固定值；仍需提供/注入 | 是 | 存储根目录；不同组件应使用对应独立目录 |

### sage.session.mysql

Durable per-Session MySQL store with appended Run events. No global Session index.

提供能力：`session.store:default`。支持 scope：process。

| 参数 | 类型 / 范围 | 默认值 | schema 必填 | 用途 |
| --- | --- | --- | --- | --- |
| `dsn` | string；minLength=1 | 无固定值；仍需提供/注入 | 是 | 数据库连接串 |
| `table_prefix` | string | `"sagent"` | 否 | 数据库表名前缀 |

### sage.session.postgres

Durable per-Session PostgreSQL store with appended Run events. Single-process writers; no global Session index.

提供能力：`session.store:default`。支持 scope：process。

| 参数 | 类型 / 范围 | 默认值 | schema 必填 | 用途 |
| --- | --- | --- | --- | --- |
| `dsn` | string；minLength=1 | 无固定值；仍需提供/注入 | 是 | 数据库连接串 |
| `schema_name` | string；minLength=1 | `"sage_v2"` | 否 | Postgres schema 名 |
| `table_prefix` | string；minLength=1 | `"sagent"` | 否 | 数据库表名前缀 |

### sage.skill.filesystem

Lazy, bounded, symlink-safe Skill catalog and source.

提供能力：`skill.catalog:filesystem`、`skill.source:filesystem`。支持 scope：agent, process。

| 参数 | 类型 / 范围 | 默认值 | schema 必填 | 用途 |
| --- | --- | --- | --- | --- |
| `roots` | array；minItems=1 | 无固定值；仍需提供/注入 | 是 | Skill 搜索根目录数组 |
| `max_files` | integer；minimum=1 | `2000` | 否 | 发现/读取 Skill 文件数上限 |
| `max_total_bytes` | integer；minimum=1 | `67108864` | 否 | Skill 文件总字节上限 |

### sage.skill.loading.lazy

Loads Skill material only when it is asked for, within a token budget.

提供能力：`skill.loading:default`。支持 scope：agent, run。

| 参数 | 类型 / 范围 | 默认值 | schema 必填 | 用途 |
| --- | --- | --- | --- | --- |
| `max_active_characters` | integer；minimum=1 | `24000` | 否 | 活动 Skill 内容的精确字符存储上限 |

### sage.tool-selection.direct

Sends every policy-allowed Tool to the model. Best for small catalogs.

提供能力：`tool.selection-policy:default`。支持 scope：agent, run。

没有可配置参数，使用 `config: {}`。

### sage.tool-selection.lexical

Ranks Tool names, descriptions, and parameters locally like a search engine.

提供能力：`tool.selection-policy:default`。支持 scope：agent, run。

| 参数 | 类型 / 范围 | 默认值 | schema 必填 | 用途 |
| --- | --- | --- | --- | --- |
| `max_visible_tools` | integer；minimum=1, maximum=10000 | `24` | 否 | 发送给模型的完整工具 schema 数量上限 |
| `model_timeout_seconds` | number；exclusiveMinimum=0, maximum=120 | `60.0` | 否 | 模型辅助工具选择等待上限（秒） |

### sage.tool-selection.llm

Uses a fast model and recent context to select relevant Tools.

提供能力：`tool.selection-policy:default`。支持 scope：agent, run。

| 参数 | 类型 / 范围 | 默认值 | schema 必填 | 用途 |
| --- | --- | --- | --- | --- |
| `max_visible_tools` | integer；minimum=1, maximum=10000 | `24` | 否 | 发送给模型的完整工具 schema 数量上限 |
| `model_timeout_seconds` | number；exclusiveMinimum=0, maximum=120 | `60.0` | 否 | 模型辅助工具选择等待上限（秒） |

### sage.tool-selection.recent

Keeps recently called Tools first, then fills the remaining count deterministically.

提供能力：`tool.selection-policy:default`。支持 scope：agent, run。

| 参数 | 类型 / 范围 | 默认值 | schema 必填 | 用途 |
| --- | --- | --- | --- | --- |
| `max_visible_tools` | integer；minimum=1, maximum=10000 | `24` | 否 | 发送给模型的完整工具 schema 数量上限 |
| `model_timeout_seconds` | number；exclusiveMinimum=0, maximum=120 | `60.0` | 否 | 模型辅助工具选择等待上限（秒） |

### sage.tool.ephemeral

In-memory Tool catalog and executor without restart durability.

提供能力：`tool.catalog:ephemeral`、`tool.executor:ephemeral`。支持 scope：agent, process, run。

| 参数 | 类型 / 范围 | 默认值 | schema 必填 | 用途 |
| --- | --- | --- | --- | --- |
| `tools` | 宿主对象 | `[]` | 否 | 宿主工具定义集合 |
| `handlers` | 宿主对象 | `{}` | 否 | 宿主工具处理器映射 |

### sage.tool.mcp

Bridges configured MCP servers into the Sage Tool catalog and executor.

提供能力：`tool.catalog:mcp`、`tool.executor:mcp`。支持 scope：agent, process。

| 参数 | 类型 / 范围 | 默认值 | schema 必填 | 用途 |
| --- | --- | --- | --- | --- |
| `servers` | array | `[]` | 否 | MCP 服务列表，嵌套字段见下表 |
| `session_factory` | 宿主对象 | 省略时 None，使用默认会话工厂 | 否 | 宿主对象：MCP 会话工厂 |

`servers[]` 的完整字段：

| 参数 | 类型 / 范围 | 默认值 | schema 必填 | 用途 |
| --- | --- | --- | --- | --- |
| `name` | string；minLength=1, maxLength=255 | 无固定值；仍需提供/注入 | 是 | MCP 服务唯一名称 |
| `protocol` | string；enum=["stdio", "sse", "streamable_http"] | 无固定值；仍需提供/注入 | 是 | OTLP 协议或 MCP 传输协议 |
| `url` | string / null | `null` | 否 | HTTP/SSE MCP 服务地址 |
| `api_key` | string / null | `null` | 否 | 连接服务的私密凭据，勿提交真实值 |
| `command` | string / null | `null` | 否 | stdio MCP 启动命令 |
| `args` | array | `[]` | 否 | stdio 命令参数数组 |
| `env` | object | `{}` | 否 | stdio 子进程环境变量映射 |
| `timeout_seconds` | number；exclusiveMinimum=0 | `30` | 否 | MCP 连接、初始化和工具发现等待上限（秒），不限制工具执行时长 |
| `call_timeout_seconds` | number / null；exclusiveMinimum=0 | `null` | 否 | 单次工具执行截止时间（秒）；默认持续等待结果，仍可取消。HTTP/SSE 读取等待同步使用此配置，避免 SDK 默认读取超时中断长任务 |
| `required` | boolean | `true` | 否 | 此 MCP 服务是否为必需依赖 |
| `max_tools` | integer；exclusiveMinimum=0, maximum=10000 | `256` | 否 | 发现工具数上限 |
| `max_pages` | integer；exclusiveMinimum=0, maximum=1024 | `64` | 否 | 发现分页数上限 |
| `max_schema_bytes` | integer；exclusiveMinimum=0, maximum=16777216 | `262144` | 否 | 工具 schema 大小上限（字节） |
| `max_result_bytes` | integer；exclusiveMinimum=0, maximum=67108864 | `4194304` | 否 | 工具结果大小上限（字节） |

`env` 缺省为空映射；stdio 必须有 command，HTTP/SSE 必须有 url；协议组合还有传输层校验。

### sage.tool.multi-agent

V2-native Fibre and Team delegation tools.

提供能力：`tool.catalog:multi-agent`、`tool.executor:multi-agent`。支持 scope：agent, run。

| 参数 | 类型 / 范围 | 默认值 | schema 必填 | 用途 |
| --- | --- | --- | --- | --- |
| `coordinator` | 宿主对象 | 无固定值；仍需提供/注入 | 是 | 宿主对象：多 Agent 协调器 |
| `runtime` | 宿主对象 | 无固定值；仍需提供/注入 | 是 | 宿主对象：RuntimePort |

### sage.tool.official

V2-native decorator-backed workspace and runtime tools.

提供能力：`tool.catalog:official`、`tool.executor:official`。支持 scope：agent, process, run。

| 参数 | 类型 / 范围 | 默认值 | schema 必填 | 用途 |
| --- | --- | --- | --- | --- |
| `runtime` | 宿主对象 | 无固定值；仍需提供/注入 | 是 | 宿主对象：RuntimePort |

### sage.tool.skill

Decorator-backed Tool operations owned by the Skill module.

提供能力：`tool.catalog:skill`、`tool.executor:skill`。支持 scope：agent, run。

| 参数 | 类型 / 范围 | 默认值 | schema 必填 | 用途 |
| --- | --- | --- | --- | --- |
| `loader` | 宿主对象 | 无固定值；仍需提供/注入 | 是 | 宿主对象：SkillLoader |
| `language` | string | 省略时 None，由提示语言规则决定 | 否 | 工作区模板/查询/Skill 提示语言 |

### sage.trace.langfuse

Exports Agent, model and tool observations to Langfuse.

提供能力：`observability.trace-sink:default`。支持 scope：process。

| 参数 | 类型 / 范围 | 默认值 | schema 必填 | 用途 |
| --- | --- | --- | --- | --- |
| `base_url` | string；minLength=1 | 无固定值；仍需提供/注入 | 是 | 服务入口地址 |
| `public_key_env` | string | `"LANGFUSE_PUBLIC_KEY"` | 否 | 读取公钥的环境变量名 |
| `secret_key_env` | string | `"LANGFUSE_SECRET_KEY"` | 否 | 读取密钥的环境变量名 |
| `service_name` | string | `"sage"` | 否 | Trace 服务名 |
| `ingestion_version` | integer；enum=[3, 4] | `4` | 否 | Langfuse ingestion 协议版本 |
| `environment` | string | `"production"` | 否 | Trace 为环境标签；credentials.environment 为宿主环境变量映射 |
| `content_mode` | string；enum=["metadata", "redacted"] | `"redacted"` | 否 | metadata 只记录元数据；redacted 记录脱敏内容 |
| `max_content_chars` | integer；minimum=256, maximum=65536 | `16384` | 否 | Trace 内容字符截断上限 |
| `sample_rate` | number；minimum=0, maximum=1 | `1.0` | 否 | Trace 采样比例 0–1 |
| `max_queue_size` | integer；minimum=1 | `2048` | 否 | Trace 导出队列上限 |
| `max_active_spans` | integer；minimum=1 | `4096` | 否 | 活动 Trace span 数上限 |
| `timeout_seconds` | number；exclusiveMinimum=0, maximum=30 | `3.0` | 否 | 该组件操作的总等待上限（秒），不是整个 Run 预算 |

### sage.trace.noop

Discards trace spans.

提供能力：`observability.trace-sink:default`。支持 scope：process。

没有可配置参数，使用 `config: {}`。

### sage.trace.otlp

Exports traces over OTLP to Jaeger or a compatible collector.

提供能力：`observability.trace-sink:default`。支持 scope：process。

| 参数 | 类型 / 范围 | 默认值 | schema 必填 | 用途 |
| --- | --- | --- | --- | --- |
| `endpoint` | string；minLength=1 | `"http://127.0.0.1:4317"` | 否 | OTLP collector 地址 |
| `service_name` | string；minLength=1 | `"sage"` | 否 | Trace 服务名 |
| `protocol` | string；enum=["grpc", "http"] | `"grpc"` | 否 | OTLP 协议或 MCP 传输协议 |
| `insecure` | boolean | `true` | 否 | OTLP 是否使用非 TLS 连接 |
| `environment` | string | `"production"` | 否 | Trace 为环境标签；credentials.environment 为宿主环境变量映射 |
| `content_mode` | string；enum=["metadata", "redacted"] | `"redacted"` | 否 | metadata 只记录元数据；redacted 记录脱敏内容 |
| `max_content_chars` | integer；minimum=256, maximum=65536 | `16384` | 否 | Trace 内容字符截断上限 |
| `sample_rate` | number；minimum=0, maximum=1 | `1.0` | 否 | Trace 采样比例 0–1 |
| `max_queue_size` | integer；minimum=1 | `2048` | 否 | Trace 导出队列上限 |
| `max_active_spans` | integer；minimum=1 | `4096` | 否 | 活动 Trace span 数上限 |
| `timeout_seconds` | number；exclusiveMinimum=0, maximum=30 | `3.0` | 否 | 该组件操作的总等待上限（秒），不是整个 Run 预算 |

### sage.workspace.initializer.bare

Creates an empty workspace root without starter files.

提供能力：`workspace.initializer:default`。支持 scope：agent, process。

没有可配置参数，使用 `config: {}`。

### sage.workspace.initializer.claw

Seeds a Claw-style workspace layout and starter files.

提供能力：`workspace.initializer:default`。支持 scope：agent, process。

| 参数 | 类型 / 范围 | 默认值 | schema 必填 | 用途 |
| --- | --- | --- | --- | --- |
| `language` | string；minLength=1 | `"en"` | 否 | 工作区模板/查询/Skill 提示语言 |

## Run 的网络故障自动恢复

`RunConfig.transient_retry_limit` 默认 `null`：主模型推理及该步骤请求准备阶段遇到可重试的 `provider_transient` / `rate_limited` 错误时，不会因重试三次失败就要求人工处理。可显式设为非负整数限制连续重试次数，`0` 表示禁用透明重试。空语义响应、参数错误、鉴权错误、未知工具副作用不属于此无限重试路径。

退避间隔为 1、2、4、8……秒，上限 60 秒。每次等待前原子写入 `step.retry_scheduled` 和运行检查点，保存连续失败次数及下次尝试时间。故障恢复或宿主接管运行后继续处理同一推理步骤，不重复执行已完成工具，不消耗正常步骤额度；成功推理后清零连续失败次数。暂停、取消和显式 `deadline_seconds` 仍有效。

在内置调度器下，等待前持久化 `automatic_resume_at` 后归还 Worker 租约，调度项以该时间延迟重新入队，同时释放租户并发名额。原 Run 保持非终态，观察者的完成 Future 保持等待。Team/Fibre 成员的等待通过可核对的委派任务 ID 汇总给父任务，整棵调用树可在无活动调用时归还根 Worker；已完成兄弟任务的结果直接复用。暂停可提前唤醒等待任务，取消会结算原调用者。直接驱动 Loop 的宿主仍可使用进程内等待；自定义 Scheduler 应实现 `release(..., requeue=True, available_at=...)` 以启用让出 Worker。

恢复驱动或沙箱恢复报出明确可重试且可安全恢复的临时服务、限流或资源错误时，调度器会再次延迟入队，不把它改写为不确定副作用的终态失败。显式运行截止时间仍生效。入队/归还租约的持久化事务会在 Worker 取消前完成，避免关闭服务时中断 fsync 而损坏调度状态。

`RunConfig.automatic_stage_continuation` 默认 `true`，达到 `max_steps` 的阶段边界时自动保存检查点、重置阶段步骤计数，并在同一 Run、同一会话中接续原目标。历史消息、工具结果、总 token 用量、重复行为检测状态不重置。`max_stages` 默认 `null`，可配置正整数限制阶段数；将 `automatic_stage_continuation` 设为 `false` 可恢复步骤上限后的人工恢复行为。截止时间、总 token 上限和显式人工交互不被阶段接续绕过。

Flow 在执行节点前保存稳定的节点执行 ID，并将节点结果与游标、子流程栈原子持久化。运行中断后由 `AgentFlowDriver.recover_interrupted` 恢复，复用原子 Run 与已完成并行分支，不重复已完成操作。Agent 节点的延期等待向根调度项传递唤醒时间并释放 Worker；节点显式完成边界保留。普通 Tool 节点若只有派发记录而无可靠结果，仅通过 runner 的 `recover_interrupted(context)` 对账；缺少该能力时保存未知结果并暂停，不直接重放。恢复时检查原配置身份及 Flow 图哈希。

Scheduler 配置 `preserve_runs_on_shutdown` 默认 `true`：正常关闭服务会保留未完成 Run 和检查点、归还租约，重启后通过持久化执行意图自动接管。设置为 `false` 可使用原有的关闭即失败行为。Filesystem Scheduler 持有独占写锁，新进程获得锁后立即回收旧租约；即使进程在保存检查点之后、延迟入队之前被强杀，也会依据检查点的唤醒时间恢复，不必等待 48 小时租约自然过期。

父子 Run 的 `max_total_tokens` 按执行树累计主任务、兄弟和后代的持久化 `usage.recorded`，不把父预算重新分配给每个子任务；子任务自身更严格的上限仍有效。截止时间取每个祖先的原始 `created_at + deadline_seconds` 中最早者，延迟启动、阶段接续、重启均不重置。每次开始新推理或工具批次前检查预算，并按剩余额度收窄模型输出上限；等待中的调度项最迟在祖先截止时间唤醒。预算耗尽先结算等待中的后代，再发布父任务失败。计费依据供应商实际 usage，已派发的并发推理及不可安全取消的外部操作仍需结算，可能超过阈值；这不是预付费式的精确硬限额。

Desktop 通过标准 App 恢复归档 Agent 和原执行配置。runtime 的 `start_workers: false` 可以推迟 Worker 启动；宿主产品服务准备完毕后调用标准 dispatcher 的 `start()`。无需安装宿主恢复 Driver。恢复不自动重放不确定副作用；跨进程恢复应选择持久化 SessionStore。

Desktop 最后一个窗口退出或客户端租约到期时，只要存在排队、运行、恢复或延期等待的普通根 Run，Sidecar 就继续保活；RSI 原有保活也保留。任务全部结算且没有客户端后，下一次空闲检查会关闭 Sidecar。纯人工等待的挂起 Run 保持持久化，但不单独要求后台进程常驻。

不能把未知结果的写操作作为网络请求直接重发。鉴权、不可用的资源配置、磁盘配额不足、不可核对的外部副作用仍需各自的修复或确认策略；自动恢复不会删除已有产物、提高显式资源额度或宣告未验收目标完成。

MCP 工具使用 `resume_strategy=agent_recovery`。调用期间连接重置、超时或未收到响应时，先核对本地执行回执；仍无法确认则将原始诊断、操作 ID、幂等键和原始参数作为工具错误持久化并反馈给模型，不创建阻塞式人工核对。错误明确标记 `execution_outcome=unknown` 和 `recovery_action=check_status_before_retry`，指导 Agent 先调用可用的状态查询工具或检查已有产物：已完成则复用，仍在执行则等待，确认未执行或可安全重复后才重试。框架不直接重放未知写操作，也不假设所有 MCP 服务都有统一的状态接口。此规则适用于主 Agent、Team/Fibre 子 Agent 和丢失内存回执后的中断恢复。明确返回的 `isError` 仍作为普通工具失败；合法的空内容响应仍有效，`None` 响应不能当作成功。其他工具的显式人工恢复策略保持有效。

本地沙箱启动前检测到工作区超过 `resources.disk_mb` 时，返回 `sandbox.workspace_quota_exceeded`，包含已用字节数、配额及“尚未执行”标记，界面展示具体容量；不会删除已有产物或自动突破显式资源限制。该错误与请求参数错误、实际物理磁盘已满不同。

Desktop、Server 的工作区 `FileSystemPolicy.max_total_bytes` 从有效的 `resources.disk_mb * 1024 * 1024` 派生，不再单独固定为 4 GB；CLI 省略独立 `max_total_bytes` 时也使用此值。CLI 显式设置的独立文件系统上限仍保留。默认 `resources.disk_mb` 仍为 4096，需要更大工作区时应调整资源配置，例如 `32768`。Desktop 配置入口是 `component_configs["execution.sandbox"]["resources"]["disk_mb"]`。

子 Agent 继承父任务已接受的 `runtime_components` 配置快照，创建和恢复时使用同一资源配置；修改全局设置不追溯修改已有任务或沙箱。配置更新应通过新任务及新沙箱生效。

## 源码与维护

字段契约：[runtime.py](../../../sagents/v2/package/manifest/runtime.py)；默认组件：[defaults.py](../../../sagents/v2/composition/defaults.py)；插件参数/工厂：[official.py](../../../sagents/v2/runtime/extensions/official.py)；装配优先级：[assembler.py](../../../sagents/v2/composition/assembler.py)；Agent 组件依赖：[agent_components.py](../../../sagents/v2/composition/agent_components.py)。

新增插件或修改默认值时，同时更新注册 schema、这份参考文档和有关测试。这里列出的注册 schema 不替代 provider 的运行时能力检查。

部分可选参数省略时会由工厂传 Python None，但其 JSON schema 并不允许显式 null；这时应省略字段，不要写 `field: null`。本表标注“省略时 None”指工厂行为。
