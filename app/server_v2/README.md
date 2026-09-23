# Sage Server v2

多用户 AG-UI 宿主。代码直接在 `app/server_v2/`，前端在 `web/`。

```text
api/            HTTP 路由与鉴权
schemas/        OpenAPI / 请求响应 DTO
services/       跨聚合用例（Sage runtime + AG-UI）
domain/         领域记录与规则，不碰 SQL
repositories/   MySQL 仓储（实现 domain 端口）
db/             表元数据
storage/        工作区 / session 目录
agui/           AG-UI 映射与回放
a2a/            A2A 协议映射（Card / Task / JSON-RPC handler）
core/           基础设施
```

新业务按 `domain/<name>.py` + `repositories/<name>.py` 加；有跨表/跨系统编排再加 `services/<name>.py`。

生产启动只强制 MySQL：`SAGE_SERVER_MYSQL_URL`。AG-UI 回放直接读取 Sage Session 的 canonical RuntimeEvent。

单进程并发可用 `SAGE_SERVER_MAX_CONCURRENT_RUNS`（默认 8）、`SAGE_SERVER_MAX_CONCURRENT_RUNS_PER_USER`（默认 2）和 `SAGE_SERVER_MAX_PENDING_RUNS`（默认 1024）配置。参数必须为正数，分别约束总执行、每用户执行及等待队列，见[单机并发说明](../../docs/zh/architecture/sagents-v2-single-host-concurrency.md)。

Server 只支持单 worker：SessionStore 只接受一个 writer（`multi_process_writes: False`），订阅者留在进程内，Scheduler 与 JobRuntime 是内存实现。第二个进程会在获取独占 writer 锁时启动失败。MySQL 让 Session 状态跨重启存活，但不提供横向扩容。manifest 的 `required_guarantees` 在装配阶段校验 SessionStore 的事务性、持久性与 actor 授权能力。

```bash
# 后端依赖（仓库根目录，Python 3.12+ 环境）
python -m pip install -e '.[server-v2]'

cd app/server_v2/web && npm install && npm run build
cd ../../..
python -m app.server_v2 --data-root /tmp/sage-server-v2
```

开发也可开 Vite：`app/server_v2/web` 的 `npm run dev` 代理到 `8090`。

读 `app/server_v2/.env`（进程环境变量优先）。生产必须设置 `SAGE_SERVER_JWT_SECRET`（至少 32 字节）。默认管理员：`admin` / `admin12345`。OpenAPI 在 `/docs`。

成功/失败 JSON 都带 `request_id`，并回写 `X-Request-ID`。可传入该请求头以透传。

## 数据

| 数据 | 生产 | 测试 |
|---|---|---|
| 用户 / catalog / 会话索引 | MySQL `users` / `catalogs` / `threads` | Memory mock |
| Sage Session | `sage.session.mysql`（无表前缀） | filesystem（`data_root/runtime/sessions`） |
| AG-UI 回放 | Sage Session `run_events` | Sage Session `run_events` |
| 工作区 | `{data_root}/tenants/{user_id}/workspace/` | 同左 |
| Skill catalog | MySQL `skills` / `skill_versions` / `agent_skill_selections`；artifact 相对路径 `{data_root}/skills/...` | Memory mock + 同左磁盘 |
| Agent / MCP / A2A peer | `catalogs` JSON：`agents[]`（提示词、model_id、tools、skills）+ `mcp_servers[]` + `a2a_agents[]` | 同左 |
| A2A API Key | MySQL `api_keys`（只存哈希） | Memory mock |

对话：首次 run 把 `agent_id` 钉在会话上（之后忽略下拉/`forwardedProps`）；读 catalog Agent → Official 文件/沙箱工具 + MCP + A2A peer + skill 组成 Composite，再 `materialize_agent` 加载 sagents/v2 loop。进程 Application 只 build 一次。

`/health` 的 `backends` 按实际装配报告 `host_store`（`mysql` / `memory`）、`session_store`（`mysql` / `filesystem`）、`agui_replay`、`log` 和 `run_ownership`（恒为 `single-process`），配了 `SAGE_SERVER_JAEGER_URL` 再多一个 `trace`。sagents 结构化日志由 host 固定接到 `sage.logging.stdout`，默认输出 `sage.log/v1` JSONL；`SAGE_SERVER_LOG_LEVEL` 控制最低级别，`SAGE_SERVER_LOG_FORMAT` 可显式切到本地阅读用的 `text`。stdout 的持久化由容器日志驱动或 Alloy/Loki 负责，不写审计业务表。

模型客户端池使用 `SAGE_SERVER_MAX_MODEL_CLIENTS`（默认 64）限制容量。同一用户的相同配置跨 Run 复用连接，凭据变化使用新客户端；池满且所有客户端占用时返回可重试的限流错误。详见[模型池与增量持久化](../../docs/zh/architecture/sagents-v2-model-pool-and-persistence.md)。

## 完整 Agent 包平台与 Studio

`/studio` 提供完整包定义编辑、普通 Agent 导入、不可变版本、复制/切换版本、运行、事件、任务历史、反馈、人工审批和同 Session 续接。对应 HTTP 入口为 `/api/agent-packages`。普通 Agent 可选择 `agent_package_*` 工具，通过同一管理服务创建并调用其他 Agent。

生产库存使用 MySQL `managed_agent_records`；managed Session 使用独立 MySQL 前缀，验证用临时文件存储。普通对话与包任务共享运行/用户额度、模型额度和 JobRuntime。可通过 `SAGE_SERVER_MAX_MANAGED_APPLICATIONS`（默认 32）和 `SAGE_SERVER_MAX_MANAGED_BUILDS`（默认 4）控制实例与装配容量。

包模型使用 `provider=server`，`model` 指向本人模型 ID 或 `default`，不携带凭据和地址。源码插件默认关闭，只有宿主注册与明确授权后才能加载，且属于可信宿主代码。能力、API、部署成本和验证边界见 [Server V2 Agent 平台](../../docs/zh/architecture/SERVER_V2_AGENT_PLATFORM.md)。

## A2A

外部 Agent 通过 JSON-RPC 入口 `/a2a/v1` 调用本机 Agent，Agent Card 在 `/a2a/v1/card` 与 `/.well-known/agent-card.json`。两个 card 路径都要鉴权：一个 Sage 宿主服务多租户，匿名 card 只能描述某个任意租户的 Agent。

鉴权用 API Key（`Authorization: Bearer sage_a2a.<key_id>.<secret>`），在 `/api/keys` 签发、查询和吊销，明文只在创建时返回一次，库里只存哈希。key_id 放在 token 里，校验是一次主键查询。Run 的 actor 是 key 的 owner（凭据本身记在 `delegated_by`），所以 A2A 起的会话在 Web UI 里照样能看到；但权限只取凭据上的 scope（`a2a:invoke` / `a2a:read`），不继承账号的控制台权限，且 `agent_id` 绑定在凭据里而非请求里，所以一把 key 到不了租户的其他 Agent。Scope 在 HTTP 层按 JSON-RPC 方法名校验后才进入 dispatcher。

已实现 `SendMessage`、`SendStreamingMessage`、`GetTask`、`SubscribeToTask`、`ListTasks`、`CancelTask`；push notification 返回 `UnsupportedOperation`。A2A Task 不单独存储，每次读取都从 Sage Run 的 canonical 事件日志重建，因此与 Web UI 看到的是同一份事实。

Run 一律交给后台任务驱动，不跑在请求自己的任务上：Run 是事实，响应只是它的一个视图，客户端中途断开或立刻回来取 Task，都不应该中断已经开始的工作。`SendMessage` 默认等到 Run 结束才返回终态 Task，`returnImmediately` 则返回受理那一刻的 Task，两者只差在把调用方挂多久。

流式遵循 A2A 的“先整体后增量”：第一帧是完整 Task，后续是 `statusUpdate` / `artifactUpdate` / `message` 增量，所以晚接入的客户端也不用自己拼状态。`SubscribeToTask` 把接入前的历史折进开场 Task 而不重放，已经终态的 Run 就只给一帧最终 Task。调用方自己写的 user message 不会作为增量回吐（它仍在 Task history 里）。A2A 1.0 的 `TaskStatusUpdateEvent` 没有 `final` 字段，流的结束由终态 `status.state` 加 SSE 断流表示。流式方法要求请求带 `A2A-Version: 1.0` 头，这是 SDK 的版本校验，非流式方法不强制。

### 等待输入与续跑

Sage 的"挂起 Run + 待答 Interaction"对应 A2A 的 `input-required` Task，回答就是一条带 `taskId` 的普通 Message。Task 的 `metadata` 会带上 `sage.interactionId`、`sage.interactionType`、`sage.allowedDecisions` 和 `sage.payload`：A2A 只说"需要输入"，不说需要哪种输入，不把决策词表交出去的话，客户端只能从给人看的散文里猜。

决策从 `message.metadata` 的 `sage.decision` 取，`sage.payload`（Struct）补充结构化字段，正文文本落进 `payload["text"]`。只有自由问答（`allowed_decisions` 含 `submit`）和只剩一个选项的问题才会在没有 `sage.decision` 时自行推断；审批类问题必须显式给出决策，答不上来一律 `InvalidParams`（-32602）而不是猜。"yes, go ahead" 和 "no, don't" 在英文里一样自然，把散文读成同意，写下去的副作用是撤不回的。

给一个并非在等输入的 Task 回消息同样是 -32602：A2A 没有"状态变了"这个错误码，而 -32002 的意思是"不能取消"，用在这里会让客户端放弃，正确的动作其实是重新读一次 Task。续接一个已经结束的会话不是给旧 Task 发消息，而是同一个 `contextId` 下开一个新 Task。

续跑的等待与流式都从"受理那一刻的 run sequence"往后看，不从头看：Run 的日志里已经躺着那条让它停下来的 `run.suspended`，从头读会立刻撞上它，把刚刚被回答掉的暂停当成"跑完了"回给调用方。

Web 侧对应 `POST /api/threads/{thread_id}/resume`（body 给 `runId` / `decision` / `payload`），同样以 AG-UI SSE 流回续跑过程。等待中的 Run 由 thread 自己认定而不由客户端指名，否则一个过期的页面可以回答两个 Run 之前的问题。

`CancelTask` 用调用方读到的 revision 做 compare-and-set，已经结束的 Run 报 `TaskNotCancelable`（-32002）而不是 `TaskNotFound`（-32001）——它存在，只是不能取消了。Sage 的 Run 索引挂在 Session 上而非租户上，所以 `ListTasks` 是按 owner 的 thread 再逐个 Session 走 Run，page token 是不透明的 `v1:<session_index>:<run_index>`，一页的成本只与这一页有关。

鉴权失败不出现在 JSON-RPC 错误表里：A2A 没有对应错误码，所以 scope 在 HTTP 层结算（403），跨租户读不到的 Task 报 `TaskNotFound`。流式请求若在第一个事件之前就被拒（例如订阅别人的 Task），SDK 返回的是普通 JSON-RPC 错误响应而非 SSE——此时还没有流可以放错误帧。

`a2a-sdk` 会引入 protobuf，因此放在可选 extra 里（`'.[server-v2]'` 已包含，单独装是 `'.[a2a]'`）；没装时 A2A 路由不注册，启动日志会说明，其余接口不受影响。Agent Card 中的 URL 取 `SAGE_SERVER_PUBLIC_URL`，未配置则回落到请求的 base URL。

### 调用别的 Agent（出站）

`/api/a2a-agents` 维护租户可委派的远端 Agent：`url` 填对方的 base URL 而不是 JSON-RPC 端点，因为端点写在对方的 Agent Card 里，钉在记录上会在对方搬家的那一刻失效。`api_key` 明文只进不出（列表只回 `has_api_key`），`POST /{name}/refresh` 重新读一次 card。

card 上的每个 skill 变成一个工具 `a2a_<peer>_<skill>`，描述里始终写明对方是谁：问错组织不是重试能撤销的。工具是写级别且需要审批，所以第一次委派会挂起 Run 等人点头，Web 侧用 `POST /api/threads/{thread_id}/resume` 回答。返回值里带 `contextId`，下一次调用把它作为 `context_id` 传回去就续在同一个会话上；对方停下来要补充信息（`input-required`）时，答案里会直接说明该怎么继续。

card 声明的端点只在与配置的 host 相同时才采信，重定向也不跟：这条请求带着租户的凭据，一张能把它引到别的 host 的 card 就等于一个取凭据的入口。

出站不依赖 `a2a-sdk`，直接用 httpx 说 JSON-RPC，所以没装 extra 的部署照样能调别人，只是自己不能被调。

### 委派跳数

委派链没有自然终点，每个 Agent 只看得见眼前这一条请求。预算作为 `message.metadata` 的 `sage.callDepth` 随请求走，上限 4 跳，两端各管一半：出站方向，已经到上限的 Run 干脆不组合 A2A 工具（模型不会看到一个用了要挨骂的能力）；入站方向，超预算的请求直接 `InvalidParams` 拒掉，这一条管的是改写了深度的对端。深度在受理时冻结进 composition，所以续跑一个挂起的 Run 不会把预算清零。

MCP 与 A2A 这类租户自己的目录，工具授权按目录整体授予而不按 Agent 勾选——Agent 的 `tools` 列表里只有官方工具，产品也只让它选这些，而对方的工具要读到 card / `list_tools` 才存在。授权在每个 Run 解析一次而非在装配时快照，所以新加一个 peer 不用等缓存的 Application 过期；普通对话与包任务走同一条授权。
