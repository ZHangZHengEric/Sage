---
layout: default
title: Server Agent 平台
parent: 架构
nav_order: 5
lang: zh
ref: v2-detail-SERVER_V2_AGENT_PLATFORM
---

{% include lang_switcher.html %}

# Server Agent 平台

如果只是给现有 Agent 发消息，使用普通聊天即可。需要保存一组完整配置、比较版本、测试后再切换版本时，使用 `/studio` 中的 Agent 包管理。两者共用 v2 运行时，但入口和任务记录各有自己的工作流程。

## 职责与入口

SAgents 提供定义、装配、Flow、执行、持久化和交互；Server 提供身份、权限、用户目录、宿主配置和 HTTP/Web 入口。HTTP 与模型管理工具使用同一个 AgentManagementService。

普通聊天通过 `/api/agent` 使用 AG-UI。完整包工作流位于 `/api/agent-packages` 与 `/studio`，可从 catalog Agent 导入草稿，保留提示词、模型、工具和 Skill 选择；导入不修改原 Agent，后续编辑也不自动传播到已保存包。

Studio 支持 JSON 定义编辑、Schema/资源检查、保存、复制、分页版本库、活动版本切换、执行、历史、事件、取消、反馈、审批及同 Session 续接；不是拖拽式 Flow 画布。包运行是独立 API 工作流，不等于 AG-UI 聊天流。

## 版本与权限

- 原生 AgentPackageBundle 保存完整 manifest 和文本资源；不可变 ID/version 与 ref 绑定完整内容。相同内容可幂等保存，变更须新版本。
- 活动指针使用 expected_ref 比较更新，可重新激活旧 ref；已运行任务不换版。续接限制为同用户、版本和 Agent 的 Session。
- 用户身份来自 JWT，库存、任务和事件按 owner key 隔离，body 不能指定其他用户。
- 模型用 `provider: server`，model 为当前用户的 catalog 模型 ID 或 default。凭据和地址由宿主解析；包不能自行覆盖 credential、base_url、环境变量、持久化、调度和日志后端。
- 包内 max_steps 上限为 10000；没有记忆后端时拒绝声称启用读写记忆。
- `agent_package_*` 模型工具仍受宿主授权，不具有人类审批特权。HTTP control 的 approve 独立鉴权，检查 owner、interaction ID、允许决策、revision 和授权。

## 工具、Skill 与扩展

`ServerHost(package_extensions=..., package_authorizer=...)` 注册扩展并设置授权。包可选择已授权的 flow.node、tool.provider、memory.provider，其余基础设施由宿主固定。源码扩展默认关闭；启用时执行可信宿主 Python 代码，不能视为非可信代码隔离，也不自动 pip 安装。

页面/API Agent 也持久化为库存内的标准 `AgentPackageBundle`，`agents.package_ref` 是必需的配置引用；目录批量解析包，Skill 索引和包更新共用事务。启动只创建缺失表，现有记录缺失包引用时拒绝读取。旧 `/api/agents/{id}/runs` 受理时冻结包，执行时使用冻结定义，网络再与当前 Agent/Server 上限取交集。

官方工具由 ExecutionBindingProvider 按真实 Run ID 绑定用户工作区与沙箱，子 Run 独立绑定。MCP、Skill 与模型来自当前用户目录，模型从宿主池借用租约，凭据不写入包库存。Skill 列表描述不截断，加载后的活跃内容另受 token 预算限制。

包内 `agents.<id>.sandbox.network` 支持 `none`（默认）和 `unrestricted`。使用既有严格 manifest Schema 校验并随不可变版本保存；运行时 `PackageBindings.acquire` 按实际 Agent ID 解析，主 Run、子 Run、恢复 Run 都在 provision 前与宿主 `ServerSettings.sandbox_network_mode` 上限取交集。宿主上限默认 `unrestricted`，可通过构造配置收紧到 `none`，无新增环境变量。`unrestricted` 使用直接网络并允许私网；未配置的包和普通 Agent 保持禁网。模式参与沙箱哈希；不改变宿主侧模型/MCP/A2A 的联网行为。示例见 [Server README](../../../app/v2/server/README.md#包沙箱网络)。

Server MCP 仅支持 sse、streamable_http，不接受租户 stdio 命令；非法配置保存时返回 422，历史 stdio 记录读取时跳过。单个 MCP 不可用不阻断整个 Run，按用户/配置指纹复用发现缓存；`POST /api/mcp/{name}/refresh` 可使缓存失效。

远端 A2A peer 使用 `/api/a2a-agents` 管理。入站 `/a2a/v1` 及 Agent Card 仅在安装 a2a extra 后挂载，使用绑定 Agent 的 API Key 和 a2a:read / a2a:invoke scope。API Key 由 `/api/keys` 管理；Card 地址可通过 SAGE_SERVER_PUBLIC_URL 指定。

## 并发与生命周期

普通聊天和 managed Applications 队列独立，共享 SchedulerQuotaGroup；领取和配额检查原子执行，总额度不随包数增加。它不承诺跨租户严格 FIFO；内联子 Agent 仍受核心委派与共享模型额度约束。

| 配置 | 默认值 | 作用 |
| --- | ---: | --- |
| SAGE_SERVER_MAX_CONCURRENT_RUNS | 8 | 共享运行及模型调用额度 |
| SAGE_SERVER_MAX_CONCURRENT_RUNS_PER_USER | 2 | 用户运行额度 |
| SAGE_SERVER_MAX_PENDING_RUNS | 1024 | 共享等待队列及模型等待上限 |
| SAGE_SERVER_MAX_MODEL_CLIENTS | 64 | 模型客户端池 |
| SAGE_SERVER_MAX_MANAGED_APPLICATIONS | 32 | managed 实例及构建占位 |
| SAGE_SERVER_MAX_MANAGED_BUILDS | 4 | 并行装配 |

JobRuntime 由宿主拥有并共享。关闭先停止执行，再关闭 managed Applications 和主 Application；Application 释放自己持有的 dispatcher、调度器、模型池等资源。失败保留可重试清理的对象。容量不足只回收可持久恢复、空闲且无非终态任务的实例，没有安全候选则返回过载。

Agent、模型、MCP、A2A peer 和 Skill 绑定分列保存，各类使用各自进程内锁，不互相覆盖。这不是跨进程 CAS。

## 存储与恢复

生产库存位于 MySQL managed_agent_records，保存版本、活动指针、操作、回复及终态归档。身份字段可索引，操作和 Agent 名使用二进制比较。

Session 使用核心 MySQL SessionStore。managed Application 以宿主持久路径派生独立表前缀；正式运行创建表族，验证使用临时文件存储。版本增加带来的表族数量是部署成本。

启动分页恢复未归档操作，重新检查当前授权，不重新提交 StartRun。暂停保留交互；没有 durable handle 的 admission_pending 需要用原 operation 与输入重试。恢复失败保留状态并记录错误，不改写为成功。

归档结果读取无需模型初始化。文件存储支持未归档终态和事件的只读冷读取；MySQL 未归档结果仍需装配对应应用。事件采用 run_sequence 游标，每页最多 200 条，Studio 显示最近 100 条。

## HTTP 与部署

完整路由、鉴权与条件挂载见[HTTP API](../api/HTTP_API_REFERENCE.md)。资源授权失败为 403，不可见对象为 404，版本冲突为 409，容量/模型限流为 429，非法定义为 422。

构建 app/v2/server/web 后，后端托管 web/dist，可访问 `/studio`；未知 API 和越界文件路径不会回退成 HTML。也可独立部署前端并代理后端请求，见[Server 启动](../applications/WEB.md)。

仅支持单 worker。MySQL 持久化不提供横向扩容，AG-UI 回放读取 Session 事件，不依赖 Redis。测试中的 SQLite 事务、模拟模型和合成并发不能代替真实 MySQL、原生平台或长时间模型负载验收。

实现入口：[bootstrap.py](https://github.com/ZHangZHengEric/Sage/blob/main/app/v2/server/bootstrap.py)。

包权限规则：[policy.py](https://github.com/ZHangZHengEric/Sage/blob/main/app/v2/server/packages/policy.py)。

## Session 诊断包

管理员通过历史页“下载诊断包”或 `GET /api/threads/{thread_id}/download` 获取 `<session>-diagnostics.zip`。服务端通过观测层的 `export_evidence(session_id, run_ids)` 查询证据，只从业务存储读取已授权的 Run 列表并核对 Agent/tenant 归属，不再导出业务状态和事件。`sage.session-diagnostic-bundle/v2` 包含 `manifest.json`、`models.json`、`requests/`、`tools.json`、`failures.json`、`logs.json`，外部查询还包含 `traces.json`；移除 `state.json`、`session.json`、`runs/`、`events/`。工具结果与失败从观测 span/日志生成，历史缺口明确记录，不从业务事件重建。业务会话、检查点、暂停、交互、恢复数据及记忆索引仍由原持久化机制维护。

仅在 trace 后端为 noop 时，Server 使用本地 `runtime/diagnostics/evidence.sqlite3` 保存诊断。选择外部观测后端后不创建、不写该库；Phoenix 和 Jaeger 实时查询外部证据，外部故障返回 503。性能记录和原始日志合入当前执行段的真实 `agent.run` span，恢复段按 Run 合并；保留 Agent 自身起止时间，Server 入口准备及收尾的端到端计时记录在 `sage.performance.*` 属性和事件中，收尾完成后导出，不再创建独立的性能节点；原始诊断写入既有 span 的 `sage.diagnostic.*` events，不为每个日志/计时创建独立根 span。Langfuse 与通用 OTLP 尚无诊断查询能力，下载返回 409，不回退本地采集。stdout 保留，文件日志默认关闭，非空 `SAGE_SERVER_LOG_DIRECTORY` 可显式启用。模型请求优先记录 provider wire payload，响应为 SDK 归一化响应，流证据为 SDK 暴露的事件而非 HTTP 字节。Phoenix raw 模式不脱敏、不按内容长度截断，并保存完整工具结果、operation ID、metadata 和结构化错误；采集仍受异步队列、采样、导出失败及保留期影响。清单列出来源、缺失 Run、截断和未送达信息。ZIP 保留下载大小与条目上限，超限返回 413。

ZIP 下载继续脱敏凭证字段、嵌套 JSON、常见 Bearer / API token、URL 用户信息和标记过的内联凭证，此策略独立于 Phoenix 的 raw 保存模式。下载保持管理员权限，先校验持久化 Session owner、Agent 和 tenant 绑定，只导出该 Session 及权威 Run 白名单内的观测证据。运行中和未送达的记录可能缺失，此包不能作为恢复备份。
