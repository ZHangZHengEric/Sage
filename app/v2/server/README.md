# Sage Server

[code reading guide](../../../docs/en/architecture/code-reading-guide.md) · [中文阅读指南](../../../docs/zh/architecture/code-reading-guide.md)


多用户 AG-UI 服务。后端代码在 `app/v2/server/`，前端在 `web/`。

```text
routers/        对外 HTTP 路由、鉴权依赖、请求响应模型
config/         服务配置与运行 manifest
identity/       用户和 API Key、认证与仓储
catalog/        Agent、模型、MCP 和 A2A 目录
skills/         Skill 目录、文件与运行时加载
conversations/  会话、Run、AG-UI 与 A2A 协议
packages/       托管 Agent 包、版本和运行管理
runtime/        执行编排、模型池及外部工具集成
admin/          管理服务
database/       数据库连接、共享 Base 和建表注册
storage/        工作区路径
observability/  请求上下文、日志和指标
bootstrap.py    进程资源和服务装配
main.py         应用启动入口
web/            前端
```

业务代码按能力放入对应目录，记录、规则、服务和仓储就近组织；共享的数据库连接和运行时能力分别放在 `database/`、`runtime/`。对外接口统一放在 `routers/`，配置放在 `config/`。HTTP 接口注入所属业务服务，由服务访问仓储；简单列表从服务读取目录，不暴露仓储给路由。AG-UI 与 A2A 协议实现在 `conversations/agui/`、`conversations/a2a/`，共用 `conversations/admission.py` 受理 Run。Agent 独立保存在 `agents` 表，以服务端生成的 `agent_<UUID>` 为全局主键，`owner_user_id` 限定归属。`catalogs.default_agent_id` 保存默认 Agent 引用；模型、MCP、A2A peer 仍按目录分列保存。Agent 新建接口不接受 `id`，修改使用路径中的 ID，外部调用按 Agent 主键查找归属。

生产启动只强制 MySQL：`SAGE_SERVER_MYSQL_URL`。AG-UI 回放读取 Sage Session 的 canonical RuntimeEvent；模型流式 delta 是进程内预览，断线重连通过预览序号续接，进程重启后以持久事件恢复。

单进程并发可用 `SAGE_SERVER_MAX_CONCURRENT_RUNS`（默认 8）、`SAGE_SERVER_MAX_CONCURRENT_RUNS_PER_USER`（默认 2）和 `SAGE_SERVER_MAX_PENDING_RUNS`（默认 1024）配置。参数必须为正数，分别约束总执行、每用户执行及等待队列，见[单机并发说明](../../../docs/zh/architecture/sagents-v2-single-host-concurrency.md)。

Server 只支持单 worker：SessionStore 只接受一个 writer（`multi_process_writes: False`），订阅者留在进程内，Scheduler 与 JobRuntime 是内存实现。第二个进程会在获取独占 writer 锁时启动失败。MySQL 让 Session 状态跨重启存活，但不提供横向扩容。manifest 的 `required_guarantees` 在装配阶段校验 SessionStore 的事务性、持久性与 actor 授权能力。

```bash
# 后端依赖（仓库根目录，Python 3.12+ 环境）
python -m pip install -e '.[server]'

python -m app.v2.server --data-root /tmp/sage-server-v2
```

Docker 部署可使用仓库中的 `deploy/compose_v2.sh`，仅启动 v2 后端和 Web，连接外部 MySQL；配置与命令见 [部署指南](../../../deploy/README.md)。

Web 开发时可单独启动：在 `app/v2/server/web` 执行 `npm install && npm run dev`，Vite 将 API 请求代理到后端 `8090` 端口。执行 `npm run build` 后再启动后端，后端会托管 `web/dist`，可直接访问 `http://localhost:8090` 或 `/studio`。也可使用独立静态文件服务部署，并代理 API 请求到后端。

启动按当前 ORM 元数据创建缺失表，不执行历史表结构升级或 Agent 数据回填。Agent 配置统一通过 `agents.package_ref` 读取标准包。Skill 描述列使用 `LONGTEXT`，列表描述不截断，加载内容受 Skill 文件大小限制。

环境变量模板统一维护在根目录 [`.env.example`](../../../.env.example)。源码启动前执行 `cp .env.example app/v2/server/.env` 并填写配置，进程环境变量优先。生产必须设置 `SAGE_SERVER_JWT_SECRET`（至少 32 字节）。未配置时的默认管理员：`admin` / `admin12345`；模板要求替换管理员密码。OpenAPI 在 `/docs`。

成功/失败 JSON 都带 `request_id`，并回写 `X-Request-ID`。可传入该请求头以透传。

## 数据

| 数据 | 生产 | 测试 |
|---|---|---|
| 用户 / catalog / 会话索引 | MySQL `users` / `catalogs` / `threads` | Memory mock |
| Sage Session | `sage.session.mysql`（无表前缀） | filesystem（`data_root/runtime/sessions`） |
| AG-UI 回放 | Sage Session `run_events` | Sage Session `run_events` |
| 工作区 | `{data_root}/tenants/{user_id}/{agent_id}/workspace/` | 同左 |
| Skill catalog | MySQL `skills` / `skill_versions` / `agent_skill_selections`；artifact 相对路径 `{data_root}/skills/...` | Memory mock + 同左磁盘 |
| Agent / MCP / A2A peer | `agents.package_ref` 引用 `managed_agent_records` 中的标准包；`catalogs` 保存模型、MCP 和 A2A peer | 同左 |
| A2A API Key | MySQL `api_keys`（只存哈希） | Memory mock |

对话：首次 run 把 `agent_id` 钉在会话上（之后忽略下拉/`forwardedProps`）；读 catalog Agent → Official 文件/沙箱工具 + MCP + A2A peer + skill 组成 Composite，通过 Package Builder 的统一 `build(package, runtime=...)` 装配，并借用进程 Application 的共享服务；循环走统一 `create_loop(...)`。进程 Application 只 build 一次。

`/health` 返回就绪状态与 `trace_enabled`；配置 `SAGE_SERVER_JAEGER_URL` 时管理页显示 Jaeger 入口。Server V2 与 sagents/v2 运行时直接通过 `StructuredLogger` 调用统一日志接口；Uvicorn 和第三方标准日志经适配器转换成 `sage.log/v1` 记录。所有记录由同一 LogSink 写入 stdout；默认不写文件，显式配置非空的 `SAGE_SERVER_LOG_DIRECTORY` 才额外写入轮转文件。`SAGE_SERVER_LOG_LEVEL` 控制最低级别，`SAGE_SERVER_LOG_FORMAT` 控制两处输出的 `json` 或 `text` 格式。stdout 也可由容器日志驱动或 Alloy/Loki 持久化，不写审计业务表。

DEBUG 模式下，HTTP/OpenAI/MCP/A2A 客户端仅保留 WARNING 及以上日志，MySQL/Redis 客户端仅保留 INFO 及以上日志。状态提交、入口准备、Agent 准备和会话归档的成功 DEBUG 计时仅在耗时达到 100ms 时输出；失败、异常和缺少耗时的记录继续保留。该过滤同时用于 stdout、轮转文件和现有诊断日志，模型/工具/Run 生命周期及首段正文计时完整保留，不改变对话执行与会话持久化。

模型客户端池使用 `SAGE_SERVER_MAX_MODEL_CLIENTS`（默认 64）限制容量。同一用户的相同配置跨 Run 复用连接，凭据变化使用新客户端；池满且所有客户端占用时返回可重试的限流错误。详见[模型池与增量持久化](../../../docs/zh/architecture/sagents-v2-model-pool-and-persistence.md)。

## Server 插件配置

管理员可在 `/plugins` 点击“配置 Server”，选择实现并编辑 Schema 参数；普通用户只能查看插件目录。`PUT /api/plugins/server` 接收版本号 `revision` 和局部变更 `changes`，将某项设为 `null` 恢复部署默认。保存会校验插件能力、可用依赖、参数和宿主保留项；过期版本返回 409，不覆盖其他管理员的修改。

配置以原子替换写入 `{data_root}/config/plugins.json`，启动时加载快照。页面分别显示当前实现和待重启配置；保存不会改变运行中的对话，也不会使后续 Run 与进程共享服务使用不同版本。重启 Server 后才统一生效。Docker 的 `/app/data` 持久化挂载会保留这些配置。

页面可编辑上下文摘要、Token 估算、上下文压缩、完成判定、工具选择、工具结果压缩、Skill 加载、记忆检索词生成，以及长期记忆、会话记忆、摘要存储、链路追踪、工作区初始化和包注册表。模型接口、工具与 Skill 目录、日志和诊断、Session 数据库、沙箱、共享调度及其他注入服务由部署或相应专用页面管理，不能保存一份会被宿主忽略的插件选择。

普通智能体可以覆盖前八项。优先级为：智能体显式配置 → Server 已生效配置 → 插件默认值。同一实现合并参数；不同实现替换整项选择。智能体选择“跟随默认”不会写入覆盖。Server 保存后尚未重启的配置不会成为智能体默认值。Studio 独立 Package 使用 `ServerPackagePolicy` 的额外授权，不扩大普通智能体的权限。

普通智能体设置的「运行模式」支持 Simple、Fibre、Team。Fibre 和 Team 可以选择当前用户已有的智能体作为成员；Fibre 还可在运行中创建临时专家。成员不能重复、包含自身或形成循环依赖。成员保留各自的模型、工具、技能和执行权限上限。

`POST /api/agents` 和 `PUT /api/agents/{agent_id}` 接收 `agent_mode`（`simple` / `fibre` / `team`）及 `available_sub_agent_ids`（成员 ID 列表）；详情和列表返回相同字段。新建默认为 Simple、无成员；更新省略这两个字段时保留原配置，传空成员列表则清空。配置直接保存在现有 Package 的 `mode`、`subagents` 和依赖包中。新运行读取成员的最新配置，并通过既有 Run 配置快照冻结整个团队，排队及恢复不会重新读取成员业务配置；实时权限收紧仍然有效。

本地 BM25 记忆使用 `sage.memory.filesystem-bm25`，必填 `root`，页面默认放在 `{data_root}/runtime/plugins/memory.provider`。这只启用存储提供者；自动召回、写入和 `search_memory` 授权仍属于 Agent 行为，需要单独配置。

## 完整 Agent 包平台与 Studio

`/studio` 提供完整包定义编辑、普通 Agent 导入、不可变版本、复制/切换版本、运行、事件、任务历史、反馈、人工审批和同 Session 续接。对应 HTTP 入口为 `/api/agent-packages`。普通 Agent 可选择 `agent_package_*` 工具，通过同一管理服务创建并调用其他 Agent。

ServerHost 必须注入 Database；生产库存使用 MySQL `managed_agent_records`，测试使用 SQLite Database，不再使用独立的包库存文件。managed Session 使用独立 MySQL 前缀，验证用临时文件存储。普通对话与包任务共享运行/用户额度、模型额度和 JobRuntime。可通过 `SAGE_SERVER_MAX_MANAGED_APPLICATIONS`（默认 32）和 `SAGE_SERVER_MAX_MANAGED_BUILDS`（默认 4）控制实例与装配容量。

包模型使用 `provider=server`，`model` 指向本人模型 ID 或 `default`，不携带凭据和地址。源码插件默认关闭，只有宿主注册与明确授权后才能加载，且属于可信宿主代码。能力、API、部署成本和验证边界见 [Server V2 Agent 平台](../../../docs/zh/architecture/SERVER_V2_AGENT_PLATFORM.md)。

### 统一 Agent package 配置

页面及 `POST/PUT /api/agents` 保存标准 `AgentPackageBundle` 到现有 `managed_agent_records` 不可变版本库存，`agents.package_ref` 引用当前内容哈希。读取、组装 manifest、Run 受理均以该引用的 package 为准；引用缺失或哈希不符会拒绝操作。`GET /api/agents/{id}` 返回 `package`、`package_ref` 和从 package 投影的 `sandbox`。

编辑产生新的内容版本，旧版本仍可读；不改变 Agent ID、已有 Session、API Key、默认 Agent 或 workspace 路径。Skill 绑定索引和 package 的 Skill 声明在同一数据库事务内更新。Run 受理冻结 package 和 Skill 版本；排队或审批后不会切换到之后编辑的包。网络在创建沙箱时取冻结配置、当前 Agent 上限和 Server 上限的交集。

现有 `POST /api/agents/{id}/runs`、AG-UI 和 A2A 入口均沿用上述来源，无需业务方换接口。每次 Run 只解析配置、复用宿主服务，不重新创建一个托管 Application；目录中的 package 批量读取，避免逐 Agent 查询。

编辑时省略 `sandbox` 字段会保留现有网络配置。API 配置示例：

```json
{"name": "Agent", "sandbox": {"network": "unrestricted"}}
```

### 包沙箱网络

在 `sage.yaml`（Studio JSON 对应 `manifest`）中按 Agent 声明：

```yaml
agents:
  assistant:
    name: Assistant
    instructions:
      inline: Be helpful.
    sandbox:
      network: unrestricted
```

`agents.<id>.sandbox.network` 只接受 `none` 和 `unrestricted`，省略时为 `none`。该字段沿用 package Schema、导入、校验及版本库存机制；其他值或未知沙箱字段会被拒绝。每个 Agent 单独配置，子 Agent 不继承父 Agent 的网络声明。

Server 在受理新 Run 时冻结有效沙箱配置，实际执行时按该快照创建工作区沙箱；子 Run 按标准规则继承，恢复后重建沙箱也使用原快照，不重新读取 Agent 的最新配置。实际权限取包声明与服务端上限的交集：任一为 `none` 即禁网。宿主可在构造 `ServerSettings(sandbox_network_mode="none", ...)` 时收紧全服务上限；默认上限为 `unrestricted`，仅允许包显式申请联网，未配置的包仍禁网。此上限没有环境变量入口。普通页面/API Agent 和托管包使用相同的网络策略；未配置的 Agent 保持禁网。

`unrestricted` 允许沙箱进程直接联网（包括私网），不提供域名白名单过滤；`none` 由实际沙箱隔离网络。网络模式参与沙箱 spec/policy 哈希，无法实施策略的宿主不会退化为无隔离执行。该配置控制沙箱内进程，不控制宿主侧模型、MCP、A2A 或可信源码插件的网络。

## A2A

外部 Agent 通过 JSON-RPC 入口 `/a2a/v1` 调用本机 Agent，Agent Card 在 `/a2a/v1/card` 与 `/.well-known/agent-card.json`。两个 card 路径都要鉴权：一个 Sage 宿主服务多租户，匿名 card 只能描述某个任意租户的 Agent。

鉴权用 API Key（`Authorization: Bearer sage_a2a.<key_id>.<secret>`），在 `/api/keys` 签发、查询和吊销，明文只在创建时返回一次，库里只存哈希。key_id 放在 token 里，校验是一次主键查询。Run 的 actor 是 key 的 owner（凭据本身记在 `delegated_by`），所以 A2A 起的会话在 Web UI 里照样能看到；但权限只取凭据上的 scope（`a2a:invoke` / `a2a:read`），不继承账号的控制台权限，且 `agent_id` 绑定在凭据里而非请求里，所以一把 key 到不了租户的其他 Agent。Scope 在 HTTP 层按 JSON-RPC 方法名校验后才进入 dispatcher。

已实现 `SendMessage`、`SendStreamingMessage`、`GetTask`、`SubscribeToTask`、`ListTasks`、`CancelTask`；push notification 返回 `UnsupportedOperation`。A2A Task 不单独存储，每次读取都从 Sage Run 的 canonical 事件日志重建，因此与 Web UI 看到的是同一份事实。

Run 一律交给后台任务驱动，不跑在请求自己的任务上：Run 是事实，响应只是它的一个视图，客户端中途断开或立刻回来取 Task，都不应该中断已经开始的工作。`SendMessage` 默认等到 Run 结束才返回终态 Task，`returnImmediately` 则返回受理那一刻的 Task，两者只差在把调用方挂多久。

流式遵循 A2A 的“先整体后增量”：第一帧是完整 Task，后续是 `statusUpdate` / `artifactUpdate` / `message` 增量，所以晚接入的客户端也不用自己拼状态。`SubscribeToTask` 把接入前的历史折进开场 Task 而不重放，已经终态的 Run 就只给一帧最终 Task。调用方自己写的 user message 不会作为增量回吐（它仍在 Task history 里）。A2A 1.0 的 `TaskStatusUpdateEvent` 没有 `final` 字段，流的结束由终态 `status.state` 加 SSE 断流表示。流式方法要求请求带 `A2A-Version: 1.0` 头，这是 SDK 的版本校验，非流式方法不强制。

### 用户执行授权

执行策略属于用户账号，控制台「执行设置」页、网页对话和该用户全部 API 密钥共用。API Key 只承担身份、Agent 绑定和接口 scope，不携带执行策略。使用账号 JWT 调用 `GET /api/auth/execution-policy` 读取，`PUT /api/auth/execution-policy` 更新：

```json
{
  "shell": "sandboxed",
  "on_approval_required": "suspend",
  "approval_timeout_seconds": 86400
}
```

用户的 `shell` 默认为 `sandboxed`，允许官方 Shell、文件修改工具在该用户工作区内执行；`ask` 要求命令和文件修改先审批；`deny` 禁止 Shell，其他工具仍按各自策略审核。Shell 网络取自 Agent package 的 `sandbox.network`（默认禁网），`sandboxed` 允许工作区内代码执行及文件删除，MCP/A2A 等外部工具仍保留原审批要求。机器调用不能管理 Agent 包。`on_approval_required=deny` 将所有需要审批的操作直接拒绝，适合无人值守。

生效策略取服务上限、Agent 上限、用户设置和请求限制的交集。服务上限由 `SAGE_SERVER_EXECUTION_SHELL_MODE`（默认 `sandboxed`）及 `SAGE_SERVER_APPROVAL_TIMEOUT_SECONDS`（默认 86400，允许 60–604800 秒）指定。Agent 的 `execution_policy` 是上限，默认允许用户自行选择；新用户默认允许工作区内自动执行。A2A 消息的 `metadata["sage.executionPolicy"]` 可提供相同结构收紧本次请求，不能扩大授权。

受理时冻结实际策略与哈希，恢复和每次工具决策都会重新检查用户当前策略、原密钥是否撤销、Agent 是否存在及当前上限。后续放宽权限不会扩大已受理任务的权限。机器回复审批必须额外持有 `a2a:approve`；只调用或读取的密钥不能批准操作，默认签发不包含审批权限。执行设置接口只接受用户登录凭据，API Key 不能修改账号策略。托管包运行继续使用自身 manifest 的工具策略。

用户可在对应会话中处理审批，或使用账号 JWT 调用 `GET /api/approvals?limit=50&offset=0`。分页按会话扫描，可能出现空页，应继续使用 `next_offset`。将条目的 `expected` 原样回传到 `POST /api/approvals/{run_id}/decisions`，body 为 `{"decision":"approve_once","expected":{...}}`，也支持 `deny`、`cancel`。过期或版本已改变返回 409；接口受理决定后由后台继续执行。

挂起后保留持久化 Run、事件和审批记录；执行任务退出、释放调度槽并销毁本轮沙箱及其中进程，工作区文件保留。恢复时重建执行资源，因此旧后台 Shell 作业不会跨审批挂起继续存活。宿主共享服务仍常驻。一个宿主维护任务每分钟清理过期审批，答复入口也检查有效期；不为每条审批创建等待任务。

### 审批消息与续跑

Sage 的"挂起 Run + 待答 Interaction"对应 A2A 的 `input-required` Task，回答就是一条带 `taskId` 的普通 Message。Task 的 `metadata` 会带上 `sage.interactionId`、`sage.interactionType`、`sage.allowedDecisions` 和 `sage.payload`：A2A 只说"需要输入"，不说需要哪种输入，不把决策词表交出去的话，客户端只能从给人看的散文里猜。

决策从 `message.metadata` 的 `sage.decision` 取，`sage.payload`（Struct）补充结构化字段，正文文本落进 `payload["text"]`。只有自由问答（`allowed_decisions` 含 `submit`）和只剩一个选项的问题才会在没有 `sage.decision` 时自行推断；审批类问题必须显式给出决策，答不上来一律 `InvalidParams`（-32602）而不是猜。"yes, go ahead" 和 "no, don't" 在英文里一样自然，把散文读成同意，写下去的副作用是撤不回的。

给一个并非在等输入的 Task 回消息同样是 -32602：A2A 没有"状态变了"这个错误码，而 -32002 的意思是"不能取消"，用在这里会让客户端放弃，正确的动作其实是重新读一次 Task。续接一个已经结束的会话不是给旧 Task 发消息，而是同一个 `contextId` 下开一个新 Task。

续跑的等待与流式都从"受理那一刻的 run sequence"往后看，不从头看：Run 的日志里已经躺着那条让它停下来的 `run.suspended`，从头读会立刻撞上它，把刚刚被回答掉的暂停当成"跑完了"回给调用方。

Web 侧对应 `POST /api/threads/{thread_id}/resume`（body 给 `runId` / `decision` / `payload`），同样以 AG-UI SSE 流回续跑过程。等待中的 Run 由 thread 自己认定而不由客户端指名，否则一个过期的页面可以回答两个 Run 之前的问题。

对话页从 `sage.interaction.requested` 这一条 CUSTOM 事件渲染审批卡片：问的是什么、允许哪几个决策，都由服务端给，客户端不自己编一套词汇。这条事件也落在 thread 事件里，所以关掉标签页再打开，等待中的问题还在，不用指望当时那条流。含 `submit` 的问题是自由问答，回答落进 `payload.text`。回答前会先把记录回退到本轮 Run 开始处——续跑的流是从 Run 的第一条事件重放的，不回退就会把已经在屏幕上的内容再叠一遍。用户自己那条消息排在 `RUN_STARTED` 之前，所以回退不会把它一起抹掉。

`CancelTask` 用调用方读到的 revision 做 compare-and-set，已经结束的 Run 报 `TaskNotCancelable`（-32002）而不是 `TaskNotFound`（-32001）——它存在，只是不能取消了。Sage 的 Run 索引挂在 Session 上而非租户上，所以 `ListTasks` 是按 owner 的 thread 再逐个 Session 走 Run，page token 是不透明的 `v1:<session_index>:<run_index>`，一页的成本只与这一页有关。

鉴权失败不出现在 JSON-RPC 错误表里：A2A 没有对应错误码，所以 scope 在 HTTP 层结算（403），跨租户读不到的 Task 报 `TaskNotFound`。流式请求若在第一个事件之前就被拒（例如订阅别人的 Task），SDK 返回的是普通 JSON-RPC 错误响应而非 SSE——此时还没有流可以放错误帧。

`a2a-sdk` 会引入 protobuf，因此放在可选 extra 里（`'.[server]'` 已包含，单独装是 `'.[a2a]'`）；没装时 A2A 路由不注册，启动日志会说明，其余接口不受影响。Agent Card 中的 URL 取 `SAGE_SERVER_PUBLIC_URL`，未配置则回落到请求的 base URL。

### 调用别的 Agent（出站）

`/api/a2a-agents` 维护租户可委派的远端 Agent：`url` 填对方的 base URL 而不是 JSON-RPC 端点，因为端点写在对方的 Agent Card 里，钉在记录上会在对方搬家的那一刻失效。`api_key` 明文只进不出（列表只回 `has_api_key`），`POST /{name}/refresh` 重新读一次 card。

card 上的每个 skill 变成一个工具 `a2a_<peer>_<skill>`，描述里始终写明对方是谁：问错组织不是重试能撤销的。工具是写级别且需要审批，所以第一次委派会挂起 Run 等人点头，Web 侧用 `POST /api/threads/{thread_id}/resume` 回答。返回值里带 `contextId`，下一次调用把它作为 `context_id` 传回去就续在同一个会话上；对方停下来要补充信息（`input-required`）时，答案里会直接说明该怎么继续。

card 声明的端点只在与配置的 host 相同时才采信，重定向也不跟：这条请求带着租户的凭据，一张能把它引到别的 host 的 card 就等于一个取凭据的入口。

出站不依赖 `a2a-sdk`，直接用 httpx 说 JSON-RPC，所以没装 extra 的部署照样能调别人，只是自己不能被调。

### 委派跳数

委派链没有自然终点，每个 Agent 只看得见眼前这一条请求。预算作为 `message.metadata` 的 `sage.callDepth` 随请求走，上限 4 跳，两端各管一半：出站方向，已经到上限的 Run 干脆不组合 A2A 工具（模型不会看到一个用了要挨骂的能力）；入站方向，超预算的请求直接 `InvalidParams` 拒掉，这一条管的是改写了深度的对端。深度在受理时冻结进 composition，所以续跑一个挂起的 Run 不会把预算清零。

Server API 用 `external_tools` 配置外部工具，页面与内置 `tools` 分开展示；持久化到标准 Agent Package 时合并进已有的 `tools` 名单，不扩展 SAgents schema。Server 按每个 Run 的 Agent 名单和工具授权过滤 MCP/A2A provider 后传入内核。页面在「智能体 → 编辑 → 可用工具 → 外部工具」勾选 MCP/A2A 工具；未选中任何外部工具时禁止调用，新增工具不会自动获得授权。原先依赖整个外部目录自动授权的 Agent，升级后需重新勾选并保存。工具审批设置仍独立生效。

## 模型观测

支持独立选择 `sage.trace.otlp`、`sage.trace.langfuse` 或 `sage.trace.phoenix`，共用运行、工具、模型输入输出、token 与首 token 观测。配置见 [V2 观测说明](../../../docs/zh/architecture/sagents-v2-observability.md) 和根目录 [`.env.example`](../../../.env.example)。这些导出插件需要安装 `.[otel]`；配置公开访问地址后，管理页显示对应平台入口。


### 内网业务调用 V2 chat

原 `POST /api/agent` 同时支持 Sage 登录态和内网业务头部身份。内网调用同时提供 `SAGE-AGENT-ID`、`SAGE-TENANT-ID`，必须提供 `Authorization: Bearer <该 Agent 的 API Key>`；`SAGE-TENANT-ID` 是外部业务用户唯一标识，无需在 Sage 注册。`SAGE-AGENT-ID` 全局唯一，由该 Agent 所属 Sage 账号提供模型、提示词、工具和技能配置。Server 校验 API Key、绑定的 Agent、所有者和权限，外部用户身份由通过鉴权的业务后端负责从登录态提取，不接受客户端任意冒用。

请求继续使用 AG-UI：`session_id` 是唯一会话身份，传入时原样使用；省略时由 Sage 生成。`threadId` 是兼容别名，两者同时传入必须完全一致，否则在启动 Run 前返回 422。空字符串、首尾空格及无效 ID 会被拒绝，不会静默规范化。`runId` 是本次请求唯一 ID，`messages` 中传用户文字和文件 URL。编辑复用响应中的 `session_id`，使用新的 `runId`；相同 `runId` 重试不会重复生成。SSE 的 `RUN_STARTED` / `RUN_FINISHED` 和结果接口同时返回 `session_id`、兼容字段 `threadId`，二者都指向实际持久化会话。

页面、`POST /api/agent`、`POST /api/agents/{agent_id}/runs` 共享以上契约。A2A 的 `contextId` 同样原样作为 session ID，缺省生成后通过 Task.contextId 返回。工具参数及模型上下文中的 `session_id` 由实际 Run 统一绑定，调用方和模型不能指定其他会话。`runtimeContext.session_id` 如有传入必须匹配请求会话。请求头中的 SAGE-AGENT-ID 优先于 forwardedProps.agentId。

当前 SessionStore 的 session ID 是全局主键，因此同一个 ID 不能被另一个 tenant 或 Agent 复用。`session_bindings` 以数据库唯一约束持久化 owner、tenant、Agent 归属；冲突启动返回 409，越权读取返回 404，不再通过改写 ID 实现隔离。绑定不会随会话删除转让给其他归属。部署时自动创建绑定表并将 MySQL threads.thread_id 扩为 VARCHAR(192)。

旧 `external_<hash>` 会话采用原位兼容，升级前应备份业务数据库、SessionStore 和 tenants 工作空间：携带原 tenant、Agent 和业务 ID 请求时，只探测已有旧哈希记录，不创建新的哈希会话；命中后返回旧的实际 `session_id`，后续应复用这个返回值。历史 Run、检查点、问卷、审批、事件及 `.sage/todos/<旧ID>.json` 都留在原位，workspace 仍使用原 `server_v2.workspace_user_id`。这是兼容读取和继续执行方案，不重写活动会话或 Todo 文件。若历史数据缺少 workspace 身份元数据，使用原 tenant/Agent/业务 ID 可验证已有旧哈希并建立可信绑定；恢复和工作空间浏览从该绑定补全身份，不修改旧命令。仅知道哈希时无法反推出 tenant，必须先核对原始身份，禁止猜测或把文件移到别的租户目录。旧 runId 重试复用持久化启动命令，输入、workspace 或运行上下文不同则明确拒绝，避免升级后幂等摘要改变。

```json
{"threadId":"work-123","runId":"request-456","messages":[{"id":"request-456","role":"user","content":"用户文字与素材 URL"}],"state":{},"tools":[],"context":[],"forwardedProps":{}}
```

后端可消费 SSE 而不向 App 展示；读取端断开不终止后台生成。`GET /api/threads/{threadId}/result?runId={runId}` 使用相同请求头查询本次结果；省略 `runId` 返回会话最新运行。返回 data 包含 `threadId`、`runId`、`state`、`text`、`error`；仅 completed 返回完整助手结果，运行中 text 为空。Sage 原生运行主键不对外返回。结果由现有持久化 SessionStore 重建，服务重启后仍可查询已落盘状态与结果，不增加额外结果表。未完成任务是否可继续执行取决于运行时持久化状态；不把重启视为成功完成。

标准登录用户也可使用该结果接口查询自己的 threadId。反向代理须透传原样的 `SAGE-AGENT-ID` / `SAGE-TENANT-ID` 请求头（使用中划线头名，无需开启下划线请求头透传）。

工作空间统一按用户与 Agent 隔离：同一用户的同一 Agent 跨 Session 共享，不同 Agent 不共享。外部 API 的用户身份取 `SAGE-TENANT-ID`，配置所有者只用于授权和配置读取，不作为外部用户的工作空间身份。用户/Agent ID 中的路径分隔符使用可逆 URL 编码，普通 ID 保持原样，不使用 SHA 目录。

长期记忆由 sagents 按可信用户身份与 Agent workspace 隔离，并保留宿主租户边界。外部调用的用户取 `SAGE-TENANT-ID`，不取共享 Agent 的配置所有者；同一用户与 Agent 的不同 Session、作品子目录共享该工作空间的长期记忆。身份在 Run 接受时由宿主传入并持久化，恢复执行、自动写入和 `search_memory` 使用同一隔离键，调用方的 metadata 不能覆盖它。BM25 插件持久化到 Server 数据目录；Agent Package 需启用记忆行为及 `search_memory` 工具。历史无 workspace 身份的记忆保留原文件，不自动迁入新范围，以免误分其他用户的数据。


工作空间查询须提供 `thread_id` 或 `agent_id`；有 Session 时由后端从持久化身份解析目录。旧用户共享目录和旧 SHA 目录不自动合并或复制；历史外部 Session 缺少原始用户标识时需要明确迁移映射，不能从 SHA 反推用户。


### 外部 workspace 与会话清理

内网业务接口使用 `SAGE-TENANT-ID`，Agent 取 URL 中的 `agent_id`，必须同时提供 `Authorization: Bearer <Agent API Key>`。所有运行、结果、回复、取消、文件和删除接口统一鉴权；GET 使用 `a2a:read`，调用和文件修改使用 `a2a:invoke`，回复交互使用 `a2a:approve`（沿用现有 API Key 权限名称）。Key 只能访问其绑定的 Agent，撤销后请求立即拒绝。业务后端必须从已验证的登录态提取用户 ID；Key 不应交给最终用户或前端。

- `DELETE /api/agents/{agent_id}/workspace/files?path=assets/site&recursive=true`：删除该租户、该 Agent workspace 内的相对文件或目录。`recursive` 默认 false，仅能删除文件、链接或空目录；true 可递归删除目录。不绑定业务实体或目录前缀。
- 成功返回 `data: {"path":"assets/site","deleted":true}`；目标不存在返回 200，`deleted:false`，不创建工作空间。禁止空路径、绝对路径、路径穿越和隐藏管理目录。路径祖先不能是符号链接；目标链接及子目录中的链接只删除链接本身，保留链接指向的数据。
- 错误通过 `error_detail` 区分：422 `invalid_workspace_path`；403 `workspace_permission_denied`；409 `workspace_busy` 或 `workspace_not_empty`；500 `workspace_storage_failure`。递归失败可能已删除部分内容，修复原因后可用相同请求重试；接口不会回滚已删除的文件。
- 同租户、同 Agent 有未结束 Run（包括排队、等待输入和恢复中的 Run），或本地执行尚未退出时返回 409。Run 的 working directory 不是文件访问隔离边界，因此保护整个 Agent workspace，即使待删除路径与 Run 的工作目录不同。先取消任务并等待执行退出，再重试清理。
- `DELETE /api/agents/{agent_id}/sessions/{session_id}`：独立清理该身份下的会话树和 thread 索引，重复调用成功，保留会话身份绑定及 workspace 文件；错误身份返回 404。有未结束任务时拒绝清理。是否与目录删除组合、调用顺序由业务后端决定。

删除与 Run 创建、文件导入在当前 server 进程内互斥；请求取消时会等待文件线程退出后释放互斥。运行冲突保护适用于现有单进程 server v2，不提供多 worker、多实例或外部进程直接写 workspace 时的分布式文件租约。

## 在线技能导入

技能页的“导入技能”支持本地 ZIP、在线 ZIP 和 `npx skills add` 命令。远程导入先解析并展示技能列表，用户选择后导入；同名且内容不同的技能需要明确选择“更新已有技能”。导入不自动修改智能体绑定。

- `POST /api/skill-import-previews`：登录用户提交 `{ "kind": "zip_url", "value": "https://example.com/skills.zip" }`，或 `{ "kind": "skills_cli", "value": "npx skills add vercel-labs/agent-skills --skill web-design-guidelines" }`。返回 `revision` 和 `candidates`；候选包含 `path`、`package_sha256`、`expected_version_id` 及 `new` / `unchanged` / `conflict` 状态。
- `POST /api/skill-imports`：保留相同的 `kind`、`value`、`revision`，增加 `items` 数组。每项提交候选的 `path`、`package_sha256`、`expected_version_id` 和显式更新开关 `overwrite`。来源内容或目标版本变化时要求重新预览；各项结果沿用 ZIP 上传的 `success_count`、`failed_count`、`results` 和 `skills`。
- 在线 ZIP 接受公开 HTTPS 443 地址，最大压缩体积 32 MiB、展开 64 MiB、2000 个条目，一次最多 32 个技能；重定向逐次校验，DNS 解析和连接固定到公开地址。使用 fake IP 的本机代理需要为服务端配置正常 DNS，私网和保留地址不会放行。
- Skills CLI 当前支持公开 GitHub 仓库简写、仓库或 tree 目录地址，支持 `--skill` / `-s`、`--list` / `-l` 和 `--yes` / `-y`。`--global`、指定其他 Agent 和 Shell 表达式不接受。服务器需 Node.js 22.20 以上、npx，并能访问 GitHub 与 npm registry；调用固定 `skills@1.7.2`，在隔离的临时目录中进行项目级复制安装，不执行技能脚本或 npm 安装脚本，不继承服务端凭据。

导入记录和内容仍使用已有的 Skill 版本及制品目录，不新增数据库表。npm 缓存位于 `{data_root}/runtime/skill-import-npm-cache`。运行时由 SDK 将技能包物化到工作区，已有文件内容不同时拒绝覆盖；更多设计见[远程导入方案](../../../docs/zh/architecture/skill-import-proposal.md)。

智能体配置页「可用技能」中的「Agent 技能同步」调用 `PUT /api/agents/{agent_id}/guidance`，以表单字段 `sync_bound=true` 同步已保存绑定的最新技能包。此模式仅允许 Agent 所有者调用，不提交或修改提示词，不发布新技能版本；旧工作区文件按现有同步逻辑备份后完整替换，各技能独立返回成功或失败结果。未创建的工作区由首次运行按需生成。原有 `prompt` + ZIP 上传模式继续使用同一接口。

## 标准运行控制边界

审批、问答、取消、已有暂停任务的继续和重启恢复均进入 Sage 标准 App/Runtime。产品后台任务只观察 SDK 执行并处理完成回调，不实现 Agent loop。当前 Server 未开放独立手动暂停或 Session 候选提交发布的 HTTP 接口；Goal/Plan 提交使用官方工具。各入口及验证边界见[标准控制接口核对](../../../docs/zh/architecture/sagents-v2-host-controls.md)。

### 工作区路径约定

Linux Server 的标准 `execution.binding` 显式使用 `workspace_alias: /workspace`，文件工具、Shell 和前端检查器共用沙箱内路径 `/workspace`；真实数据仍保留在 `tenants/<租户>/<Agent>/workspace`。Desktop 和 SDK 默认使用真实路径。执行环境发布 `SAGE_WORKSPACE_ROOT`，检查器以此定位 `.sage-tests`，不要求 Agent 建软链接或修复环境。

Web 工作目录树、单文件和目录 ZIP 下载按已授权的租户及 Agent 解析；API 接受相对路径与 `/workspace/...`，返回树节点使用相对路径，拒绝 `..`、其他绝对路径和软链接。Shell 默认启用 `pipefail`，检查命令经 `tail` 或 `tee` 输出时仍保留失败退出码。映射模式随 Run 配置冻结，旧真实路径 Run 恢复时不会静默切换模式；需新建 Run，工作区文件无需迁移。检查器用法见 [前端测试环境](../../../deploy/images/frontend-test/README.md)。

### 运行性能

管理员从 Web「系统设置 → 运行性能」（`/performance`）查看全局或单个 Agent 的最近 1/6/24 小时、7 天、指定日期或自定义范围。`GET /api/observability/performance` 同样仅向管理员开放；接受带时区的 `start`、`end`（最多 31 天）、`agent_id`、`bucket=hour|day` 和 `timezone_name`，默认上海时区。指标按请求开始时间归入时间桶，不按完成时间漂移。

启用 Phoenix 后，同一性能页内增加 Token、模型成本、错误请求、请求错误率和调用链工作台，不再单列外部 Phoenix 跳转。调用列表支持类型、状态及 `session_id` 精确筛选，点击 Session ID 可快速筛选；该筛选同步作用于 Phoenix 区域的汇总指标。Session ID 使用 Phoenix 的会话分组标识 `session.id`（由 trace 的 `session.sessionId` 返回），fork 的子会话仍遵循现有 root Session 分组。点击调用记录可在页内查看瀑布图及输入、输出、原始记录、事件、属性。列表分页加载轻量元数据，完整内容只在选择具体 span 时读取，原始内容按 Phoenix 中保存的数据展示。

这些查询均经 server 的管理员鉴权：`GET /api/observability/traces/summary`、`GET /api/observability/trace-spans`、`GET /api/observability/traces/{trace_id}/spans`、`GET /api/observability/trace-spans/{span_id}`。前两者接受统一时间范围和 `agent_id`、`session_id`；列表额外接受 `kind`、`status`、`cursor`。server 使用配置好的项目与凭据访问 Phoenix 的只读 GraphQL / REST API，不接受浏览器指定上游地址或查询语句，也不把上游凭据交给浏览器；不新增业务持久化。原有 console 链接在 Phoenix 模式下指向本地 `/performance`。

未启用 trace 后端（noop）时，计时与诊断证据写入本地 `runtime/diagnostics/evidence.sqlite3`。选择任一外部 trace 后端后，不创建、不写入该库。Langfuse 和通用 OTLP 暂不提供诊断查询，下载接口返回 409，性能入口不显示；不会回退本地采集。Phoenix 或 Jaeger 模式下，相同的轻量计时字段随 `sage.performance` spans 发往当前 trace 后端，页面按需查询外部 API，复用下述统计口径。Phoenix 默认使用 OTLP endpoint 去掉 `/v1/traces` 后的地址查询项目 spans；Jaeger 使用 Query v3 HTTP API，默认地址为 `SAGE_SERVER_JAEGER_PUBLIC_URL`。可用 `SAGE_SERVER_TRACE_QUERY_URL` 单独指定 server 可达的查询地址，用 `SAGE_SERVER_TRACE_QUERY_HEADERS_ENV` 指定查询凭据所在的环境变量名（默认 `OTEL_EXPORTER_OTLP_TRACES_HEADERS`，格式同 OTLP headers）。远程查询失败返回 503，不回退写入或混入旧本地历史。旧数据不自动迁移；部署本变更之前的 trace 不具有完整计时记录，统计受采样、导出失败和后端保留期影响。

“下载诊断包”使用观测层的异步 `export_evidence(session_id, run_ids)` 能力，服务端仅鉴权、核对 Run 的 Agent/tenant 归属并临时打包，不再调用业务存储的全量导出。ZIP 格式为 `sage.session-diagnostic-bundle/v2`，保留 `manifest.json`、`models.json`、`requests/`、`logs.json`、`tools.json`、`failures.json`，外部查询还包含 `traces.json`。移除 `state.json`、`session.json`、`runs/`、`events/`；不复制业务快照。工具结果和失败由观测 span/日志生成，缺失的历史结果不从业务事件反查，manifest 明确记录可用性。外部查询只包含该 Session 和权威 Run 白名单内的 trace。完整原始模型流是否可用由当前采集模式决定，不会从本地旧库补齐。MySQL 的会话、事件和恢复数据不受影响。

Phoenix 设置 `SAGE_SERVER_TRACE_CONTENT_MODE=raw`、`SAGE_SERVER_TRACE_SAMPLE_RATE=1.0` 时，Sage 不对上报内容脱敏或裁剪；模型输入输出、provider 请求体、SDK 暴露的流事件、规范化流事件、工具完整结构化结果（含 operation ID、metadata、error）及关联 Run 的结构化日志会发送到 Phoenix。原始诊断内容通过 `sage.diagnostic` spans 保存，不在业务数据库追加审计存储。raw 模式忽略 `SAGE_SERVER_TRACE_MAX_CONTENT_CHARS`，同时取消 Sage 的 8 MiB 流采集上限和 OTel 属性长度上限。流事件是 provider SDK 暴露的对象，不是 HTTP/TLS 网络字节。队列满、导出失败或进程退出仍可能丢失未送达的数据；这不是可靠归档。诊断 ZIP 的脱敏下载策略独立于 Phoenix 中保存的原始内容。

统计单位是一次用户请求的 Run，合并内部步骤；恢复执行仍属于原请求。起点在每次 AG-UI/A2A 运行入口、进入受理准备和 Agent 加载之前，沿调用链传入 SAgents；终点在 SDK 执行等待返回后、产品回调之前。每次发生的 Agent 加载、配置更新、受理、调度、工作区与上下文初始化以及 SDK 收尾均计入；进程启动时的一次性初始化、HTTP 请求传输和浏览器渲染不在这个范围内。暂停至用户答复之间的等待单列，恢复时的重复加载重新计时。

- **端到端首 token**：上述起点至主 Agent 首次产出推理或正文 token 的有效执行时间。摘要、记忆检索等内部辅助模型输出不充当用户首 token。只有工具调用参数、没有推理或正文的输出不会伪造一个首 token 时间。
- **首段正文**：起点至主 Agent 第一段正文；与首 token 分开，避免把用户看不到的推理当成正文响应。
- **模型首 token**：第一次主模型请求自身的 TTFT，供区分请求前准备和提供方等待。
- **框架耗时**：有效执行总时间减去全部 LLM 与工具执行区间的并集。摘要压缩、记忆检索、续跑判断的 LLM 均计入模型时间。并行区间只扣一次；框架时间是观察到的剩余墙钟时间，包含数据库、调度、上下文、序列化等等待，不代表 CPU 使用时间。

趋势提供 P50、P95 和框架占比。占比按完整样本的总框架时间除以总有效时间计算，不平均每个请求的百分比。未完成、失败、取消的请求不进入完成请求分位数；缺少模型结束或恢复边界等记录时，框架耗时显示缺失，绝不填零。历史记录缺少最外层初始化边界时标记「初始化未记录」，不与新口径混合比较。列表最多展示最近 200 条，汇总最多 10000 个请求或 100000 条轻量时间记录；达到上限时明确标记，应缩小时间范围。

诊断写入线程同时维护仅含身份、时间戳和分类的 SQLite 轻量投影；页面查询只读取这些索引表，不加载模型上下文、文件、工具参数或诊断导出。采集维持有界异步队列，失败与丢失数在页面提示，不阻塞首 token。已有诊断可由管理员显式执行一次时间字段回填，不在启动或页面请求中自动扫描大记录：

```sh
python -m app.v2.server.observability.performance --backfill /app/data/runtime/diagnostics/evidence.sqlite3
```

回填只提取时间字段，幂等写入；不能凭历史数据补造缺失的初始化边界。
