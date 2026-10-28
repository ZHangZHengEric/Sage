# 飞书 IM P0

飞书自建应用通过事件 Webhook 接入 V2 Server。仅处理已配对本人的 `p2p` 文本消息，执行沿用 `RunAdmission`、`RunService(native)`、SessionStore 和现有审批页面。无需启动旧的 `mcp_servers/im_server`。

## 部署配置

安装服务端依赖 `python -m pip install -e '.[server]'`。生产沿用现有 MySQL 与 SessionStore 配置，启动时创建四张缺失的渠道业务表：`im_connections`、`im_conversation_bindings`、`im_inbox`、`im_deliveries`。它们仅存连接、绑定及收发恢复状态，不存第二份聊天历史，不新增审计库。

部署配置固定公网地址：

```dotenv
SAGE_SERVER_PUBLIC_URL=https://sage.example.com
```

服务端首次启动自动生成独立的凭据加密主密钥，原子保存至 `<data_root>/secrets/im-credentials.key`（文件权限 `0600`、目录权限 `0700`），重启读取并复用，无需手动配置密钥或环境变量。密钥位于用户工作区之外，独立于 JWT secret。并发首次启动不会覆盖已生成的密钥；已有连接时若密钥丢失、损坏或无法解密，服务仍正常启动，仅将受影响连接停用并显示「不可用」，保留原密文且不自动替换密钥。恢复原密钥备份后，在 IM 管理中测试凭据并重新启用。

部署时持久化并备份服务端数据目录，数据库备份须配套保留 `secrets` 目录。多副本须挂载同一份持久化 `secrets` 目录，再启动服务。每位用户在页面填写自己的飞书应用凭据；服务端加密后保存在现有 `im_connections.config`，不新增密钥表。密文绑定 owner、app 与 tenant，接口不返回明文或密文。先前的环境变量引用配置需由本人删除后重新创建。

`SAGE_SERVER_PUBLIC_URL` 必须为 HTTPS，包含反向代理路径前缀时会原样保留。审批链接使用此配置，不使用外部请求的 Host。此地址需要能打开现有 Sage Web 页面；模型、工具授权和登录继续使用原有配置。

## 创建连接

用户通过一级菜单「IM管理」（`/im`）直接创建本人连接，或使用自己的 Sage Bearer token 调用 `POST /api/im/connections`。owner 只取当前登录身份，`agent_id` 必须属于本人，不接受 `owner_user_id`、跨用户 Agent 或部署环境变量引用：

```json
{
  "agent_id": "agent_existing_agent",
  "name": "我的飞书机器人",
  "config": {
    "app_id": "cli_actual_app_id",
    "tenant_key": "actual_tenant_key",
    "app_secret": "<your app secret>",
    "verification_token": "<your verification token>",
    "encrypt_key": "<your encrypt key>"
  }
}
```

创建前先验证 App ID / App Secret 能取得飞书 tenant token，失败不会占用账号；临时网络故障可重试。返回 `data.id`，例如 `im_...`，公开配置仅包含 app_id、tenant_key 与 credentials_configured 状态。相同 app/tenant 不能重复认领。P0 Agent 与账号配置在创建后固定；启停使用带 `revision` 的 PATCH，不沿用旧插件页面的全局默认绑定接口。

在飞书开发者后台：

1. 启用自建应用的机器人能力，开放给要配对的本人并发布应用。
2. 为机器人配置接收用户私聊消息及以应用身份发送消息的权限，例如 `im:message.p2p_msg:readonly`、`im:message:send_as_bot`；以应用后台展示的可用权限为准。
3. 选择将事件发送到开发者服务器，配置 Encrypt Key 与 Verification Token，与本人在 Sage 连接表单中填写的值相同。
4. 将事件请求地址设为 `https://sage.example.com/api/im/webhooks/<connection_id>`，完成 challenge 校验。
5. 订阅 `im.message.receive_v1`。P0 不订阅卡片回调，不接受群消息、图片、消息编辑或撤回作为 Agent 输入。

URL challenge 使用 Verification Token 校验；普通事件必须通过 Encrypt Key 对原始 body 的签名校验，时间窗口为五分钟，支持 AES-256-CBC 加密事件。还会校验 app_id、tenant_key 和 sender_type，不依赖路径中的连接 ID 作为凭据。

## 本人配对与对话

连接 owner 使用自己的 Sage 登录身份调用 `POST /api/im/connections/{id}/pairings`。返回单次配对码、`/pair <code>` 命令与十分钟有效期。将命令发送到飞书机器人的私聊。只有配对成功的 open_id 能调用该连接；配对码不写入消息正文或日志，仅保存摘要，连续五次错误后须重新生成。

配对成功后：

- 直接发送文字：进入原生 Sage Run，回复最终可见文本；长回复按固定分片投递，超长内容提供 Sage 页面链接。
- `/new`：创建新的 Sage Session；重复平台回调不会重复重置。旧 Session 保留在 Sage，旧代次尚未投递的回复被抑制。
- `/stop`：请求取消当前 Run；若任务尚未受理，取消待办输入。取消同样受 Run revision 校验，回复不会被当作新 Agent 指令。
- 需要人工审批或补充信息：收到 `https://sage.example.com/?thread=<session_id>`，登录 Sage 后通过现有界面处理。链接不携带认证 token，也不自动批准。重复轮询同一 suspension 只生成一次通知。

IM 始终作为受委托入口执行，Shell 权限最多为 `ask`，仍取 Server、用户、Agent 的交集；Agent 包管理与自配置不会因飞书消息获得额外权限。工具调用、模型调用和审批恢复均复查连接授权。禁用连接会撤销原入口授权并停止待发回复；已发生的外部请求无法撤回。重新启用不会重新执行旧授权代次的输入。

## 管理接口

除 Webhook 使用飞书认证，其余接口均要求 Sage 登录，只操作本人连接；创建也由普通用户自助完成。

| 接口 | 作用 |
| --- | --- |
| `GET /api/im/plugins` | 飞书插件的配置 Schema 与 P0 能力 |
| `GET /api/im/connections` | 本人连接列表，部署最多 200 个连接 |
| `GET /api/im/connections/{id}` | 本人连接详情，不返回密钥值与配对码 |
| `PATCH /api/im/connections/{id}` | `{"revision": 1, "enabled": false}`，旧版本返回冲突 |
| `GET /api/im/connections/{id}/status` | unavailable（凭据不可解密）、disabled、awaiting_pairing、webhook_ready；不代表生产消息权限已联调 |
| `POST /api/im/connections/{id}/test` | 验证 tenant token 获取，不发送测试消息 |
| `POST /api/im/connections/{id}/pairings` | 创建或刷新本人配对挑战 |
| `GET /api/im/connections/{id}/deliveries?after=0&limit=50` | 分页读取投递状态与脱敏错误 |
| `DELETE /api/im/connections/{id}?revision=1` | 删除渠道配置与收发状态，保留既有 Sage 会话 |
| `DELETE /api/im/deliveries/{id}?revision=3` | 丢弃已失败/未知投递，解除目标队列阻塞 |
| `POST /api/im/deliveries/{id}/retries` | 重试失败项；需传当前 `revision`；unknown 还须显式传 `{"revision": 3, "allow_duplicate": true}` |

Web 一级菜单 **IM管理**（`/im`）提供飞书连接管理。每位用户选择自己的 Agent、填写自己的应用凭据，自助创建与管理连接，不需要管理员代配；账号参数创建后只读。页面支持复制服务端配置的回调地址、启停/删除连接、凭据测试、生成本人配对码并刷新配对状态。密钥输入使用密码框，关闭表单后清除；配对码仅保留在当前弹框中，关闭或过期后清除，两者均不写入浏览器存储。

投递管理默认按服务端 `unresolved=true` 筛选失败与未知状态后分页，可切换全部投递。重试和丢弃携带当前 revision；未知投递重试需在弹框中显式接受重复发送风险。审批仍在现有 Sage 会话页面处理，Swagger `/docs` 保留接口联调入口。

## 模型最终通知工具

绑定通知目标的 Run 会通过现有 V2 ToolProvider 获得内置 `im_notify(content)`。模型在完成业务工作后，为 IM 编写独立的简短结果正文；普通最终答案仍用于 Sage 会话。工具只接受 `content`（1–20000 字符的非空文本），目标用户、连接、私聊、Run 和会话代次由服务端冻结，模型不能传收件人或改路由。子 Run 和 Plan 模式不暴露此工具。

工具返回 `{"notification_id": 123, "status": "prepared"}`，表示正文已持久化，不表示平台已收到。Run 真正完成后才把该正文投影为待发消息；未调用工具时使用公开最终答案兜底。失败、取消时发送状态提示，不发送先前准备的成功文案；等待审批时发送原有 Sage 会话链接。相同 Run 的最终通知只生成一次，不会同时发送工具正文和普通最终答案。

审批中的 `cancel` 决策与网页停止、飞书 `/stop`、Run 取消接口都终止本次 Run，不再请求模型或执行剩余工具；`deny` 只拒绝该次工具调用，模型仍可继续处理。审批取消若与暂停或其他控制操作发生版本冲突，会重新读取 Run 完成取消，不能把拒绝回执当成成功并退出执行。审批链接已投影的 suspension 标记与消息在同一事务中记录到现有通知意图，已送达记录清理后也不会再次发送同一审批链接；进入新的审批时仍可通知。

复用 `im_deliveries` 保存 Run 通知意图和实际投递，仅新增可空 `run_context` JSON 字段；已有表由服务端启动时补充字段，不新建审计表或第二份聊天历史。受理前先登记 `prepared` 意图，Run 的事实仍从 SessionStore 读取。工具操作中断后通过已有工具 reconcile 链路核对 SQL 草稿，服务重启不需要重新调用模型生成正文。尚未受理的有效意图会保留并退避复查，每连接最多 1000 个；失效的连接授权或会话代次会关闭旧意图。实际通知继续沿用原有连接租约、分片、unknown 管理和人工重试链路。

网页会话的输入框提供「IM 通知」选择，仅列出本人已启用并配对的连接；默认不通知，新会话清空选择。IM 私聊发起的 Run 自动绑定原私聊。

网页/API 请求可在顶层传入 `notification_connection_id`：

```json
{
  "session_id": "daily-report",
  "runId": "daily-report-20261028-0900",
  "messages": [{"id": "request-1", "role": "user", "content": "生成今天的报告，完成后通知我"}],
  "notification_connection_id": "im_<own-connection-id>"
}
```

登录用户调用 `POST /api/agent`。外部定时调度器调用 `POST /api/agents/{agent_id}/runs`，使用该用户的 Agent API key（`a2a:invoke`）和 `SAGE-TENANT-ID: <该 Sage 用户自己的 user_id>`；业务租户身份不能向凭证持有人发送 IM。每次计划触发使用独立 `runId`，同次触发重试保留原 `session_id`、`runId`、消息和通知目标。外部请求重放、客户端断开与服务重启均复用原 Run，不创建第二个通知 Run。V2 当前没有独立 cron 管理模块，这一入口用于接入已有外部调度器。

## 恢复与投递语义

Webhook 先将有效输入提交业务数据库，再向平台 ACK。后台轮询只做唤醒和领取，普通输入队列满返回可重试错误，不能 ACK 后仅留下一个内存 Task。每连接最多 1000 项待处理输入；`/stop` 与 `/new` 在输入队列满时仍可使用。

入站同时按平台 event ID 和 message ID 去重。同 key 不同内容返回冲突。受理前持久化冻结的 StartRun；若 Run 已接受而 inbox 的 run_id 尚未保存，恢复时按原 key 查找原 Run，不创建第二个 Run，也不读取更新后的 Agent 来替换已冻结命令。

终态与挂起信息从 Sage Session 读取。出站 intent 与 inbox 完成状态在同一业务事务内写入；Run 成功和平台发送成功是两件事。SUSPENDED 保留运行关联，审批后继续投影原 Run；重启不丢失挂起关联。

平台实例通过现有 ExtensionHost 加载命名 `im.channel-factory:feishu`。跨连接最多八路并发，后台以数据库连接租约领取工作，过期领取者不能确认投递。发送按外部会话保序、分片 UUID 固定；响应明确接受后记为 `platform_accepted`，不代表用户已读。临时限流/尚未连接有界退避，最多自动尝试五次；发送后超时、不可解析回执或 worker 在发送中丢失记为 `unknown`，不自动重发。unknown/failed 会阻挡同目标后续发送，须检查后按当前 revision 重试或丢弃；旧版本操作返回冲突。

已完成审批的旧链接、来源授权已撤销的通知会自动标记为 `superseded` 并清空正文，包括 failed/unknown 状态，避免堵住后续仍合法的通知。清理使用连接租约和投递 revision 比较，不能覆盖并发的人工重试；仍有效的 unknown 不会自动重发或丢弃。

飞书消息请求携带稳定 `uuid` 作为平台去重辅助；不依赖平台去重窗口来保证任意时间的 exactly-once。unknown 的人工重试可能重复发送，因此接口要求显式接受此风险。inbox 去重记录保留七天，正文与冻结请求在任务完成后即清理；已接受出站载荷也即时清空，已完成记录七天后清理。未解决的 unknown/failed 不自动删除。

连接租约有效期为 60 秒。正常关闭会释放本 worker 的租约；进程崩溃后由下一 worker 在租约到期后接管。P0 的数据库领取机制在本地 SQLite 仓储测试中验证。多副本 MySQL/Redis 的故障选主与真实平台网络场景需要部署验收，不能用本地恢复测试替代。

## 本地验证与真实联调

```bash
python -m pytest tests/app/v2/server/im -q
```

测试使用实际 V2 Host、SQLite 业务仓储、文件 SessionStore 和 scripted model；仅飞书网络传输用 httpx MockTransport/发送替身。包含验签解密、伪造/过期拒绝、私聊与身份隔离、重复回调、重置、运行前/运行中取消、审批恢复与撤权、冻结受理、全 Host 重启和不确定发送恢复。

2026-10-28 本地验证记录：

- 通知链路复核：IM、启动 schema 与原生审批取消专项 102 项通过；其中三种入口的审批/取消/重启矩阵 30 项通过，覆盖挂起时重启、批准已提交但尚未执行时重启、再次重启去重、跨用户审批拒绝、失败/unknown 链接失效、并发暂停后的取消和最终正文。另验证已撤销定时凭据的失败投递不阻塞新任务，以及活跃审批记录清理后的去重。
- 复核原生 Agent loop 153 项通过，前端 168 项通过。真实浏览器操作审批页“取消本次运行”，工具显示已取消、文件未写入、未请求后续成功正文，只有一条取消通知；浏览器控制台无错误。模型和飞书网络使用隔离替身。
- Server 非 live 复核 937 项通过、1 项跳过，另有原先下载测试的 teardown 错误（见下方原始验证记录）；本轮 Ruff、diff 空白与架构检查通过。文档检查仍只有原有 RSI 的四项问题。
- 本次 `im_notify`：IM 与启动 schema 专项 65 项通过，覆盖模型正文、成功/失败/取消、审批、受理重试、完整 Host 重启、工具 reconcile 和 unknown 人工重试；网页与定时调用的归属隔离和幂等重放均通过。
- 本次前端 168 项通过，生产构建通过。真实浏览器验证网页选择本人连接、模型调用工具、Run 完成后只产生一条最终通知；模型和飞书网络使用隔离替身。
- 本次 Server 回归 907 项通过、1 项跳过，另有既有下载测试 `test_session_download_never_exports_business_aggregate` 的 teardown 错误（monkeypatch 清理时 `FilesystemSessionStore.read_events` 不存在）；未修改该用例及对应 SDK。
- 前次 IM 专项：45 项通过，包括自动密钥生成与并发发布、密钥丢失/损坏/替换后的启动隔离与恢复、用户自助创建、拒绝越权/旧 env 字段、凭据验证失败不占用账号、加密归属绑定和原有 Run/恢复链路。
- 前次 IM 与 Server 启动/配置回归：113 项通过。
- 前次前端：166 项通过，生产构建通过。真实浏览器验证普通用户创建、密钥密码框/关闭清除、配对、状态、启停、失败筛选、58 条跨页投递与未知重试确认；320/768/1024/1440px 无整页横向溢出。另在真实浏览器验证密钥损坏后显示不可用、恢复备份后测试并重新启用。飞书网络使用隔离替身。
- 前次 Server 非 live 回归：877 项通过、1 项跳过、1 项失败、1 项 teardown 错误。图片验收的沙箱错误与下载测试 monkeypatch 的 SessionStore 方法缺失，均在未修改的 HEAD 复现。
- P0 后端阶段完整 V2 非 live 回归：5083 项通过、59 项跳过，另有 125 项失败与 9 项错误，未全绿。失败包含本机禁止进程资源监控/本地端口监听、缺失 pandas/filelock 与评测数据，以及既有 RSI/SessionStore 用例问题；已在 HEAD 抽查复现非环境断言，不代表逐项完成全量基线核验。
- 本次 Python 文件的 Ruff、diff 空白检查与架构检查通过。文档检查仍报告 HEAD 已有的 RSI 翻译结构和缺少对应文档问题。

真实联调需配置实际应用凭据及回调域名，再依次验证：challenge → 本人配对 → 文本回复 → `/new` → `/stop` → 需要审批的任务 → Sage 登录批准 → 服务端重启后继续收发。当前实现没有把 mock 结果声明为飞书生产链路已验收。

协议依据：[飞书事件接收](https://open.feishu.cn/document/server-docs/event-subscription-guide/event-subscription-configure-/encrypt-key-encryption-configuration-case)、[接收消息事件](https://open.feishu.cn/document/server-docs/im-v1/message/events/receive)、[发送消息](https://open.feishu.cn/document/server-docs/im-v1/message/create)、[官方 Python SDK 验签](https://github.com/larksuite/oapi-sdk-python/blob/v2_main/lark_oapi/event/dispatcher_handler.py)、[官方解密实现](https://github.com/larksuite/oapi-sdk-python/blob/v2_main/lark_oapi/core/utils/decryptor.py)。
