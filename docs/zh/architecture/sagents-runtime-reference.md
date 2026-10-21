---
layout: default
title: Runtime 配置参考
parent: 架构
nav_order: 15
lang: zh
ref: v2-detail-sagents-runtime-reference
---

{% include lang_switcher.html %}

# SAgents Runtime 配置参考

Skill 可按“保存管理”和“加载使用”两组配置，详见
[Skill 插件配置与版本行为](sagents-skill-management-and-usage.md)。

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

宿主并发受理不同配置时，可以把独立配置直接传给加载操作：

```python
agent = await app.load_agent(package, runtime=selected_runtime, models=selected_models)
updated = await app.update_agent(
    agent=agent, package=changed_package,
    runtime=selected_runtime, models=selected_models,
)
```

这两个参数会复制、校验后一起参与装配，不修改 `app.runtime_configuration` 或 `app.models`。不同版本可以并行构建，相同版本的并发请求共用一次构建；`update_agent` 仍检查传入的版本是否为当前版本，竞争更新失败后须重新读取当前 handle。会话存储、调度器与安全配置属于 App 身份，不能通过单次加载切换。

执行中、受理中和流式投影使用的版本保持资源引用。其余空闲版本（包括当前配置）最多缓存 64 个，空闲 300 秒后由每 30 秒运行的回收任务释放；当前配置只保留不可变句柄和计划元信息。首个版本承载 App 的通用服务，因此保留至关闭。回收不会删除原有版本快照；通过 `entrypoint()` 使用旧 handle、同步 `app.agent()` 返回的稳定门面或恢复旧 Run 时，SDK 会重新装配并核对原 composition hash。同步门面的 `runtime.start_run/stream` 同样恢复原版本来冻结执行配置，其余 RuntimePort 读操作和控制操作使用 App 的共享运行内核。事件订阅和协议投影在迭代期间持有版本引用，使用结束应关闭迭代器或 detach。租户工作区属于已受理 Run 的 execution snapshot，Server 在受理时根据已验证身份冻结路径，外部租户数量不会导致同一 Agent 重复装配。

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

通过 `default_runtime(session_root)` 取得默认配置，再将配置传给 `build(runtime=...)`，可以改变默认运行目录。默认方案共享的是组件选择，不会读取你电脑 Desktop 的 API Key、模型目录、数据库或个人设置。

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
| `start_workers` | boolean | `true` | 是否在 App 创建时启动 Worker；产品依赖准备好后可以显式启动标准 dispatcher |
| `check_readiness` | boolean | `false` | 是否执行注册能力的 readiness 检查；不能代替真实模型与工具调用验收 |
| `state_root` | string / null | `null` | Agent 版本及恢复状态目录，属于 App 身份，改变需要新建 App |

Identifier 长度 1–192，首字符为字母或数字，后续可用字母、数字和 `._:@/-`。保障名不是任意配置开关，需对应 provider 支持的能力报告。分布式调度要求支持共享写入与提交时执行权校验的会话存储；Redis/MySQL 与 Redis 调度器需要使用相同的 Redis 地址。仅切换到 MySQL 不代表可多进程共同执行。

工具只通过 `tool.provider` 选择，插件提供一个带 `catalog`、`executor` 的 `ToolProvider`；Skill 只通过 `skill.provider` 选择，由同一提供者实现 `list_skills`、`get_skill`、`fetch`。`skill.management` 仍独立控制发布能力。引用压缩由上下文模块内部执行。旧的成对能力名和独立引用压缩器配置不接受输入，也不自动转换。

## CapabilitySelection 全部字段

```yaml
capabilities:
  context.reducer:
    plugin: sage.context.reducer.window
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
| `grant_tools` | boolean | `false` | 仅用于 `tool.provider`，由可信宿主将该提供者的工具加入运行可用范围；请求身份与授权策略仍生效 |

scope 的含义：process 与 App 进程服务同寿命；tenant 按租户隔离；agent 关联 Agent 实例/版本的装配作用域；run 关联运行作用域。scope 不自动提供跨进程共享，也不会自动给插件加锁。process/tenant/agent 插件必须能处理重叠调用。某些装配点只支持一个 scope 或需要宿主提供相应身份。

## 默认组件

下表中的 `R` 表示 `Path(session_root).expanduser().resolve()`，默认 `session_root=.runtime/sagents`。省略的 config 使用后文插件参数默认值。

| 能力 | build() 默认插件 | 默认参数 / 用途 |
| --- | --- | --- |
| `session.store` | `sage.session.filesystem` | `root=R`；持久化 Session、命令和事件 |
| `memory.provider` | `sage.memory.filesystem-bm25` | `root=R/memory`；长期记忆检索与存储 |
| `session-memory.provider` | `sage.session-memory.sqlite-bm25` | `root=R/session-memory`；会话记忆索引 |
| `skill.loading` | `sage.skill.loading.lazy` | 按需激活 Skill，默认活动内容上限 24000 字符 |
| `agent.continuation-policy` | `sage.agent.continuation.llm-judge` | 模型判断后续执行/结束 |
| `context.reducer` | `sage.context.reducer.persistent-summary` | 持久化摘要压缩上下文 |
| `context.summarizer` | `sage.context.summarizer.model` | 主模型生成摘要 |
| `context.summary-store` | `sage.context.summary-store.session-derived` | 使用会话派生状态存摘要 |
| `memory.recall-query` | `sage.memory.recall-query.llm` | 模型生成记忆检索查询 |
| `tool.selection-policy` | `sage.tool-selection.llm` | 按需选择给模型展示的工具 schema |
| `observability.provider` | `sage.observability.local` | log_root=R/logs; diagnostics_root=R/sessions |
| `workspace.initializer` | `sage.workspace.initializer.claw` | `language=en`；工作区引导资料 |


默认运行方案未显式列出的服务仍有装配回退：调度器 `sage.scheduler.ephemeral`、后台 Job `sage.job.ephemeral`、Package Registry `sage.package-registry.ephemeral`、Trace `sage.observability.noop`、凭据 `sage.credentials.environment`。模型实现由 App 模型目录解析 Agent 的模型 ID 引用。引用压缩由上下文模块内部执行，不单独配置。

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
  observability.provider:
    plugin: sage.observability.local
    config: {log_stream: stderr, log_level: debug, log_format: json}
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
  tool.provider:
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
    plugin: sage.session.mysql
    config:
      dsn: mysql://user:password@localhost/sage
      table_prefix: sagent
```

示例 DSN 仅为格式说明，不要提交真实密码。当前 runtime 文本没有通用 `${ENV}` 插值，建议通过正式凭据提供者或注册工厂解析连接凭据，宿主已有 SessionStore 也通过注册工厂提供。MySQL 需要 aiomysql；数据库存储并不让内存 Job、Scheduler 自动变成持久化或分布式实现。

## 自定义插件、校验和生命周期

使用与内置插件相同的声明和参数入口，先注册再 build：

```python
from sagents.v2 import SAgentBuilder
from examples.v2.host.plugins import reducer_registration

builder = SAgentBuilder()
builder.register(reducer_registration())
app = await builder.build(runtime={
    "capabilities": {
        "context.reducer": {
            "plugin": "example.context.reference-reducer",
            "config": {"minimum_characters": 4},
        },
    },
})
try:
    agent = await app.load_agent("./agents/assistant")
finally:
    await app.close()
```

完整独立插件见 [plugins.py](../../../examples/v2/host/plugins.py)。注册提供 descriptor、config_schema/config_model、factory，以及需要时的 start/stop。插件可以依赖 SDK 公共契约，不要依赖另一个插件实现；不要求为了复用抽取共同基类。

`build` 固定注册表与配置；加载 Agent 时实际装配和校验。未知参数、缺少依赖、不可用插件、scope/API 不匹配、能力保障不满足，都应在装配阶段处理，不能靠“参数被接受”判断组件已生效。`plugins` 声明不等于安装依赖包，YAML 也不等于任意 Python 动态 import。

`config` 在配置、规划和插件上下文入口均只接受有限 JSON 值，不再接收模型、存储、客户端或回调对象。内置插件与自定义插件统一在 `ExtensionDescriptor.dependencies` 声明所需能力，并在工厂中通过 `dependencies.require_unique("model.provider")` 等方法获取实例；指定名称的依赖使用 `require(capability, name)`。依赖进入同一份解析图，统一检查版本、启动顺序、作用域和关闭责任。选择缺失或生命周期不合法时装配失败，不回退到对象配置。

宿主已有对象也通过注册工厂提供。注册项声明 `ownership="borrowed"` 时由宿主负责关闭；声明 `ownership="owned"` 时由 Sage 按插件协议释放。App 持有的插件遵循作用域启动、失败回滚、关闭协议。用 try/finally 关闭 App；不要给每次请求重新创建整个 App，也不要手动关闭共享组件。

## 排查配置与恢复问题

1. 普通 SDK 看 `agent.resolved_plan` 和 `agent.resource_readiness`；`app.resolved_plan` 只是进程首次装配视图。
2. 加载句柄的 `resolved_plan` 描述选择和依赖；`app.run_configuration()` 与 `execution_diagnostics()` 查询已授权 Run 的冻结配置及实际绑定。
3. 在 Run 记录中关联 session_id、run_id、resolved_spec_hash，确认恢复使用受理时的版本。
4. `update_runtime` 修改后续加载的 Agent 配置；已受理 Run 保留原快照。`state_root`、存储、调度器、Job runtime 和安全配置属于 App 身份，变更这些项需要创建新 App。`update_models` / `update_agent` 发布新版本，不替换旧任务使用的版本。
5. 保留 `agent-revisions` 和 Session 数据。恢复时使用原版本、原执行配置及其所需插件；当前 App 的新配置不能覆盖旧 Run。原实现、可信解释器或能力无法恢复时明确报不兼容。
6. readiness 不是模型/工具真实可用性验证；还需有代表性的实际调用。

## 内置插件完整参数表

以下内容来自标准注册表的公开 `inventory()`。`config` 仅接受可序列化参数；工厂对象依赖通过声明的能力协议传递，不放进 runtime。Sage 创建对象与宿主借用对象都通过注册工厂提供，以注册项的 `ownership` 明确关闭责任。

表中“必填”指所在对象内部的要求。嵌套对象本身未提供时，不表示必须提交其全部子字段。未声明默认值的参数以 schema 和实现契约为准。完整 JSON Schema（包括联合类型、额外字段策略和嵌套约束）可通过 `builder.inventory()` 查询；校验错误不会静默回退。

### sage.agent.approval-memory.session

Standard agent.approval-memory implementation with declared dependencies and lifecycle.

版本：`2.0.0`；scope：process；所有权：`owned`。

提供能力：`agent.approval-memory:default` (API `2`)。

依赖：`derived-state.store` (API `>=2,<3`)。

没有固定配置字段；是否允许额外参数以公开 Schema 为准。

### sage.agent.continuation.deterministic

Applies ordered safety, budget, and completion rules without a model call.

版本：`2.0.0`；scope：agent, run；所有权：`owned`。

提供能力：`agent.continuation-policy:default` (API `2`)。

| 参数 | 类型 | 必填 | Schema 默认值 | 约束 |
| --- | --- | --- | --- | --- |
| `repeat_threshold` | `integer` | 否 | `3` | `{"minimum":1}` |

### sage.agent.continuation.explicit-status

Completes only when the model emits an explicit turn_status.

版本：`2.0.0`；scope：agent, run；所有权：`owned`。

提供能力：`agent.continuation-policy:default` (API `2`)。

| 参数 | 类型 | 必填 | Schema 默认值 | 约束 |
| --- | --- | --- | --- | --- |
| `repeat_threshold` | `integer` | 否 | `3` | `{"minimum":1}` |

### sage.agent.continuation.hybrid

Combines deterministic safety rules with an LLM judge for completion.

版本：`2.0.0`；scope：agent, run；所有权：`owned`。

提供能力：`agent.continuation-policy:default` (API `2`)。

依赖能力：`model.provider`。

| 参数 | 类型 | 必填 | Schema 默认值 | 约束 |
| --- | --- | --- | --- | --- |
| `repeat_threshold` | `integer` | 否 | `3` | `{"minimum":1}` |
| `model_binding` | `string` | 否 | `"fast"` | `{"minLength":1}` |
| `timeout_seconds` | `number` | 否 | `60.0` | `{"exclusiveMinimum":0}` |

### sage.agent.continuation.llm-judge

Uses a judge model to decide completion when no tool call is pending.

版本：`2.0.0`；scope：agent, run；所有权：`owned`。

提供能力：`agent.continuation-policy:default` (API `2`)。

依赖能力：`model.provider`。

| 参数 | 类型 | 必填 | Schema 默认值 | 约束 |
| --- | --- | --- | --- | --- |
| `repeat_threshold` | `integer` | 否 | `3` | `{"minimum":1}` |
| `model_binding` | `string` | 否 | `"fast"` | `{"minLength":1}` |
| `timeout_seconds` | `number` | 否 | `60.0` | `{"exclusiveMinimum":0}` |

### sage.agent.tool-policy.default

Standard agent.tool-policy implementation with declared dependencies and lifecycle.

版本：`2.0.0`；scope：process；所有权：`owned`。

提供能力：`agent.tool-policy:default` (API `2`)。

| 参数 | 类型 | 必填 | Schema 默认值 | 约束 |
| --- | --- | --- | --- | --- |
| `approval_strategy` | `string` | 否 | `"configured"` | `{"enum":["configured","always_ask","high_risk","auto_approve"]}` |

### sage.artifact.ephemeral

Process-local artifact bytes without restart durability.

版本：`2.0.0`；scope：process, run；所有权：`owned`。

提供能力：`artifact.store:default` (API `2`)。

没有固定配置字段；是否允许额外参数以公开 Schema 为准。

### sage.artifact.filesystem

Immutable binary artifact files with local restart durability.

版本：`2.0.0`；scope：process；所有权：`owned`。

提供能力：`artifact.store:default` (API `2`)。

| 参数 | 类型 | 必填 | Schema 默认值 | 约束 |
| --- | --- | --- | --- | --- |
| `root` | `string` | 是 | 未声明 | `{"minLength":1}` |

### sage.context.reducer.persistent-summary

Summarizes complete history only after API rejection or reported usage reaches a configured limit.

版本：`2.0.0`；scope：agent, run；所有权：`owned`。

提供能力：`context.reducer:default` (API `2`)。


| 参数 | 类型 | 必填 | Schema 默认值 | 约束 |
| --- | --- | --- | --- | --- |
| `summary_target_tokens` | `integer` | 否 | `1024` | `{"minimum":1}` |
| `protected_recent_units` | `integer` | 否 | `4` | `{"minimum":1}` |
| `max_summary_calls` | `integer` | 否 | `64` | `{"minimum":1}` |
| `max_summary_source_tokens` | `integer` | 否 | `24000` | `{"minimum":1}` |

`max_summary_source_tokens` 作为已有配置字段被 schema 接受；当前内置 reducer 工厂不以它控制输入长度。需要配置摘要源预算时，使用所选 summarizer 能力的正式参数。

### sage.context.reducer.window

Drops complete historical units only when explicitly requested.

版本：`2.0.0`；scope：agent, run；所有权：`owned`。

提供能力：`context.reducer:default` (API `2`)。

没有固定配置字段；是否允许额外参数以公开 Schema 为准。

### sage.context.summarizer.extractive

Preserves bounded task state and Tool outcomes without a model call.

版本：`2.0.0`；scope：agent, process；所有权：`owned`。

提供能力：`context.summarizer:default` (API `2`)。

没有固定配置字段；是否允许额外参数以公开 Schema 为准。

### sage.context.summarizer.model

Uses a model binding to write conversation summaries.

版本：`2.0.0`；scope：agent, run；所有权：`owned`。

提供能力：`context.summarizer:default` (API `2`)。

依赖能力：`model.provider`。

| 参数 | 类型 | 必填 | Schema 默认值 | 约束 |
| --- | --- | --- | --- | --- |
| `model_binding` | `string` | 否 | `"primary"` | `{"const":"primary"}` |
| `max_source_tokens` | `integer` | 否 | `24000` | `{"minimum":1}` |
| `timeout_seconds` | `number` | 否 | `300.0` | `{"exclusiveMinimum":0}` |
| `idle_timeout_seconds` | `number` | 否 | `60.0` | `{"exclusiveMinimum":0}` |

### sage.context.summary-store.ephemeral

In-memory conversation summaries without restart durability.

版本：`2.0.0`；scope：agent, process；所有权：`owned`。

提供能力：`context.summary-store:default` (API `2`)。

没有固定配置字段；是否允许额外参数以公开 Schema 为准。

### sage.context.summary-store.session-derived

Persists conversation summaries through the selected SessionStore.

版本：`2.0.0`；scope：agent, process；所有权：`owned`。

提供能力：`context.summary-store:default` (API `2`)。

依赖能力：`derived-state.store`。

没有固定配置字段；额外参数以公开 Schema 为准。


### sage.credentials.environment

Resolves credentials from process environment variables.

版本：`2.0.0`；scope：process, tenant；所有权：`owned`。

提供能力：`credentials.provider:default` (API `2`)。

| 参数 | 类型 | 必填 | Schema 默认值 | 约束 |
| --- | --- | --- | --- | --- |
| `declarations` | `object` | 否 | 未声明 | `{}` |
| `environment` | `['object', 'null']` | 否 | 未声明 | `{}` |

### sage.credentials.mapping

Resolves credentials from an in-memory host-supplied mapping.

版本：`2.0.0`；scope：process, tenant；所有权：`owned`。

提供能力：`credentials.provider:default` (API `2`)。

| 参数 | 类型 | 必填 | Schema 默认值 | 约束 |
| --- | --- | --- | --- | --- |
| `values` | `object` | 否 | 未声明 | `{}` |
| `source` | `string` | 否 | `"host"` | `{"minLength":1}` |

### sage.derived-state.ephemeral

Standard derived-state.store implementation with declared dependencies and lifecycle.

版本：`2.0.0`；scope：process；所有权：`owned`。

提供能力：`derived-state.store:default` (API `2`)。

没有固定配置字段；是否允许额外参数以公开 Schema 为准。

### sage.execution.binding.ephemeral

Independent virtual files with explicit process-local recovery limits.

版本：`1.0.0`；scope：process；所有权：`owned`。

提供能力：`execution.binding:default` (API `2`)。

依赖：`session.store` (API `>=2,<3`)。

| 参数 | 类型 | 必填 | Schema 默认值 | 约束 |
| --- | --- | --- | --- | --- |
| `workspace_root` | `string` | 否 | `"/workspace"` | `{}` |
| `policy` | `object` | 否 | 未声明 | `{"additionalProperties":false}` |
| `policy.filesystem` | `object` | 否 | 未声明 | `{"additionalProperties":false}` |
| `policy.filesystem.allowed_operations` | `array` | 是 | 未声明 | `{}` |
| `policy.filesystem.allowed_roots` | `array` | 否 | `["/workspace"]` | `{}` |
| `policy.filesystem.protected_paths` | `array` | 否 | `[]` | `{}` |
| `policy.filesystem.max_file_bytes` | `integer / null` | 否 | `null` | `{}` |
| `policy.filesystem.max_total_bytes` | `integer / null` | 否 | `null` | `{}` |
| `policy.filesystem.allow_symlinks` | `boolean` | 否 | `false` | `{}` |
| `policy.process` | `object` | 否 | 未声明 | `{"additionalProperties":false}` |
| `policy.process.enabled` | `boolean` | 否 | `false` | `{}` |
| `policy.process.read_only` | `boolean` | 否 | `false` | `{}` |
| `policy.process.allowed_executables` | `array` | 否 | `[]` | `{}` |
| `policy.process.allow_shell` | `boolean` | 否 | `false` | `{}` |
| `policy.process.allowed_env_names` | `array` | 否 | `[]` | `{}` |
| `policy.process.max_processes` | `integer` | 否 | `1` | `{"exclusiveMinimum":0}` |
| `policy.process.max_wall_time_seconds` | `number / null` | 否 | `null` | `{}` |
| `policy.process.max_output_bytes` | `integer` | 否 | `1048576` | `{"exclusiveMinimum":0}` |
| `policy.process.allow_background_jobs` | `boolean` | 否 | `false` | `{}` |
| `policy.resources` | `object` | 否 | 未声明 | `{"additionalProperties":false}` |
| `policy.resources.cpu_percent` | `number` | 否 | `100` | `{"minimum":1}` |
| `policy.resources.memory_mb` | `integer` | 否 | `1024` | `{"exclusiveMinimum":0}` |
| `policy.resources.disk_mb` | `integer` | 否 | `4096` | `{"exclusiveMinimum":0}` |
| `policy.resources.max_processes` | `integer` | 否 | `64` | `{"minimum":4}` |
| `policy.resources.require_hard_limits` | `boolean` | 否 | `true` | `{}` |
| `policy.network` | `object` | 否 | 未声明 | `{"additionalProperties":false}` |
| `policy.network.mode` | `string` | 否 | `"none"` | `{"enum":["none","allowlist","proxy","unrestricted"]}` |
| `policy.network.proxy_url` | `string / null` | 否 | `null` | `{}` |
| `policy.network.allowed_hosts` | `array` | 否 | `[]` | `{}` |
| `policy.network.allowed_ports` | `array` | 否 | `[]` | `{}` |
| `policy.network.allowed_schemes` | `array` | 否 | `["https"]` | `{}` |
| `policy.network.allowed_methods` | `array` | 否 | `["GET","HEAD"]` | `{}` |
| `policy.network.allowed_request_headers` | `array` | 否 | `["accept","content-type","user-agent"]` | `{}` |
| `policy.network.allow_listen` | `boolean` | 否 | `false` | `{}` |
| `policy.network.deny_private_networks` | `boolean` | 否 | `true` | `{}` |
| `policy.network.max_redirects` | `integer` | 否 | `5` | `{"minimum":0,"maximum":20}` |
| `policy.network.max_request_body_bytes` | `integer` | 否 | `1048576` | `{"minimum":0}` |
| `policy.network.max_response_bytes` | `integer` | 否 | `10485760` | `{"exclusiveMinimum":0}` |
| `policy.network.max_wall_time_seconds` | `number` | 否 | `30` | `{"exclusiveMinimum":0}` |

### sage.execution.binding.local-workspace

Run-owned sandbox leases with admitted execution policy.

版本：`1.0.0`；scope：process；所有权：`owned`。

提供能力：`execution.binding:default` (API `2`)。

| 参数 | 类型 | 必填 | Schema 默认值 | 约束 |
| --- | --- | --- | --- | --- |
| `workspace` | `string` | 是 | 未声明 | `{}` |
| `private_workspace_root` | `string / null` | 否 | `null` | `{}` |
| `policy` | `object` | 否 | 未声明 | `{"additionalProperties":false}` |
| `policy.filesystem` | `object` | 否 | 未声明 | `{"additionalProperties":false}` |
| `policy.filesystem.allowed_operations` | `array` | 是 | 未声明 | `{}` |
| `policy.filesystem.allowed_roots` | `array` | 否 | `["/workspace"]` | `{}` |
| `policy.filesystem.protected_paths` | `array` | 否 | `[]` | `{}` |
| `policy.filesystem.max_file_bytes` | `integer / null` | 否 | `null` | `{}` |
| `policy.filesystem.max_total_bytes` | `integer / null` | 否 | `null` | `{}` |
| `policy.filesystem.allow_symlinks` | `boolean` | 否 | `false` | `{}` |
| `policy.process` | `object` | 否 | 未声明 | `{"additionalProperties":false}` |
| `policy.process.enabled` | `boolean` | 否 | `false` | `{}` |
| `policy.process.read_only` | `boolean` | 否 | `false` | `{}` |
| `policy.process.allowed_executables` | `array` | 否 | `[]` | `{}` |
| `policy.process.allow_shell` | `boolean` | 否 | `false` | `{}` |
| `policy.process.allowed_env_names` | `array` | 否 | `[]` | `{}` |
| `policy.process.max_processes` | `integer` | 否 | `1` | `{"exclusiveMinimum":0}` |
| `policy.process.max_wall_time_seconds` | `number / null` | 否 | `null` | `{}` |
| `policy.process.max_output_bytes` | `integer` | 否 | `1048576` | `{"exclusiveMinimum":0}` |
| `policy.process.allow_background_jobs` | `boolean` | 否 | `false` | `{}` |
| `policy.resources` | `object` | 否 | 未声明 | `{"additionalProperties":false}` |
| `policy.resources.cpu_percent` | `number` | 否 | `100` | `{"minimum":1}` |
| `policy.resources.memory_mb` | `integer` | 否 | `1024` | `{"exclusiveMinimum":0}` |
| `policy.resources.disk_mb` | `integer` | 否 | `4096` | `{"exclusiveMinimum":0}` |
| `policy.resources.max_processes` | `integer` | 否 | `64` | `{"minimum":4}` |
| `policy.resources.require_hard_limits` | `boolean` | 否 | `true` | `{}` |
| `policy.network` | `object` | 否 | 未声明 | `{"additionalProperties":false}` |
| `policy.network.mode` | `string` | 否 | `"none"` | `{"enum":["none","allowlist","proxy","unrestricted"]}` |
| `policy.network.proxy_url` | `string / null` | 否 | `null` | `{}` |
| `policy.network.allowed_hosts` | `array` | 否 | `[]` | `{}` |
| `policy.network.allowed_ports` | `array` | 否 | `[]` | `{}` |
| `policy.network.allowed_schemes` | `array` | 否 | `["https"]` | `{}` |
| `policy.network.allowed_methods` | `array` | 否 | `["GET","HEAD"]` | `{}` |
| `policy.network.allowed_request_headers` | `array` | 否 | `["accept","content-type","user-agent"]` | `{}` |
| `policy.network.allow_listen` | `boolean` | 否 | `false` | `{}` |
| `policy.network.deny_private_networks` | `boolean` | 否 | `true` | `{}` |
| `policy.network.max_redirects` | `integer` | 否 | `5` | `{"minimum":0,"maximum":20}` |
| `policy.network.max_request_body_bytes` | `integer` | 否 | `1048576` | `{"minimum":0}` |
| `policy.network.max_response_bytes` | `integer` | 否 | `10485760` | `{"exclusiveMinimum":0}` |
| `policy.network.max_wall_time_seconds` | `number` | 否 | `30` | `{"exclusiveMinimum":0}` |
| `command_path` | `string / null` | 否 | `null` | `{}` |
| `read_paths` | `array` | 否 | `[]` | `{}` |
| `isolation_python` | `string / null` | 否 | `null` | `{}` |
| `child_workspace_policy` | `string` | 否 | `"shared_parent"` | `{"enum":["shared_parent","private_child","read_only_parent"]}` |
| `linux_cgroup_root` | `string / null` | 否 | `null` | `{}` |
| `linux_quota_mount` | `string / null` | 否 | `null` | `{}` |
| `linux_execution_uid` | `integer / null` | 否 | `null` | `{}` |
| `linux_execution_gid` | `integer / null` | 否 | `null` | `{}` |

### sage.execution.environment

Authenticated identity and borrowed resources of the actual Run.

版本：`2.0.0`；scope：run；所有权：`borrowed`。

提供能力：`execution.environment:default` (API `2`)。

没有固定配置字段；是否允许额外参数以公开 Schema 为准。

### sage.execution.tool-runtime

Official tools bound to the accepted Run sandbox and shared services.

版本：`2.0.0`；scope：run；所有权：`owned`。

提供能力：`execution.tool-runtime:default` (API `2`)。

依赖：`execution.environment` (API `>=2,<3`)、`execution.job-runtime` (API `>=2,<3`)、`artifact.store` (API `>=2,<3`)、`tool.selection-policy` (API `>=2,<3`)。

没有固定配置字段；是否允许额外参数以公开 Schema 为准。

### sage.flow.agent

Runs a child Agent through the shared AgentLoopEngine.

版本：`2.0.0`；scope：run；所有权：`owned`。

提供能力：`flow.node:agent` (API `2`)。

依赖能力：`runtime.kernel`、`agent.child-executor`。

| 参数 | 类型 | 必填 | Schema 默认值 | 约束 |
| --- | --- | --- | --- | --- |
| `descriptor` | `object` | 是 | 未声明 | `{}` |
| `workspace_policy` | `string` | 否 | 未声明 | `{"enum":["private_child","shared_parent","read_only_parent"]}` |

### sage.job.ephemeral

Process-local background Job runtime without restart durability.

版本：`2.0.0`；scope：process；所有权：`owned`。

提供能力：`execution.job-runtime:default` (API `2`)。

| 参数 | 类型 | 必填 | Schema 默认值 | 约束 |
| --- | --- | --- | --- | --- |
| `runners` | `object` | 否 | 未声明 | `{}` |
| `max_concurrent_jobs` | `integer` | 否 | `32` | `{"minimum":1}` |
| `max_admitted_jobs` | `integer` | 否 | `1024` | `{"minimum":1}` |
| `max_job_output_bytes` | `integer` | 否 | `8388608` | `{"minimum":1}` |
| `max_job_output_chunks` | `integer` | 否 | `8192` | `{"minimum":1}` |
| `max_buffered_output_bytes` | `integer` | 否 | `268435456` | `{"minimum":1}` |
| `max_buffered_output_chunks` | `integer` | 否 | `65536` | `{"minimum":1}` |
| `terminal_ttl_seconds` | `integer` | 否 | `86400` | `{"minimum":1}` |
| `max_retained_terminal_jobs` | `integer` | 否 | `4096` | `{"minimum":0}` |
| `max_retained_output_bytes` | `integer` | 否 | `268435456` | `{"minimum":0}` |
| `output_reconnect_window_seconds` | `integer` | 否 | `300` | `{"minimum":0}` |

### sage.observability.langfuse

Unified log, trace and model evidence collection with owned lifecycle.

Provides: `observability.provider:default` (API `2`); process scope; owned lifecycle.

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `log_stdout` | `boolean` | No | `true` |
| `log_stream` | `string` | No | `"stdout"` |
| `log_root` | `string/null` | No | `null` |
| `log_filename` | `string` | No | `"sage.jsonl"` |
| `log_level` | `string` | No | `"info"` |
| `log_format` | `string` | No | `"json"` |
| `log_max_bytes` | `integer` | No | `10485760` |
| `log_backup_count` | `integer` | No | `5` |
| `diagnostic_content_mode` | `string` | No | `"redacted"` |
| `raw_max_bytes` | `integer` | No | `16777216` |
| `base_url` | `string` | Yes | `""` |
| `service_name` | `string` | No | `"sage"` |
| `environment` | `string` | No | `"production"` |
| `public_key_env` | `string` | No | `"LANGFUSE_PUBLIC_KEY"` |
| `secret_key_env` | `string` | No | `"LANGFUSE_SECRET_KEY"` |
| `ingestion_version` | `integer` | No | `4` |
| `content_mode` | `string` | No | `"redacted"` |
| `max_content_chars` | `integer` | No | `16384` |
| `sample_rate` | `number` | No | `1` |
| `max_queue_size` | `integer` | No | `2048` |
| `max_active_spans` | `integer` | No | `4096` |
| `timeout_seconds` | `number` | No | `3` |

### sage.observability.local

Unified log, trace and model evidence collection with owned lifecycle.

Provides: `observability.provider:default` (API `2`); process scope; owned lifecycle.

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `log_stdout` | `boolean` | No | `true` |
| `log_stream` | `string` | No | `"stdout"` |
| `log_root` | `string/null` | No | `null` |
| `log_filename` | `string` | No | `"sage.jsonl"` |
| `log_level` | `string` | No | `"info"` |
| `log_format` | `string` | No | `"json"` |
| `log_max_bytes` | `integer` | No | `10485760` |
| `log_backup_count` | `integer` | No | `5` |
| `diagnostics_root` | `string/null` | No | `null` |
| `diagnostics_storage` | `string` | No | `"files"` |
| `diagnostic_content_mode` | `string` | No | `"redacted"` |
| `raw_max_bytes` | `integer` | No | `16777216` |

### sage.observability.noop

Unified log, trace and model evidence collection with owned lifecycle.

Provides: `observability.provider:default` (API `2`); process scope; owned lifecycle.

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |

### sage.observability.otlp

Unified log, trace and model evidence collection with owned lifecycle.

Provides: `observability.provider:default` (API `2`); process scope; owned lifecycle.

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `log_stdout` | `boolean` | No | `true` |
| `log_stream` | `string` | No | `"stdout"` |
| `log_root` | `string/null` | No | `null` |
| `log_filename` | `string` | No | `"sage.jsonl"` |
| `log_level` | `string` | No | `"info"` |
| `log_format` | `string` | No | `"json"` |
| `log_max_bytes` | `integer` | No | `10485760` |
| `log_backup_count` | `integer` | No | `5` |
| `diagnostic_content_mode` | `string` | No | `"redacted"` |
| `raw_max_bytes` | `integer` | No | `16777216` |
| `endpoint` | `string` | No | `"http://127.0.0.1:4317"` |
| `service_name` | `string` | No | `"sage"` |
| `environment` | `string` | No | `"production"` |
| `protocol` | `string` | No | `"grpc"` |
| `insecure` | `boolean` | No | `true` |
| `content_mode` | `string` | No | `"redacted"` |
| `max_content_chars` | `integer` | No | `16384` |
| `sample_rate` | `number` | No | `1` |
| `max_queue_size` | `integer` | No | `2048` |
| `max_active_spans` | `integer` | No | `4096` |
| `timeout_seconds` | `number` | No | `3` |
| `query_url` | `string` | No | `""` |
| `query_backend` | `string` | No | `""` |
| `query_headers_env` | `string` | No | `"SAGE_OBSERVABILITY_QUERY_HEADERS"` |

### sage.observability.phoenix

Unified log, trace and model evidence collection with owned lifecycle.

Provides: `observability.provider:default` (API `2`); process scope; owned lifecycle.

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `log_stdout` | `boolean` | No | `true` |
| `log_stream` | `string` | No | `"stdout"` |
| `log_root` | `string/null` | No | `null` |
| `log_filename` | `string` | No | `"sage.jsonl"` |
| `log_level` | `string` | No | `"info"` |
| `log_format` | `string` | No | `"json"` |
| `log_max_bytes` | `integer` | No | `10485760` |
| `log_backup_count` | `integer` | No | `5` |
| `diagnostic_content_mode` | `string` | No | `"redacted"` |
| `raw_max_bytes` | `integer` | No | `16777216` |
| `endpoint` | `string` | Yes | `"http://127.0.0.1:6006/v1/traces"` |
| `service_name` | `string` | No | `"sage"` |
| `environment` | `string` | No | `"production"` |
| `project_name` | `string` | No | `"sage"` |
| `api_key_env` | `string` | No | `"PHOENIX_API_KEY"` |
| `content_mode` | `string` | No | `"redacted"` |
| `max_content_chars` | `integer` | No | `16384` |
| `sample_rate` | `number` | No | `1` |
| `max_queue_size` | `integer` | No | `2048` |
| `max_active_spans` | `integer` | No | `4096` |
| `timeout_seconds` | `number` | No | `3` |
| `query_url` | `string` | No | `""` |
| `query_headers_env` | `string` | No | `"SAGE_OBSERVABILITY_QUERY_HEADERS"` |


### sage.memory.filesystem-bm25

Durable scoped Memory records with incremental SQLite FTS5 BM25 recall.

版本：`2.1.0`；scope：agent, process, tenant；所有权：`owned`。

提供能力：`memory.provider:default` (API `2`)。

| 参数 | 类型 | 必填 | Schema 默认值 | 约束 |
| --- | --- | --- | --- | --- |
| `root` | `string` | 是 | 未声明 | `{"minLength":1}` |

### sage.memory.noop

Disables long-term Memory without changing Agent logic.

版本：`2.0.0`；scope：agent, process, tenant；所有权：`owned`。

提供能力：`memory.provider:default` (API `2`)。

没有固定配置字段；是否允许额外参数以公开 Schema 为准。

### sage.memory.recall-query.direct

Uses the current user input as the search_memory query without an additional model request.

版本：`2.0.0`；scope：agent, process, run；所有权：`owned`。

提供能力：`memory.recall-query:default` (API `2`)。

没有固定配置字段；是否允许额外参数以公开 Schema 为准。

### sage.memory.recall-query.llm

Uses a fast model to generate compact keywords before calling search_memory.

版本：`2.0.0`；scope：agent, run；所有权：`owned`。

提供能力：`memory.recall-query:default` (API `2`)。

依赖能力：`model.provider`。

| 参数 | 类型 | 必填 | Schema 默认值 | 约束 |
| --- | --- | --- | --- | --- |
| `language` | `string` | 否 | 未声明 | `{}` |
| `timeout_seconds` | `number` | 否 | `60.0` | `{"exclusiveMinimum":0}` |

### sage.model.anthropic-messages

Uses Claude system, content-block, tool-use, and SSE semantics.

版本：`3.0.0`；scope：agent, run；所有权：`owned`。

提供能力：`model.provider:anthropic-messages` (API `2`)。

依赖能力：`credentials.provider`、`model.client:default`（可选）。

| 参数 | 类型 | 必填 | Schema 默认值 | 约束 |
| --- | --- | --- | --- | --- |
| `route` | `object` | 是 | 未声明 | `{}` |
| `provider_instance_id` | `string` | 否 | 未声明 | `{}` |

### sage.model.concurrency-budget

Standard execution.model-budget implementation with declared dependencies and lifecycle.

版本：`2.0.0`；scope：process；所有权：`owned`。

提供能力：`execution.model-budget:default` (API `2`)。

| 参数 | 类型 | 必填 | Schema 默认值 | 约束 |
| --- | --- | --- | --- | --- |
| `limit` | `integer` | 否 | `8` | `{"exclusiveMinimum":0}` |
| `max_waiting` | `integer` | 否 | `128` | `{"minimum":0}` |
| `wait_timeout_seconds` | `number` | 否 | `60` | `{"exclusiveMinimum":0}` |

### sage.model.gemini-generate-content

Uses native Gemini Parts, function calls, thought signatures, and SSE.

版本：`1.0.0`；scope：agent, run；所有权：`owned`。

提供能力：`model.provider:gemini-generate-content` (API `2`)。

依赖能力：`credentials.provider`、`model.client:default`（可选）。

| 参数 | 类型 | 必填 | Schema 默认值 | 约束 |
| --- | --- | --- | --- | --- |
| `route` | `object` | 是 | 未声明 | `{}` |
| `provider_instance_id` | `string` | 否 | 未声明 | `{}` |

### sage.model.openai-chat-completions

Streams chat messages and function calls through /chat/completions.

版本：`3.0.0`；scope：agent, run；所有权：`owned`。

提供能力：`model.provider:openai-chat-completions` (API `2`)。

依赖能力：`credentials.provider`、`model.client:default`（可选）。

| 参数 | 类型 | 必填 | Schema 默认值 | 约束 |
| --- | --- | --- | --- | --- |
| `route` | `object` | 是 | 未声明 | `{}` |
| `provider_instance_id` | `string` | 否 | 未声明 | `{}` |

### sage.model.openai-responses

Uses typed input/output items and Responses streaming events.

版本：`3.0.0`；scope：agent, run；所有权：`owned`。

提供能力：`model.provider:openai-responses` (API `2`)。

依赖能力：`credentials.provider`、`model.client:default`（可选）。

| 参数 | 类型 | 必填 | Schema 默认值 | 约束 |
| --- | --- | --- | --- | --- |
| `route` | `object` | 是 | 未声明 | `{}` |
| `provider_instance_id` | `string` | 否 | 未声明 | `{}` |

### sage.package-registry.ephemeral

Process-local AgentPackage inventory without restart durability.

版本：`2.0.0`；scope：process；所有权：`owned`。

提供能力：`package.registry:default` (API `2`)。

依赖能力：`package.resolver`。

没有固定配置字段；额外参数以公开 Schema 为准。

### sage.protocol.a2a

Projects Sage events into A2A frames.

版本：`2.0.0`；scope：process, run；所有权：`owned`。

提供能力：`interface.protocol-adapter:a2a` (API `2`)。

没有固定配置字段；是否允许额外参数以公开 Schema 为准。

### sage.protocol.acp

Projects Sage events into ACP frames.

版本：`2.0.0`；scope：process, run；所有权：`owned`。

提供能力：`interface.protocol-adapter:acp` (API `2`)。

没有固定配置字段；是否允许额外参数以公开 Schema 为准。

### sage.protocol.ag-ui

Projects Sage events into AG-UI frames.

版本：`2.0.0`；scope：process, run；所有权：`owned`。

提供能力：`interface.protocol-adapter:ag-ui` (API `2`)。

| 参数 | 类型 | 必填 | Schema 默认值 | 约束 |
| --- | --- | --- | --- | --- |
| `enable_sage_extensions` | `boolean` | 否 | `true` | `{}` |

### sage.protocol.mcp

Projects Sage events into MCP progress and elicitation frames.

版本：`2.0.0`；scope：process, run；所有权：`owned`。

提供能力：`interface.protocol-adapter:mcp` (API `2`)。

没有固定配置字段；是否允许额外参数以公开 Schema 为准。

### sage.protocol.native

Exposes the native Sage event stream without protocol translation.

版本：`2.0.0`；scope：process, run；所有权：`owned`。

提供能力：`interface.protocol-adapter:native` (API `2`)。

没有固定配置字段；是否允许额外参数以公开 Schema 为准。

### sage.sandbox.cube-volume

Remote VM execution with a persistent Cube Volume workspace.

版本：`3.0.0`；scope：process；所有权：`owned`。

提供能力：`execution.sandbox:default` (API `3`)。

| 参数 | 类型 | 必填 | Schema 默认值 | 约束 |
| --- | --- | --- | --- | --- |
| `verification_key` | `object` | 是 | 未声明 | `{}` |
| `api_url` | `string` | 是 | `""` | `{"minLength":1}` |
| `template_id` | `string` | 是 | `""` | `{"minLength":1}` |
| `proxy_node_ip` | `string` | 是 | `""` | `{"minLength":1}` |
| `api_key` | `string` | 否 | 未声明 | `{}` |
| `volume_driver` | `string` | 否 | 未声明 | `{}` |

### sage.sandbox.ephemeral

In-process sandbox for tests and ephemeral runs.

版本：`3.0.0`；scope：process；所有权：`owned`。

提供能力：`execution.sandbox:default` (API `3`)。

依赖能力：`execution.sandbox.process-handlers:default`（可选）, `execution.sandbox.network-handlers:default`（可选）.

| 参数 | 类型 | 必填 | Schema 默认值 | 约束 |
| --- | --- | --- | --- | --- |
| `verification_key` | `object` | 是 | 未声明 | `{}` |
| `terminal_ttl_seconds` | `integer` | 否 | `86400` | `{"minimum":1}` |
| `max_retained_terminal_items` | `integer` | 否 | `1024` | `{"minimum":0}` |

### sage.sandbox.local-workspace

Isolates local execution with Linux cgroups/quotas or macOS Seatbelt.

版本：`3.0.0`；scope：process；所有权：`owned`。

提供能力：`execution.sandbox:default` (API `3`)。

| 参数 | 类型 | 必填 | Schema 默认值 | 约束 |
| --- | --- | --- | --- | --- |
| `verification_key` | `object` | 是 | 未声明 | `{}` |
| `terminal_ttl_seconds` | `integer` | 否 | `86400` | `{"minimum":1}` |
| `max_retained_terminal_items` | `integer` | 否 | `1024` | `{"minimum":0}` |
| `network` | `object` | 否 | 未声明 | `{"additionalProperties":true}` |
| `network.mode` | `string` | 否 | 未声明 | `{"enum":["none","unrestricted","allowlist","proxy"]}` |
| `network.deny_private_networks` | `boolean` | 否 | 未声明 | `{}` |
| `network.allowed_hosts` | `array` | 否 | 未声明 | `{}` |
| `network.allowed_ports` | `array` | 否 | 未声明 | `{}` |
| `network.allowed_schemes` | `array` | 否 | 未声明 | `{}` |
| `network.proxy_url` | `string` | 否 | 未声明 | `{}` |
| `command_path` | `string` | 否 | 未声明 | `{"minLength":1}` |
| `read_paths` | `array` | 否 | 未声明 | `{}` |
| `linux_cgroup_root` | `string` | 否 | 未声明 | `{}` |
| `linux_quota_mount` | `string` | 否 | 未声明 | `{}` |
| `linux_execution_uid` | `integer` | 否 | 未声明 | `{"minimum":1}` |
| `linux_execution_gid` | `integer` | 否 | 未声明 | `{"minimum":1}` |

### sage.scheduler.ephemeral

Process-local scheduler without restart durability.

版本：`2.0.0`；scope：process；所有权：`owned`。

提供能力：`execution.scheduler:default` (API `2`)。

| 参数 | 类型 | 必填 | Schema 默认值 | 约束 |
| --- | --- | --- | --- | --- |
| `preserve_runs_on_shutdown` | `boolean` | 否 | `true` | `{}` |
| `max_pending_items` | `integer` | 否 | `1024` | `{"minimum":1}` |
| `max_retained_terminal_items` | `integer` | 否 | `4096` | `{"minimum":0}` |
| `max_concurrent_runs` | `integer` | 否 | 未声明 | `{"minimum":1}` |
| `max_concurrent_runs_per_tenant` | `integer` | 否 | 未声明 | `{"minimum":1}` |
| `lease_seconds` | `number` | 否 | `172800` | `{"exclusiveMinimum":0}` |

### sage.scheduler.filesystem

Persists scheduler items on the local filesystem.

版本：`2.0.0`；scope：process；所有权：`owned`。

提供能力：`execution.scheduler:default` (API `2`)。

| 参数 | 类型 | 必填 | Schema 默认值 | 约束 |
| --- | --- | --- | --- | --- |
| `preserve_runs_on_shutdown` | `boolean` | 否 | `true` | `{}` |
| `max_pending_items` | `integer` | 否 | 未声明 | `{"minimum":1}` |
| `max_retained_terminal_items` | `integer` | 否 | 未声明 | `{"minimum":0}` |
| `max_concurrent_runs` | `integer` | 否 | 未声明 | `{"minimum":1}` |
| `max_concurrent_runs_per_tenant` | `integer` | 否 | 未声明 | `{"minimum":1}` |
| `lease_seconds` | `number` | 否 | `172800` | `{"exclusiveMinimum":0}` |
| `root` | `string` | 是 | 未声明 | `{"minLength":1}` |

### sage.session-memory.noop

Disables searchable Session history without changing Agent logic.

版本：`2.0.0`；scope：agent, process；所有权：`owned`。

提供能力：`session-memory.provider:default` (API `2`)。

没有固定配置字段；是否允许额外参数以公开 Schema 为准。

### sage.session-memory.sqlite-bm25

Durable per-session BM25 index over canonical Session history.

版本：`2.0.0`；scope：agent, process；所有权：`owned`。

提供能力：`session-memory.provider:default` (API `2`)。

| 参数 | 类型 | 必填 | Schema 默认值 | 约束 |
| --- | --- | --- | --- | --- |
| `root` | `string` | 是 | 未声明 | `{"minLength":1}` |

选中的 Session 存储插件同时发布 `session.store`、`derived-state.store` 和 `artifact.store`。只需在 `session.store` 下配置一次后端，三个能力端口共享存储实例和生命周期；产物通过内部的 Run 绑定视图访问。旧的派生状态和产物适配插件 ID 已删除，现有配置需移除对应选择。其他端口显式选择同一 Session 插件时必须复用其配置，不能另外选择第二个 Session 后端。SDK 仍支持显式选择独立的派生状态和产物存储实现；Server 将产物端口作为宿主管理的存储能力展示，不再单独编辑后端。

### sage.session.ephemeral

Full lifecycle semantics without restart durability.

版本：`2.0.0`；scope：process；所有权：`owned`。

提供能力：`session.store:default`, `derived-state.store:default`, `artifact.store:default` (API `2`)。

没有固定配置字段；是否允许额外参数以公开 Schema 为准。

### sage.session.filesystem

Compact authoritative checksummed state per Session.

版本：`2.1.0`；scope：process；所有权：`owned`。

提供能力：`session.store:default`, `derived-state.store:default`, `artifact.store:default` (API `2`)。

| 参数 | 类型 | 必填 | Schema 默认值 | 约束 |
| --- | --- | --- | --- | --- |
| `root` | `string` | 是 | 未声明 | `{"minLength":1}` |

### sage.session.mysql

Durable per-Session MySQL store with appended Run events. No global Session index.

版本：`2.0.0`；scope：process；所有权：`owned`。

提供能力：`session.store:default`, `derived-state.store:default`, `artifact.store:default` (API `2`)。

| 参数 | 类型 | 必填 | Schema 默认值 | 约束 |
| --- | --- | --- | --- | --- |
| `dsn` | `string` | 是 | 未声明 | `{"minLength":1}` |
| `table_prefix` | `string` | 否 | 未声明 | `{}` |

### sage.session.redis-mysql

Redis execution state shared by Sage instances, with canonical history and attachment bytes archived to MySQL. Supports multi-process writes, cross-process subscriptions and atomic worker fencing. Redis requires AOF and noeviction. Scheduling is selected independently.

Version: `3.0.0`; scope: process; ownership: `owned`。

Provides: `session.store:default`, `derived-state.store:default`, `artifact.store:default` (API `2`)。

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

版本：`2.0.0`；scope：agent, process；所有权：`owned`。

提供能力：`skill.provider:filesystem` (API `2`)、`skill.management:filesystem` (API `2`，只读)。

| 参数 | 类型 | 必填 | Schema 默认值 | 约束 |
| --- | --- | --- | --- | --- |
| `roots` | `array` | 是 | 未声明 | `{"minItems":1}` |
| `max_files` | `integer` | 否 | 未声明 | `{"minimum":1}` |
| `max_total_bytes` | `integer` | 否 | 未声明 | `{"minimum":1}` |

### sage.skill.loading.lazy

Loads Skill material only when it is asked for, within a character storage limit.

版本：`2.0.0`；scope：agent, run；所有权：`owned`。

提供能力：`skill.loading:default` (API `2`)。

| 参数 | 类型 | 必填 | Schema 默认值 | 约束 |
| --- | --- | --- | --- | --- |
| `max_active_characters` | `integer` | 否 | `24000` | `{"minimum":1}` |

### sage.skill.repository.sqlite / sage.skill.repository.memory

版本：`2.0.0`；scope：process。提供 `skill.management`、`skill.provider`。

SQLite 实现保存不可变版本、当前版本和持久化 Run 版本选择；memory 实现仅在进程内保留。
SQLite 必填 `path`；两者支持 `max_files`（默认 2000）和 `max_total_bytes`（默认 67108864）。
发布支持 `expected_version` 乐观并发检查，原件和版本元信息在一个事务中提交。

### sage.skill.workspace.readonly-mount / sage.skill.workspace.auto-sync / sage.skill.workspace.fixed-copy

版本：`2.0.0`；scope：run。提供 `skill.workspace`，依赖实际 Run 的 `execution.environment`。

三者均使用 `skills/<名称>/`。默认 `auto-sync` 先将 Agent 侧修改归档到隐藏的
`.catalog`，然后完整同步管理器版本；管理器旧副本不归档。
`fixed-copy` 首次复制后不跟随来源更新；`readonly-mount` 要求沙箱提供真正的只读挂载，
当前内置沙箱不支持时明确报错。支持 `max_files`（默认 2000）和
`max_total_bytes`（默认 67108864）。

完整分组配置、发布和恢复语义见 [Skill 保存管理与加载使用](sagents-skill-management-and-usage.md)。

### sage.tool-selection.direct

Sends every policy-allowed Tool to the model. Best for small catalogs.

版本：`2.0.0`；scope：agent, run；所有权：`owned`。

提供能力：`tool.selection-policy:default` (API `2`)。

没有固定配置字段；是否允许额外参数以公开 Schema 为准。

### sage.tool-selection.lexical

Ranks Tool names, descriptions, and parameters locally like a search engine.

版本：`2.0.0`；scope：agent, run；所有权：`owned`。

提供能力：`tool.selection-policy:default` (API `2`)。

| 参数 | 类型 | 必填 | Schema 默认值 | 约束 |
| --- | --- | --- | --- | --- |
| `max_visible_tools` | `integer` | 否 | `24` | `{"minimum":1,"maximum":10000}` |
| `model_timeout_seconds` | `number` | 否 | `60.0` | `{"maximum":120,"exclusiveMinimum":0}` |

### sage.tool-selection.llm

Uses a fast model and recent context to select relevant Tools.

版本：`2.0.0`；scope：agent, run；所有权：`owned`。

提供能力：`tool.selection-policy:default` (API `2`)。

| 参数 | 类型 | 必填 | Schema 默认值 | 约束 |
| --- | --- | --- | --- | --- |
| `max_visible_tools` | `integer` | 否 | `24` | `{"minimum":1,"maximum":10000}` |
| `model_timeout_seconds` | `number` | 否 | `60.0` | `{"maximum":120,"exclusiveMinimum":0}` |

### sage.tool-selection.recent

Keeps recently called Tools first, then fills the remaining count deterministically.

版本：`2.0.0`；scope：agent, run；所有权：`owned`。

提供能力：`tool.selection-policy:default` (API `2`)。

| 参数 | 类型 | 必填 | Schema 默认值 | 约束 |
| --- | --- | --- | --- | --- |
| `max_visible_tools` | `integer` | 否 | `24` | `{"minimum":1,"maximum":10000}` |
| `model_timeout_seconds` | `number` | 否 | `60.0` | `{"maximum":120,"exclusiveMinimum":0}` |

### sage.tool.ephemeral

In-memory Tool catalog and executor without restart durability.

版本：`2.0.0`；scope：agent, process, run；所有权：`owned`。

提供能力：`tool.provider:ephemeral` (API `2`)。

依赖能力：`tool.handlers:default`（可选）。

| 参数 | 类型 | 必填 | Schema 默认值 | 约束 |
| --- | --- | --- | --- | --- |
| `tools` | `object` | 否 | 未声明 | `{}` |

### sage.tool.mcp

Bridges configured MCP servers into the Sage Tool catalog and executor.

版本：`2.0.0`；scope：agent, process, run；所有权：`owned`。

提供能力：`tool.provider:mcp` (API `2`)。

依赖能力：`mcp.session-factory:default`（可选）。

| 参数 | 类型 | 必填 | Schema 默认值 | 约束 |
| --- | --- | --- | --- | --- |
| `servers` | `array` | 否 | 未声明 | `{}` |
| `servers[].name` | `string` | 是 | 未声明 | `{"minLength":1,"maxLength":255}` |
| `servers[].protocol` | `string` | 是 | 未声明 | `{"enum":["stdio","sse","streamable_http"]}` |
| `servers[].url` | `string / null` | 否 | `null` | `{}` |
| `servers[].api_key` | `string / null` | 否 | `null` | `{}` |
| `servers[].command` | `string / null` | 否 | `null` | `{}` |
| `servers[].args` | `array` | 否 | `[]` | `{}` |
| `servers[].env` | `object` | 否 | 未声明 | `{"additionalProperties":{"type":"string"}}` |
| `servers[].timeout_seconds` | `number` | 否 | `30` | `{"exclusiveMinimum":0}` |
| `servers[].call_timeout_seconds` | `number` | 否 | `7200` | `{"exclusiveMinimum":0}` |
| `servers[].required` | `boolean` | 否 | `true` | `{}` |
| `servers[].max_tools` | `integer` | 否 | `256` | `{"maximum":10000,"exclusiveMinimum":0}` |
| `servers[].max_pages` | `integer` | 否 | `64` | `{"maximum":1024,"exclusiveMinimum":0}` |
| `servers[].max_schema_bytes` | `integer` | 否 | `262144` | `{"maximum":16777216,"exclusiveMinimum":0}` |
| `servers[].max_result_bytes` | `integer` | 否 | `4194304` | `{"maximum":67108864,"exclusiveMinimum":0}` |

### sage.tool.multi-agent

V2-native Fibre and Team delegation tools.

版本：`2.0.0`；scope：agent, run；所有权：`owned`。

提供能力：`tool.provider:multi-agent` (API `2`)。

依赖能力：`agent.coordinator`、`runtime.kernel`。

没有固定配置字段；额外参数以公开 Schema 为准。

### sage.tool.official

V2-native decorator-backed workspace and runtime tools.

版本：`2.0.0`；scope：run；所有权：`owned`。

提供能力：`tool.provider:official` (API `2`)。

依赖：`execution.tool-runtime` (API `>=2,<3`)。

没有固定配置字段；是否允许额外参数以公开 Schema 为准。

### sage.tool.skill

Decorator-backed Tool operations owned by the Skill module.

版本：`2.0.0`；scope：agent, run；所有权：`owned`。

提供能力：`tool.provider:skill` (API `2`)。

依赖能力：`skill.loader`。

| 参数 | 类型 | 必填 | Schema 默认值 | 约束 |
| --- | --- | --- | --- | --- |
| `language` | `string` | 否 | 未声明 | `{}` |

### sage.workspace.initializer.bare

Creates an empty workspace root without starter files.

版本：`2.0.0`；scope：agent, process；所有权：`owned`。

提供能力：`workspace.initializer:default` (API `2`)。

没有固定配置字段；是否允许额外参数以公开 Schema 为准。

### sage.workspace.initializer.claw

Seeds a Claw-style workspace layout and starter files.

版本：`2.0.0`；scope：agent, process；所有权：`owned`。

提供能力：`workspace.initializer:default` (API `2`)。

| 参数 | 类型 | 必填 | Schema 默认值 | 约束 |
| --- | --- | --- | --- | --- |
| `language` | `string` | 否 | `"en"` | `{"minLength":1}` |

## Run 的网络故障自动恢复

`RunConfig.transient_retry_limit` 默认 `null`：主模型推理及该步骤请求准备阶段遇到可重试的 `provider_transient` / `rate_limited` 错误时，不会因重试三次失败就要求人工处理。可显式设为非负整数限制连续重试次数，`0` 表示禁用透明重试。空语义响应、参数错误、鉴权错误、未知工具副作用不属于此无限重试路径。

退避间隔为 1、2、4、8……秒，上限 60 秒。每次等待前原子写入 `step.retry_scheduled` 和运行检查点，保存连续失败次数及下次尝试时间。故障恢复或宿主接管运行后继续处理同一推理步骤，不重复执行已完成工具，不消耗正常步骤额度；成功推理后清零连续失败次数。暂停、取消和显式 `deadline_seconds` 仍有效。

在内置调度器下，等待前持久化 `automatic_resume_at` 后归还 Worker 租约，调度项以该时间延迟重新入队，同时释放租户并发名额。原 Run 保持非终态，观察者的完成 Future 保持等待。Team/Fibre 成员的等待通过可核对的委派任务 ID 汇总给父任务，整棵调用树可在无活动调用时归还根 Worker；已完成兄弟任务的结果直接复用。暂停可提前唤醒等待任务，取消会结算原调用者。标准运行流程负责调度与等待；自定义 Scheduler 应实现 `release(..., requeue=True, available_at=...)` 以启用让出 Worker。

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
