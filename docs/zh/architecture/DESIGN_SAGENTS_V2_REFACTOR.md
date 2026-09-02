# SAgents V2 模块化与插件化设计

> 状态：当前代码对齐文档。V2 的核心分层、扩展内核、统一 Loop 组合、最终请求
> 预算和单机崩溃恢复边界已经成立；跨协议转换、分布式执行和真实 provider
> 故障注入仍属于后续生产验证。

正式入口是：

```python
from sagents.v2 import SAgent, SAgentBuilder
```

## 结论

SAgents V2 不需要推倒重写。当前方向是合理的：Session/Run 状态机、规范事件、
Agent Loop、领域端口、Extension 微内核和产品宿主已经形成了清晰边界。相比在
`SimpleAgent` 内继续堆叠功能，这套结构更适合长期演进。

但“目录已经拆开”和“Registry 里已经注册”不等于真正完成了解耦、模块化和
插件化。此前审计出的 provider envelope 治理、最终请求预算、Desktop/通用 Loop
双路径、context 插件未消费、Tool 取消和单机队列恢复问题，已经落实到代码与回归
测试。当前定位是：**架构骨架和单机参考实现已经闭环，但不能把它扩大表述为
“所有 provider 均已真实验证”或“已经具备多进程分布式 exactly-once”。**

## 设计目标

V2 遵循四条原则：

1. **小内核**：命令、事件、合法状态迁移、CAS、幂等和副作用顺序由框架统一定义；
2. **领域模块化**：Model、Tool、Context、Skill、Memory、Flow、Execution 各自拥有
   协议和实现，不通过通用 Manager 互相穿透；
3. **能力插件化**：有替换价值的实现通过 capability + port + lifecycle 注入；
4. **宿主解耦**：Desktop、Server 只通过公共契约接入，不被 V2 反向 import。

这里的插件化不是“所有类都注册成插件”。以下内容必须保持为稳定语义，不允许
通过插件改变：

- Run/Session 的状态机和终态定义；
- canonical event 的含义与顺序；
- CAS、幂等、checkpoint 和 suspension 规则；
- 工具必须先记录 proposal/policy，再允许外部副作用；
- 已确认 Session 提交不能被 Memory、诊断或 UI 索引失败回滚。

## 总体分层

```text
Desktop / Server / SDK
        │
        ▼
SAgent + SAgentBuilder + AgentPackage
        │       只在组合阶段选择实现
        ▼
Agent / Flow orchestration
        │       只依赖领域 port
        ▼
Runtime kernel + canonical contracts
        ▲
        │
Model / Tool / Context / Store / Scheduler / Protocol plugins
```

依赖必须向内：领域契约不能 import 实现，核心不能 import Desktop/Server，插件可以
依赖所属领域协议和外部 SDK，但不能依赖产品代码。

### 模块职责

| 模块 | 负责 | 不负责 |
|---|---|---|
| `contracts/` | 命令、事件、Item、Run/Session 类型 | provider SDK、UI DTO |
| `runtime/kernel.py` | 合法生命周期迁移 | Agent prompt、模型协议 |
| `runtime/session/` | 单个已知 Session 的状态、日志、CAS、恢复 | 全局会话列表和搜索 |
| `agent/` | Model/Tool 循环、安全点、委派和策略 | 发现插件、保存 UI 状态 |
| `context/` | 上下文段、历史投影、预算、压缩和摘要 | provider HTTP 请求 |
| `model/` | 统一请求/流协议和 provider adapter | Session 状态迁移 |
| `tool/` | catalog/executor、选择和授权 | 绕过 sandbox 执行宿主命令 |
| `skill/` | 发现、读取、校验和激活 | 产品 Skills 页面 |
| `memory/` | 长期记忆召回与写入 | Session 正史 |
| `flow/` | 使用相同 Run 生命周期执行图 | 第二套 Agent Runtime |
| `runtime/execution/` | Scheduler、Job、binding、workspace、sandbox | 业务 Agent 策略 |
| `runtime/extensions/` | 注册、解析、scope、启动和停止 | 领域实现本身 |
| `interfaces/protocols/` | 把 canonical event 投影为下游协议 | 修改 Runtime 事实 |

完整英文依赖约束见
[`sagents/v2/ARCHITECTURE.md`](../../../sagents/v2/ARCHITECTURE.md)。

## 插件模型

当前 Extension 内核已经实现以下链路：

```text
ExtensionRegistration
  -> ExtensionRegistry
  -> ExtensionResolver
  -> ExtensionCompositionPlan
  -> ExtensionHost
  -> ProviderSet
```

每个插件必须声明：

- 稳定 `plugin_id` 和版本；
- 提供的 capability、名字和 API 版本；
- 依赖的其他 capability；
- 支持的 `process / tenant / agent / run` 生命周期；
- 可验证的配置 schema；
- 能力事实，例如是否跨重启持久、是否支持多进程写、是否提供真实隔离。

Resolver 负责版本匹配、歧义、缺失依赖和循环依赖；Host 按拓扑顺序启动，在失败
或关闭时逆序释放。长生命周期插件不能依赖短生命周期插件。

`runtime/extensions/` 只能放注册与生命周期机制。具体实现仍放在自己的领域内，
例如 OpenAI Responses adapter 位于 `model/plugins/`，Filesystem SessionStore 位于
`runtime/session/`。

### Manifest 的职责

`sage.yaml.plugins` 是允许加载的插件白名单和默认配置，不负责安装 Python 包。
`runtime.capabilities` 选择具体实现与 scope。部署系统或管理员负责安装插件。

Builder 直接注入的 `with_model_provider()`、`with_session_store()` 等接口用于测试，
或用于宿主已经持有连接对象的场景。直接注入只是另一种组合输入，不能绕过领域
协议、生命周期和 composition identity。

### 哪些能力适合做插件

满足以下条件才进入扩展系统：

- 存在稳定、可测试的领域 port；
- 至少有两个有意义的实现，或明确由宿主提供实现；
- 有独立配置和生命周期；
- 替换实现不会改变 canonical runtime 语义；
- 能提供跨实现的 conformance tests。

当前适合插件化的能力包括 Model provider、SessionStore、Memory、Session Memory、
Tool provider、Skill provider、Context reducer/summarizer/token estimator、continuation
policy、Scheduler、JobRuntime、sandbox、artifact store 和 protocol adapter。

## 组合根

### 当前实现

`SAgentBuilder` 负责：

- 解析 AgentPackage 和 policy ceiling；
- 加载显式声明的插件；
- 创建 Extension scope；
- 解析 credentials、model、store、tool 和基础设施；
- 构造 `SAgentApplication` 并拥有资源释放顺序。

`AgentCompositionFactory` 不发现插件，只把已经解析好的 Model、Tool、Context、
Memory 和 policy 组装成 `AgentLoopEngine`。执行中的 `SAgent`、Loop 和 Kernel 都不应
查询全局 Registry。

### 当前实现边界

ExtensionHost 已经能一次解析完整依赖图，但 Builder 的 `_create_capability()` 仍以
单个 capability 为单位重复 plan/open scope。现在通用 Builder 已实际消费
continuation/context capability 选择，宿主依赖在 manifest 配置之后锁定注入；Desktop
和通用路径也已共用 `AgentCompositionFactory.create_engine`。Desktop 仍负责自己的授权
策略、Context providers 和产品级组件生命周期。

`SAgentApplication.resolved_plan` 现在暴露不可变的 `ResolvedApplicationPlan`，列出
capability、plugin/host 来源、scope、API version、plugin 依赖边和最终 composition
hash；计划中不保存 credential 或原始敏感配置。Builder 内部仍可按生命周期打开多个
scope，但对外只有一张最终装配事实表，执行 Loop 也只有一个构造入口。

### 目标结构

```text
Package + host overrides
        -> ResolvedApplicationPlan
        -> ExtensionHost 一次解析完整 capability graph
        -> ApplicationProviders
        -> 唯一 AgentRuntimeComposer
        -> SAgentApplication
```

Desktop 只提供产品能力：Session 索引、用户身份、授权策略、ExecutionBinding、窗口/UI
适配和产品 ContextSegmentProvider。它不再复制 Agent Loop 的组装逻辑。

## Provider 协议边界

canonical Session history 与 provider 原生续传状态必须分开：

- `MessageItem`、`ToolCallItem`、`ToolResultItem` 是可移植的 Runtime 正史；
- reasoning 的可见摘要用于 UI/诊断；
- OpenAI reasoning item、Anthropic thinking/signature 等是 provider-scoped 的续传状态；
- provider 续传状态在活动工具回合中属于恢复所需事实，不能只存诊断文件。

Agent Loop 不应理解每家 provider 的字段。Model provider 应返回一个版本化、opaque
的 replay envelope，Loop 只负责随 checkpoint 保存并在下一步原样交回相同 provider。
adapter 自己负责捕获、校验、序列化和 wire replay。

切换 model route 或 protocol 时必须有明确策略：

- 在安全边界转换为 canonical history；或
- 因存在不兼容的活动 replay state 而拒绝切换。

不能静默丢弃后继续执行。当前代码已经增加按协议 namespace 隔离的
`provider_state`：OpenAI Responses 保存 reasoning item，Anthropic 保存 thinking block
和 signature，OpenAI-compatible 保存 reasoning content/details；状态随 assistant Item
写入 Session history，并只由匹配的 adapter 回放。

这条主链已经闭环。新写入的 namespace 使用 `schema_version=1`，持久化前要求有限
JSON 且总大小不超过 8 MiB；旧 v0 字典继续由匹配 adapter 读取。切换协议时外部
namespace 不会被消费，同 namespace 的未知版本会 fail closed。尚未实现跨协议转换，
真实 provider 与 crash/resume 测试仍需补齐。

协议依据：OpenAI 要求手工管理上下文时保留并重放 response output items，无状态
场景还需要 encrypted reasoning item；Anthropic 在 thinking + tool use 场景要求原样
回传完整 thinking block 和 signature。参见 [OpenAI model guidance](https://developers.openai.com/api/docs/guides/latest-model)
和 [Anthropic extended thinking](https://platform.claude.com/docs/en/build-with-claude/extended-thinking)。

## Context 与 Prompt 边界

上下文模块负责生成 provider-neutral 的请求内容，但预算验收对象必须是最终 wire
request：

```text
system/developer segments
+ 压缩后的 Session history
+ 最新 user/task
+ hidden tool index
+ continuation guidance
+ 选中的 tool schemas
+ provider protocol overhead
```

当前实现将 tool schema、hidden index、continuation guidance 和协议固定开销建模为
显式不可压缩 reservation：它们只占预算，不进入 reducer、summary 或
`historical_messages`。压缩率只比较被替换的 canonical 可压缩内容。实际流程是：

1. Tool 选择先确定；
2. 计算四类不可压缩 reservation；
3. Context reducer 只压缩 canonical 会话投影；
4. 原样追加不可压缩内容并复核最终请求；
5. provider context overflow 映射成 `model.context_window_exceeded`；
6. 仅当没有产生语义输出时，允许一次增加 reservation 后重压缩。

Persistent Summary 必须满足：

- 永远保护最新真实 user 请求和当前任务边界；
- 保持完整 tool call/result 对；
- 保留活动 goal/plan/todo 和当前 provider replay state；
- 摘要明确标注为“不可信的历史参考”，不能提升为新的高优先级指令；
- 单条超大 Tool 结果只允许通过显式、持久化的 artifact/reference 压缩，禁止静默截断；
- 摘要前后 token 必须实际下降，否则保持原历史并报告类型化错误。

`cache_segment` metadata 由 Context 层表达稳定性。当前 Anthropic adapter 会在启用
`prompt_cache` 时，把 stable/semi-stable segment 和最后一个 Tool 定义转换为显式
`cache_control`；OpenAI 路径继续依赖其协议自身的缓存方式。是否命中仍必须通过最终
provider payload 和 usage 验证，不能只凭 metadata 或稳定排序推断。Anthropic 协议
规则参见 [Prompt caching](https://platform.claude.com/docs/en/build-with-claude/prompt-caching)。

## Runtime、持久化与执行

SAgents 只管理一个已知 `session_id` 及其中的 Run。Session 列表、搜索、排序、标题、
收藏、归档、标签和跨 Session lineage 都属于 Desktop/Server。

`FilesystemSessionStore` 保存每个 Session 的 checksummed state 和 mutation journal。
`derived/` 摘要、Memory 和 DiagnosticSink 都不是 Session 正史。

需要特别区分：

```text
Session durability   != execution durability
```

默认 Scheduler、JobRuntime、artifact store 和 package registry 仍是
single-process/ephemeral 参考实现。可选 `sage.scheduler.filesystem` 会原子保存 pending、
lease 和 fencing counter；Dispatcher 在重启后从 WorkItem 恢复 RequestContext：
`QUEUED/RESUMING` 可重新调度，已终态或已暂停的工作只结算队列，缺少安全检查点的
`RUNNING/SUSPEND_REQUESTED` 以 `execution.worker_restarted` 失败，禁止静默重放副作用。
该实现是单主机、单 writer 的重启持久化，不是分布式 Scheduler。生产 profile 仍须：

- 使用可跨进程恢复的 Scheduler/JobRuntime；
- 启动时扫描并 reconcile 非终态 Run；
- 用 lease + fencing 防止旧 worker 写入；Scheduler 插件必须实现
  `execute_fenced(lease, operation)`，在整个 Session mutation 期间保持 lease 权威；
- 对无法恢复的外部副作用进入 unknown/reconcile，而不是重复执行。

SAgents 内核不提供数据库事务，也不绑定 PostgreSQL、MySQL 或 Redis。它只定义
`supports_atomic_fenced_mutations` 语义能力；本地插件用进程锁实现，服务器插件可用
自己的事务、行锁、advisory lock 或其他线性一致机制实现。是否支持多主机 claim 由独立的
`supports_distributed_claims` 声明，不能由“支持 fencing”推断。

底层 `SessionStore` 是可信内部 port。Server 的 HTTP/RPC/WebSocket 层应使用
`application.service("session.access")`；其读取、订阅、checkpoint、interaction 和删除
接口都要求 `RequestContext` 并校验 durable Session owner，不能直接暴露仅凭 ID 的读取。

Model stream 现在保留一个未被反复取消的读取 task，并旁路轮询 durable Run 状态和
deadline；即使 provider 没有产生 delta，pause、cancel 和 deadline 也能关闭 stream，
进入 checkpoint、终态或类型化恢复。Tool cancellation 是显式可选 port：只有
ToolDefinition 声明 cooperative/forceable 且 Executor 实现 `cancel()` 时才中断；
`cancelled`、`too_late`、`unknown` 分开处理。不可取消 Tool 会先结算，再在
`SUSPEND_REQUESTED` 下原子提交结果与 checkpoint；终态 Run 的迟到结果不会发布。

## 数据权威性

```text
Session state / checkpoint -> 生命周期与 canonical history 的权威来源
active provider replay     -> 精确恢复当前 provider 工具回合所需
derived/                   -> 可删除、可重建的摘要和激活状态
MemoryProvider             -> 独立长期记忆
DiagnosticSink             -> 可选诊断，不参与恢复
Desktop session index      -> 产品列表与搜索元数据
```

模型诊断仍保存 provider-facing 请求、规范化响应、请求类型和必要关联信息，放在所属
Run 目录下；它不能成为恢复输入。

## 演进优先级

### P0：Provider 状态治理与生产验证

- 已完成首版 opaque `provider_state` 传输、Session 重建和三类 adapter 回放；
- 已增加 schema version、大小上限、有限 JSON 校验和 legacy-v0 读取；
- 已明确禁止猜测式跨协议转换；Run 冻结创建时的 model route 与 Agent runtime definition，恢复时只复用当前凭据和显式追加授权，其他配置变更仅影响新 Run；
- 保留 cumulative snapshot 归一化，增加乱序/重复/残缺 chunk 反例；
- 在 golden tests 之外增加真实 provider、进程重启和 resume 测试。

### P1：统一组合与完整预算

- 已引入单一、可检查且不泄漏敏感配置的 `ResolvedApplicationPlan`；
- 已让通用 Builder 与 Desktop 共用 `AgentCompositionFactory.create_engine`；
- 已让 continuation/context capability 真正由 manifest 选择；
- 已对最终请求预算增加不可压缩 reservation 和 provider overflow recovery；
- 已加固 latest-user、tool pair 和 summary compression gain；
- 已增加 `context.unit-compactor` port；默认实现只消费 Tool 提供并随 Session
  持久化的 `context_reference`，没有引用时 fail closed，绝不静默截断。

### P1：生产执行恢复

- 已增加单机 filesystem Scheduler、Dispatcher 启动恢复和原子 fenced mutation port；
  durable JobRuntime 与多进程 lease provider 仍待生产插件实现；
- Tool 一旦跨过 side-effect barrier，未明确证明 `not_applied` 的写操作异常统一进入
  unknown/reconcile，禁止按普通失败继续；
- 已把 deadline/cancellation 传播到 Model stream 和显式可取消 Tool；
- 对 crash、lease takeover、未知副作用和迟到结果做故障注入测试。

### P2：性能与可观测性

- 已让 FilesystemSessionStore 直接导出当前 Session aggregate，不再为一次提交序列化
  全部已加载 Session；协调器仍保留 store 级原子锁，后续分片必须先证明跨 Run 的
  Session sequence、CAS、删除树和失败回滚语义不被破坏；
- 增加长会话、多 Session、token stream 的 soak/benchmark；
- 记录最终请求大小、tool schema tokens、cache marker/hash 和 cache usage；
- `ResolvedApplicationPlan` 已展示 capability、plugin、scope、依赖和来源；后续增加
  面向运维的差异化 composition report。

## 验收标准

新增模块或插件只有同时满足以下条件才算完成：

- 依赖方向检查通过，V2 不 import legacy 或 app；
- port 有独立 conformance tests，不绑定某个内置实现；
- plugin 声明 capability、版本、scope、配置和真实保证；
- 启动回滚、逆序关闭和 scope 隔离有测试；
- RuntimeEvent 和恢复语义保持 provider-neutral；
- provider golden tests 检查最终 messages、tools、replay state 和 cache marker；
- Desktop/Server 走统一 composer，差异只通过显式 host provider 注入；
- crash、context overflow、cancel、deadline 和未知副作用都有反例测试。

## 阅读顺序

```text
sagent.py
-> builder.py
-> application.py
-> runtime/extensions/
-> agent/factory.py
-> agent/engine.py
-> contracts/
-> runtime/kernel.py
-> runtime/session/
-> context/
-> model/
-> tool/
```

详细目录和使用示例见
[`sagents/v2/README.md`](../../../sagents/v2/README.md)。实现事实以源码、最终 provider
payload 和 `tests/sagents/v2/` 的可执行契约为准。
