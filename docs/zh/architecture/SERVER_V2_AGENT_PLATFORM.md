---
layout: default
title: Server Agent 平台
parent: 架构
nav_order: 5
lang: zh
ref: v2-detail-SERVER_V2_AGENT_PLATFORM
---

{% include lang_switcher.html %}

# Server V2：多用户 Agent 服务平台

日期：2026-09-14。范围：Server V2 与所复用的 SAgents V2 核心；不修改旧 Desktop，不加入监督学习或自动晋升闭环。

## 职责与实际入口

SAgents V2 提供包定义、装配、执行、Flow、多 Agent、持久化与交互控制。Server V2 提供身份、权限、用户资源目录、宿主配置、HTTP 和 Web 入口。HTTP 和模型管理工具调用同一个 AgentManagementService，不另外实现 Agent 执行引擎。

既有 `/api/agent` AG-UI 聊天与 catalog Agent API 保持兼容。完整包工作流位于 `/api/agent-packages` 和 `/studio`。普通 Agent 可导入为包草稿，保留提示词、模型、工具与 Skill 选择；之后以包版本独立管理。导入不会修改原 Agent，也不把它之后的编辑自动传播到已保存版本。

Studio 提供完整 JSON 定义编辑、Schema/宿主能力检查、资源验证、保存、复制、分页版本库、活动版本切换、执行、任务历史、增量事件、取消、反馈、人工审批和同 Session 续接。它是可操作的完整定义编辑器，尚不是拖拽式 Flow 画布。任务结果直接展示，完整运行记录可展开查看。

## 定义、版本和权限

- 包使用原生 AgentPackageBundle；Agent 模式、成员、Flow、预算、指令文件和文本资源沿用核心契约。
- 包 ID/版本不可变；内容相同的保存可重试，修改需新版本。复制创建新的包身份。活动指针采用 expected_ref 比较更新；旧版本可再次激活。列表各行携带当前 active_ref，跨页切换仍按同一快照检查冲突。
- 运行绑定明确的 ref、agent_id 和 operation。活动指针不改变已经开始的任务；续接只能使用同一用户、版本与 Agent 的 Session。
- 路由中的用户身份来自 JWT。包库存、任务和事件按 tenant/principal 的 owner key 隔离，调用者不能通过 body 指定其他用户。
- 模型声明使用 `provider: server`，`model` 填当前用户的 catalog 模型 ID 或 `default`。凭据和地址从宿主模型目录解析；包不得携带 credential、base_url、环境覆盖或自行替换持久化、调度和日志后端。
- 包内 max_steps 上限 10000。未提供记忆后端时，拒绝声称启用记忆读写；不会把 no-op 后端当成记忆能力已实现。

模型可以选择 `agent_package_*` 标准工具，查询资源、创建与复制包、保存版本、运行其他 Agent、查询结果与事件、处理普通交互。管理操作由宿主包授权器校验，不重复要求人工批准每次保存；其他工具仍沿用正常审批策略。模型工具不能设置人工审批特权。HTTP `action=approve` 是单独的已鉴权人类入口，仍检查所有权、interaction ID、允许决策、状态 revision 和宿主授权。

## 标准插件与资源绑定

默认不开启源码执行。宿主通过 `ServerV2Service(package_extensions=..., package_authorizer=...)` 注册扩展并设置准入函数。启用源码时，`extensions/<plugin_id>.py` 导出标准 ExtensionRegistration，内容计入包哈希；ID/API/版本校验与关闭清理由核心负责。

包可选择已声明且授权的 `flow.node`、`tool.catalog` 和 `memory.provider`。其他运行基础设施由宿主固定。自定义工具的名称、配置和行为必须由 package_authorizer 核验。已注册 Flow 节点和源码 Tool 插件均有实际运行回归。

源码扩展运行在宿主 Python 进程中，不是非可信代码沙箱；授权器必须审核具体来源、内容和资源需求。当前不提供自动 pip 安装、隔离构建 worker 或第三方包供应链管理。未授权源码在加载前被拒绝。

官方工具通过 ExecutionBindingProvider 按真实 Run ID 取得本用户的工作区沙箱，子 Run 独立绑定资源；MCP 与 Skill 复用当前用户的目录。模型连接从用户客户端池借用，释放模型流后归还租约；配置凭据不进入包库存。

server_v2 面向公网多租户，MCP 只接受 `sse` 与 `streamable_http` 两种网络传输，不支持 `stdio`：stdio 会在服务进程内执行租户提供的命令，等于把任意代码执行开放给任何注册用户。传输合法性在保存时校验（非法配置返回 422），而不是等到组装 Run 才失败；持久化中的历史 stdio 记录在读取时跳过，不会让整份 catalog 无法加载。单个不可用的 MCP 只损失该服务器的工具，不会中断整个 Run。MCP 插件按 (用户, 服务器指纹) 复用以命中发现缓存，`POST /api/mcp/{name}/refresh` 会让该用户的缓存失效，使发现失败或过期的工具列表有明确的恢复路径。

## 并发与生命周期

旧聊天 Application 与 managed Applications 使用独立队列、共同的 SchedulerQuotaGroup。共享条件锁保证领取与额度检查原子执行；总并发、每用户并发与待处理数量不随包数量成倍增长。各 dispatcher 只领取本应用的任务。此机制限制调度租约，不承诺跨租户严格 FIFO；内联子 Agent 仍使用核心委派限制和共享模型额度。

| 配置 | 默认值 | 作用 |
| --- | --- | --- |
| SAGE_SERVER_MAX_CONCURRENT_RUNS | 8 | 共享调度运行额度；同时用于共享模型调用额度 |
| SAGE_SERVER_MAX_CONCURRENT_RUNS_PER_USER | 2 | 共享用户运行额度 |
| SAGE_SERVER_MAX_PENDING_RUNS | 1024 | 共享待处理队列上限；同时用于模型等待上限 |
| SAGE_SERVER_MAX_MODEL_CLIENTS | 64 | 模型客户端池容量 |
| SAGE_SERVER_MAX_MANAGED_APPLICATIONS | 32 | managed Application 缓存和构建占位总上限 |
| SAGE_SERVER_MAX_MANAGED_BUILDS | 4 | 并行装配上限 |

JobRuntime 由主宿主拥有，各应用共享任务并发、准入与输出限制。关闭顺序为 managed Applications、主 Application、主调度器、模型池。关闭失败保留对象，供再次 close 清理；不会先丢掉引用。容量不足可回收可持久恢复且无非终态任务的空闲实例；没有安全候选时返回过载，而不是无限建立实例。

Agent、模型、MCP、A2A peer、Skill 绑定分列保存。每一类写操作只替换自己的列，并使用该类自己的进程内锁。不同类的保存不会互相覆盖。这仍是单进程保护，不是跨进程 CAS。

## 持久化与恢复

生产包库存使用宿主 MySQL 的 `managed_agent_records`，保存版本、活动指针、幂等操作、交互回复与终态归档。owner/ref/kind/session key 等可索引；操作名称和 Agent 名称使用二进制比较，防止 MySQL 默认不区分大小写的比较混淆身份。

运行 Session 使用核心 MySQL SessionStore。不同 managed Application 使用由宿主持久路径导出的独立表前缀，避免多个 writer 争用同一存储实例。验证使用临时文件存储，不创建永久 MySQL 表族；正式运行才创建持久命名空间。版本增多会增加表族数量，这是当前命名空间方案的部署成本，需按实际版本规模规划。

启动后按用户和分页操作记录恢复未归档任务，重新读取当前授权，不重新提交 StartRun。暂停任务保留原交互，用户可继续回答。没有 durable handle 的 admission_pending 仍要求调用者使用原 operation 与原输入重试。恢复失败会记录错误并保留原状态，不自动改写成成功。

已归档结果无需初始化模型。内置文件存储还支持未归档终态和事件的只读冷读取；MySQL 未归档记录/事件仍需装配对应应用。事件 API 使用 run_sequence 游标，每页最多 200 条；Studio 展示最近 100 条，避免浏览器无限积累。

## HTTP 契约

前缀均为 `/api/agent-packages`，认证与错误 envelope 沿用 Server。

| 方法 / 路径 | 用途 |
| --- | --- |
| GET /schema、/resources、/template | 完整 Schema、可用资源、空白或 catalog 导入模板 |
| GET /、POST / | 分页版本库、保存完整包 |
| POST /validate | 结构/装配验证，可选资源就绪检查 |
| GET /{ref} | 读取完整定义和文件 |
| POST /{ref}/fork | 复制为新包 ID/版本 |
| POST /{ref}/activate | expected_ref 比较更新活动版本 |
| GET /runs、POST /runs | 分页任务记录、幂等启动/续接 |
| GET /runs/{operation} | 状态、结果、Flow 输出和待处理交互 |
| GET /runs/{operation}/events | 游标事件页 |
| POST /runs/{operation}/control | cancel、reply、人工 approve |
| GET /capacity | 管理员查看缓存、模型与调度额度 |

资源授权失败为 403，跨用户不可见对象为 404，版本冲突为 409，容量/模型限流为 429，非法定义为 422。Studio 的完整定义编辑与任务运行是独立 API 工作流；既有聊天端仍使用 AG-UI，不声称完整包任务已经映射为 AG-UI 流。

## 验收与边界

正式回归覆盖包保存与隔离、版本 CAS、真实模型工具创建 Agent、Flow 成员执行、提问与人工审批、源码 Flow/Tool 插件、资源越权拒绝、事件分页、数据库库存、重启恢复、关闭失败重试、共享调度准入与取消等待。

额外修复：独立资源绑定的子 Agent 继承正确的运行配置指纹与委派控制器，避免合法 Flow 成员被误判为不兼容；SPA 静态文件拒绝越界路径和未知 API 的 HTML 回退。

本轮验收：SAgents V2 完整回归 2139 passed、19 skipped、1 deselected；Server V2 112 项、Desktop V2 Python 172 项通过。最终联合运行这两个宿主套件、Agent Management 62 项和共享调度 2 项，共 348 passed。Ruff（Python 3.12）及 git diff --check 通过。

Server Web 使用仓库锁定依赖完成 Vite 构建；独立无头 Chrome 验证登录、模板加载、保存、执行、回答正文展示以及相同 Session 的第二轮任务，无 page error。Desktop 前端未修改，因此未重复 Flutter 回归。

核心完整回归排除 `test_local_sandbox_resource_limits.py`、`test_local_workspace_sandbox_matrix.py`，并 deselect `test_official_tool_provider_matrix.py::test_shell_and_todo_tools_use_v2_runtime_state`，不计为通过。

数据库仓储使用真实 SQLAlchemy 事务在 SQLite 测试库验证；该阶段验证没有连接生产 MySQL，没有做多小时真实模型负载、Windows 或原生沙箱实机验收。既有核心原生沙箱排除项不计为通过。仍只支持单 worker；MySQL 持久化不使它自动具备横向扩容能力；AG-UI 回放已改为直接读取 Session 事件，Redis 不再是启动依赖。没有承诺全进程 RSS 限制、非可信插件隔离或监督学习闭环。
