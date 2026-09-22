> 历史资料：本页已退出当前文档，可能包含旧接口、未实现方案或阶段性结论。请以 [Sage v2 文档](../../../zh/README.md) 为准。

# OpenHands 服务端架构与 Sage V2 对照研究

> 日期：2026-09-22  
> 结论基线：OpenHands Agent Canvas `a5eb10d584f4dfbc6ac0fd7043c5b73bc0fa9f8e`，其锁定的 `software-agent-sdk` / `agent-server` / `workspace` `v1.49.2`；Sage 为本文写作时工作区源码。

## 结论摘要

OpenHands 当前仓库本身主要是 Agent Canvas，服务端执行核心已经拆到 `software-agent-sdk`。真正值得 Sage V2 借鉴的不是其目录结构，而是以下运行时边界：会话级 runtime 生命周期、事件事实与流式增量分离、带 generation 的写租约、MCP 工具目录动态 reconciliation，以及 Skill 的渐进披露和确定性来源优先级。

Sage 的 `sagents.v2` Skill 设计方向是正确的：Level-1 元数据与 Level-2 bundle 分离、按需 materialize、Run 级 grant、内容预算和扩展描述符都已建立。初次审计发现 `app/server_v2` 普通聊天忽略了已经 materialize 的 `skill_loading` port，并使用进程内 activation 与 sandbox 不可见的 artifact 路径；本次优化已接通插件实例、改用 session-derived activation、冻结 Run 对应的 Skill 版本，并把显式加载的 bundle materialize 到 `/workspace` 下的内容寻址缓存。MCP 的每 Run 插件生命周期仍是后续独立优化项。

优先级建议：

| 优先级 | 建议 | 直接收益 |
|---|---|---|
| P0（Skill 部分已完成） | 普通聊天接通 Application materialize 的 `skill.loading` port；MCP 的 composition 收敛另行处理 | manifest 选择、scope、stop/close 与自定义 Skill plugin 配置生效 |
| P0（已完成） | 修正 Skill workspace materialization：资源必须位于 Run 可见的 `/workspace`，不能把 data-root artifact 的宿主绝对路径当作 workspace path | `scripts/`、`references/`、`assets/` 在 sandbox 中真实可访问，同时不扩大文件权限 |
| P1 | 将 MCP 目录缓存提升到配置指纹对应的 tenant/agent scope，Run 仅绑定快照；保留短连接调用，之后再用明确 owner 的连接池替换 | 去掉每 Run `initialize + list_tools`，又不提前引入跨 Run 连接取消/清理竞态 |
| P1（已完成） | Skill activation 统一使用 `SessionDerivedSkillActivationRepository`，以权威 Tool 历史重建，禁止 server_v2 私有的 `InMemorySkillActivationRepository` 成为恢复状态 | suspend/resume、进程重启和上下文恢复语义一致，且不新增业务存储 |
| P2 | 为 MCP 增加 `tools/list_changed` 的完整 snapshot reconciliation，并让目录版本进入 composition identity/可观测字段 | 可处理运行中工具新增、更新和删除，避免只在下个 Run 才看到变化 |

截至本文同日的实现状态：Skill 相关 P0/P1 已完成；普通聊天使用 `ports.skill_loading`，activation 使用 `SessionDerivedSkillActivationRepository`，`RunConfig.metadata` 保存无密钥的 Skill version/content-hash 快照，显式 `load_skill` 才写入租户 workspace 的内容寻址缓存。Server V2 测试 `112 passed`，相关 SAgents V2 Skill/Builder 测试 `57 passed`。MCP 项尚未包含在本次修改中。

## 1. 证据基线与仓库拆分

OpenHands 顶层仓库的开发说明明确把自身定义为 Agent Canvas，并将 agent/server 逻辑指向 `OpenHands/software-agent-sdk`；Canvas 的默认配置锁定 Agent Server `1.49.2`，启动脚本也统一解析并安装相同版本的 agent-server、SDK、tools 和 workspace。因此本文没有把 Canvas UI 误当成服务端实现，而是追踪到了它实际启动的 v1.49.2 包。

- [Canvas 仓库职责说明](https://github.com/OpenHands/OpenHands/blob/a5eb10d584f4dfbc6ac0fd7043c5b73bc0fa9f8e/AGENTS.md)
- [默认组件版本](https://github.com/OpenHands/OpenHands/blob/a5eb10d584f4dfbc6ac0fd7043c5b73bc0fa9f8e/config/defaults.json)
- [开发启动脚本的版本解析](https://github.com/OpenHands/OpenHands/blob/a5eb10d584f4dfbc6ac0fd7043c5b73bc0fa9f8e/scripts/dev-safe.mjs)

实际逻辑关系可以概括为：

```text
Agent Canvas / API client
        |
        v
Agent Server（conversation 控制面、WS、租约、持久化）
        |
        v
software-agent-sdk LocalConversation（agent loop、Skill/plugin/MCP 生命周期）
        |
        v
Workspace/runtime（local、Docker、cloud）
```

## 2. 服务端总体设计中值得参照的机制

### 2.1 控制面与 runtime 隔离

OpenHands 的 registry 在本地 runtime 与 Docker runtime 间选择；Docker 模式按 conversation 创建隔离 Agent Server，并配置 capability drop、`no-new-privileges`、UID/GID、loopback 端口、内存/CPU/PID 上限。其 deferred initialization 允许容器先进入 warm pool，再由 `/api/init` 注入会话配置。这个模型适合参考为 Sage `SandboxProvider` 的远程实现，但“一会话一容器”本身不等于具备跨节点调度、全局配额或 durable queue。

### 2.2 conversation/session/event persistence

OpenHands 以 `base_state.json` 保存 Agent/config/current state，以追加、不可变的 EventLog 保存事实历史；事件有 parent/lineage，View 由事件增量派生。流式 token delta 只用于 fan-out，不持久化，最终文本事件才是 durable truth。该边界适合用于收敛 Sage AG-UI 投影与 SessionStore 的职责：传输增量不是第二份业务记录。

会话 owner lease 保存 owner、单调递增 generation 和 expiry，写前再次验证 owner/generation；这比只有互斥锁更能防止过期 owner 继续写。其本地文件锁同时明确不适合依赖 NFS 语义，因此不能把这套文件实现直接移植为 Sage 多节点事实源。

### 2.3 agent loop 与终态顺序

OpenHands 在异步 LLM 等待期间释放状态锁，同步 fallback 放入 executor；并发工具调用可以同时执行，但结果按 action 顺序写回。取消时会为未匹配 Action 补错误 Observation，并在 terminal state 前 flush pending events。Sage 应保留同样的顺序不变量：终态不能先于可恢复的 tool/result/event 落盘。

### 2.4 security 与 observability

OpenHands 将 SecurityAnalyzer 与 ConfirmationPolicy 分离，风险标签只作为确认策略输入；模型自报 risk 不能成为权限边界。MCP HTTP header 在跨 origin redirect 时全部移除，而不仅是 `Authorization`，见 [MCP origin-bound header 处理](https://github.com/OpenHands/software-agent-sdk/blob/v1.49.2/openhands/sdk/mcp/utils.py#L120-L158)。遥测侧采用字段 allowlist、有界队列、热路径非阻塞发送和失败丢弃，且不发送 prompt、消息正文、路径、secret 或 traceback；这一思路适合 Sage 的诊断 sink，但不能为了审计再建立一套业务存储。

## 3. OpenHands MCP 架构

### 3.1 发现与动态目录

OpenHands 在 conversation 初始化时创建 `MCPClient`，同步完成 connect 和首次 `list_tools`；失败会关闭 client。客户端订阅 `notifications/tools/list_changed`，收到通知后在后台任务中重新列举，并以完整 snapshot 原子替换工具表，覆盖新增、更新和删除：[首次连接与 refresh](https://github.com/OpenHands/software-agent-sdk/blob/v1.49.2/openhands/sdk/mcp/utils.py#L247-L297)、[list_changed handler](https://github.com/OpenHands/software-agent-sdk/blob/v1.49.2/openhands/sdk/mcp/utils.py#L319-L368)、[创建与异常清理](https://github.com/OpenHands/software-agent-sdk/blob/v1.49.2/openhands/sdk/mcp/utils.py#L371-L450)。

这比“缓存一次 list_tools 到下个 Run”更完整，尤其适用于 progressive MCP server。但 callback 明确运行在后台 event-loop thread，接收方必须线程安全；Sage 不应照搬线程模型，只应借鉴完整 reconciliation contract。

### 3.2 生命周期与权限

`MCPClient` 拥有后台 executor、连接和 tool definitions，提供幂等 `sync_close()`：[MCPClient 生命周期](https://github.com/OpenHands/software-agent-sdk/blob/v1.49.2/openhands/sdk/mcp/client.py#L24-L125)。LocalConversation 只在首次 `run()` / `send_message()` 时加载 plugin/MCP，随后在 conversation close 中关闭所有 tool executors；Agent Server 关闭前先 drain in-flight run，避免 MCP close 与 tool call 竞态：[懒初始化](https://github.com/OpenHands/software-agent-sdk/blob/v1.49.2/openhands/sdk/conversation/impl/local_conversation.py#L949-L965)、[conversation close](https://github.com/OpenHands/software-agent-sdk/blob/v1.49.2/openhands/sdk/conversation/impl/local_conversation.py#L2764-L2814)、[server drain 后关闭](https://github.com/OpenHands/software-agent-sdk/blob/v1.49.2/openhands/agent_server/event_service.py#L1790-L1841)。

Plugin/Skill 的 MCP 配置支持 `${SKILL_ROOT}` 与按需 secret lookup；Agent Plugin 的 literal config 禁止再从环境扩展 secret，避免不可信 package 把宿主 secret 注入自己的 subprocess：[变量解析次序](https://github.com/OpenHands/software-agent-sdk/blob/v1.49.2/openhands/sdk/skills/utils.py#L44-L127)、[literal server 限制](https://github.com/OpenHands/software-agent-sdk/blob/v1.49.2/openhands/sdk/skills/utils.py#L225-L248)、[仅在 conversation 边界展开](https://github.com/OpenHands/software-agent-sdk/blob/v1.49.2/openhands/sdk/conversation/impl/local_conversation.py#L1200-L1213)。

### 3.3 每 Run / conversation 成本

OpenHands 把 MCP client 生命周期放在 conversation，不是每个 tool call：一次 conversation 支付 connect/list_tools，后续复用连接并接收目录变化。代价是长期连接和后台 loop 必须严格 close。

Sage `McpToolPlugin` 当前采取相反取舍：源码明确说明 discovery 或每次 tool call 都开短 session，目的是保持 asyncio/AnyIO 的 cancellation ownership 正确；它在单个插件实例中按 server fingerprint 缓存 discovery，并合并并发 discovery 请求：[设计声明与配置上限](../../../../sagents/v2/tool/plugins/mcp.py#L1-L7)、[实例缓存状态](../../../../sagents/v2/tool/plugins/mcp.py#L113-L170)、[single-flight discovery](../../../../sagents/v2/tool/plugins/mcp.py#L172-L241)、[每次调用短 session](../../../../sagents/v2/tool/plugins/mcp.py#L325-L378)。这个取舍本身合理，问题是 server_v2 普通聊天每 Run 都创建新插件，实例缓存无法跨 Run 复用。

## 4. OpenHands Skills 架构

### 4.1 发现、优先级与缓存

OpenHands 支持 sandbox、marketplace/public、user、organization、project 多来源，按 `sandbox < marketplace < public < user < org < project` 后者覆盖前者：[服务端 merge 顺序](https://github.com/OpenHands/software-agent-sdk/blob/v1.49.2/openhands/agent_server/skills_service.py#L347-L432)。用户目录与项目目录还兼容 `.agents/skills`、`.openhands/skills`、legacy microagents、根/嵌套 AGENTS.md 等：[用户发现](https://github.com/OpenHands/software-agent-sdk/blob/v1.49.2/openhands/sdk/skills/skill.py#L935-L978)、[项目发现](https://github.com/OpenHands/software-agent-sdk/blob/v1.49.2/openhands/sdk/skills/skill.py#L1049-L1139)。

公共 Skill 首次获取本地 git cache。进程内缓存按 `(repo_url, ref, marketplace_path)`，branch TTL 为 60 秒，tag/commit 在进程生命周期内不失效；只缓存非空结果，显式 sync 会 invalidate：[缓存动机与状态](https://github.com/OpenHands/software-agent-sdk/blob/v1.49.2/openhands/sdk/skills/skill.py#L1142-L1173)、[ref-aware load/cache](https://github.com/OpenHands/software-agent-sdk/blob/v1.49.2/openhands/sdk/skills/skill.py#L1226-L1376)。注释给出的现实原因是一次 git fetch 加约 40 个 Markdown parse 约一秒，且 AgentContext validation 会重复触发。

值得借鉴的是“不可变内容永久缓存、可变 ref 短 TTL、失败不污染缓存、显式失效”；不值得照搬的是在每个 conversation 扫描用户/项目文件系统。Sage 已有 DB/catalog 绑定和不可变 `version_id`，应直接以 `(skill_id, version_id, package_sha256)` 做 cache identity，而不是重新引入目录全扫描。

### 4.2 渐进披露与 workspace 注入

AgentSkills 格式默认只把 name/description/location 放入 `<available_skills>`，显式调用 `invoke_skill` 后才渲染全文；tool 会记录 invoked skill，并给出 `scripts/`、`references/`、`assets/` 相对路径位置：[Skill 语义](https://github.com/OpenHands/software-agent-sdk/blob/v1.49.2/openhands/sdk/skills/skill.py#L178-L231)、[`invoke_skill` 执行](https://github.com/OpenHands/software-agent-sdk/blob/v1.49.2/openhands/sdk/tool/builtins/invoke_skill.py#L51-L123)、[资源位置 footer](https://github.com/OpenHands/software-agent-sdk/blob/v1.49.2/openhands/sdk/tool/builtins/invoke_skill.py#L125-L160)。同名 Skill 来源优先级是确定性的，path-triggered rule 强制禁止模型直接调用：[trigger 与 invocation 约束](https://github.com/OpenHands/software-agent-sdk/blob/v1.49.2/openhands/sdk/skills/skill.py#L545-L632)、[path rule 强制限制](https://github.com/OpenHands/software-agent-sdk/blob/v1.49.2/openhands/sdk/skills/skill.py#L723-L730)。

OpenHands 会把完整 Skill 对象放在 AgentContext；服务端因此默认从 conversation HTTP response 去掉 `agent_context.skills`，因为 stock agent 约 40 个 Skill 可膨胀到约 260 KB：[响应裁剪原因](https://github.com/OpenHands/software-agent-sdk/blob/v1.49.2/openhands/agent_server/models.py#L378-L421)。Sage 的 descriptor/bundle 二级结构比这一点更好，不应退回“完整内容随 Agent 配置 round-trip”。

### 4.3 ACP/外部 runtime 的所有权边界

OpenHands 对 host-local ACP 默认采用 native skill sourcing：ACP CLI 自己读 home 配置，OpenHands 不再注入第二套 managed skills；容器内缺少该 home 配置时才可切换为 `openhands_managed`。这是避免两个宿主重复拥有 lifecycle 的直接案例：[ACP skill sourcing](https://github.com/OpenHands/software-agent-sdk/blob/v1.49.2/openhands/agent_server/conversation_service.py#L313-L351)。Sage 也应采用同一原则：Skill discovery、activation、workspace materialization 只能有一个 owner。

## 5. Sage `sagents.v2` Skill/MCP 设计判断

### 5.1 `sagents.v2` Skill 插件化本身正确

当前核心设计形成了清晰的四个 port：`SkillCatalog`、`SkillSource`、`SkillWorkspace`、`SkillActivationRepository`；`SkillBundle` 校验相对安全路径：[Skill contracts](../../../../sagents/v2/skill/contracts.py#L23-L77)。`SkillLoader` 只在显式 load 时 fetch Level-2 bundle，按 run/name 串行化 activation，按 content hash 幂等恢复，并执行 active-context token budget：[lazy loader](../../../../sagents/v2/skill/provider.py#L87-L181)、[恢复与预算](../../../../sagents/v2/skill/provider.py#L183-L237)。Level-1 context 只列元数据且有 128 项/12 KB 上限：[AvailableSkills context](../../../../sagents/v2/skill/context.py#L16-L65)。

`SkillToolPlugin` 只把 domain tool 投影为 `tool.catalog` / `tool.executor`，声明 AGENT/RUN scope；schema 和行为仍由 Skill domain 的 decorated method 拥有：[SkillToolPlugin](../../../../sagents/v2/tool/plugins/skill.py#L15-L45)、[`load_skill` 权限与幂等语义](../../../../sagents/v2/skill/tool.py#L19-L112)。Builder 已注册此 extension，并能通过 `with_skill_provider()` 注入宿主 port：[官方注册](../../../../sagents/v2/runtime/extensions/official.py#L1377-L1387)、[Builder seam](../../../../sagents/v2/builder.py#L385-L388)。因此不需要重写 Skill 核心抽象。

### 5.2 普通 `app/server_v2` 接入的审计问题与修正

普通服务启动后调用 `install_skill_driver()`，直接覆盖 Application entrypoint 的 `driver_factory`：[服务启动](../../../../app/server_v2/services/runtime.py#L112-L126)、[driver 覆盖](../../../../app/server_v2/services/skill_runtime.py#L266-L269)。随后每 Run 的 `compose_catalog_loop()`：

1. 再次读取用户 catalog、Agent Skill bindings；
2. 再次 `materialize_agent()`；
3. 手工创建 `CatalogSkillProvider`、`SkillLoader`、`SkillToolPlugin`、`McpToolPlugin`；
4. 手工构建 `CompositeToolCatalog/Executor` 与 Agent loop。

初次审计证据见 [per-Run composition](../../../../app/server_v2/services/skill_runtime.py)。当时 `materialize_agent()` 已返回按 manifest/scope materialize 的 `ports.skill_loading`，但 server_v2 没有把它传给 `create_skill_loader()`，于是 factory 又根据 manifest 创建默认插件。本次已经把该 port 传入 loader，并把 activation 从 `InMemorySkillActivationRepository` 切换到 `SessionDerivedSkillActivationRepository`。普通聊天仍保留动态 Agent loop 组装，但 Skill loading plugin 的配置和 scope lifecycle 已不再被旁路。

相比之下，managed package 路径已正确调用 `builder.with_skill_provider(...)`，MCP 也通过 `with_additional_tools(...)` 注入：[managed builder](../../../../app/server_v2/services/management.py#L313-L343)。应把普通聊天收敛到同一模式，而不是维护两套组装规则。

### 5.3 当前每 Run 开销

普通聊天每 Run 新建 `McpToolPlugin`：[server_v2 MCP factory](../../../../app/server_v2/services/mcp.py#L35-L39)。因此插件内部虽有 fingerprint cache 和 discovery single-flight，仍只对该 Run 有效；每个 Run 首次 context/tool catalog 获取都会重新连接所有 MCP server 并 `list_tools`。多个 server 的发现是并行的且有工具数、页数、schema/result bytes 上限，这部分已经合理：[并行发现与边界](../../../../sagents/v2/tool/plugins/mcp.py#L207-L313)。

Skill 列表不会扫描或复制文件：`CatalogSkillProvider.list_skills()` 只遍历本 Run 已解析的 records；只有 `load_skill` 才 `rglob` 并读完整 bundle：[catalog provider](../../../../app/server_v2/services/skill_runtime.py)、[目录读取](../../../../app/server_v2/domain/skills.py#L160-L184)。这优于 OpenHands 的 conversation 级目录发现。接入层现在在 Run admission 时一次读取 bindings，并把精确版本快照带入 `RunConfig.metadata`；composition 直接消费该快照，避免排队期间绑定或版本变化造成执行漂移。activation 也已与 Builder 原生路径一致，使用 `SessionDerivedSkillActivationRepository` 从权威 Tool 历史恢复，不再建立 server_v2 私有内存状态。

### 5.4 workspace 注入已改为 sandbox 可见的按需缓存

初次审计时 `ReadThroughSkillWorkspace.materialize()` 会返回全局 catalog artifact 的宿主绝对路径，而 Official sandbox 只映射 tenant workspace。现实现保持“metadata discovery 不复制”，只在显式 `load_skill` 时把精确版本写入 `/workspace/skills/.catalog/<name>/<content-key>`；相同内容跨 Run 复用，用户主动编辑的 `/workspace/skills/<name>` 仍优先，catalog artifact 不会暴露或被覆盖。materialize 前后都会校验 package hash，因此 `scripts/`、`references/`、`assets/` 与正文版本一致并对 sandbox 可见。

## 6. 建议的目标边界

```text
Server catalog / immutable Skill artifacts
        |
        | version_id + package_sha256（Agent/tenant scope cache identity）
        v
SAgentBuilder / ExtensionHost
        |
        +-- skill.loading plugin（唯一 loader lifecycle owner）
        +-- SkillToolPlugin（tool projection）
        +-- MCP catalog snapshot provider（tenant/agent cache）
        |
        v
Run scope
        +-- durable/derived Skill activation
        +-- /workspace/skills/<name> materialization or read-only mount
        +-- MCP snapshot binding；tool call 使用短 session
```

具体落地约束：

- 目录 cache 只保存无 secret 的 ToolDefinition snapshot；credential rotation 通过现有 secret hash fingerprint 失效，secret 本身不能进入 key 或诊断事件。
- `tools/list_changed` 更新必须以完整 snapshot 替换，且 composition/run 记录目录 generation；不要只 append 新工具。
- Skill catalog metadata 可跨 Run 缓存，activation 必须按 Run 授权过滤；resume 时仍要重新校验当前 grant。
- materialization 必须原子、content-hash 幂等、拒绝覆盖不同内容；可复用现有 `SkillWorkspace` contract，不增加业务表。
- ExtensionHost/Builder 应是 plugin start/stop/scope 的唯一 owner；server_v2 只提供 catalog、workspace、credential、sandbox 等 host ports。

## 7. 明确不建议照搬

- 不照搬 OpenHands 将完整 Skill 对象放入 AgentContext 和持久化/HTTP shape；Sage 的 metadata/bundle 分层更省上下文和序列化成本。
- 不照搬每 conversation 扫描用户 home、项目树和 legacy 目录；Sage 已有显式发布、版本、绑定和可见性模型。
- 不立即照搬长生命周期 MCP 连接。先共享 discovery snapshot；只有在连接池能明确处理 tenant、secret rotation、cancel、server notification、drain 和 close owner 后再复用连接。
- 不允许 Skill 自带 `allowed-tools`、MCP 声明或模型自报 risk 扩大 server-trusted policy ceiling；它们只能进一步收窄权限或提出需要确认的请求。
- 不把宿主全局 artifact 目录加入 sandbox allowed roots，也不为审计单独扩展业务存储。

## 8. 证据边界

本文是静态源码研究，没有启动 OpenHands MCP server、执行真实 Skill、做网络故障注入或容量压测。OpenHands 结论限定于 Canvas commit `a5eb10d58` 实际锁定的 v1.49.2；其 public extension 内容和 SaaS 控制面可能独立演进。Sage 判断基于当前工作区源码：能够证明 composition/lifecycle 调用链和静态 I/O 行为，不能把“存在缓存/并发/上限代码”外推为生产容量、延迟或多节点正确性证明。
