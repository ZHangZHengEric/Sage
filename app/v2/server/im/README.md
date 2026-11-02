# Server V2 IM：飞书 SDK 接入

飞书接入使用官方 `lark-oapi==1.7.5`：SDK 长连接接收事件，SDK OpenAPI 发送消息。每位 Sage 用户在一级菜单 **IM管理**（`/im`）配置自己的连接并完成本人配对。

## 配置

安装 Server 依赖：

```bash
pip install -e '.[server]'
```

创建连接只需连接名称、本人 Agent、飞书自建应用 **App ID / App Secret**。不填写企业租户 ID、Verification Token、Encrypt Key，不配置公网事件回调或飞书环境变量。网页自动携带当前 Sage 地址，用于生成审批与结果链接；通过 API 创建时可选传 `web_url`：

```json
{
  "name": "我的飞书",
  "agent_id": "<own-agent-id>",
  "config": {
    "app_id": "cli_xxx",
    "app_secret": "<app-secret>",
    "web_url": "http://localhost:19164"
  }
}
```

`web_url` 是用户打开的 Sage Web 地址，可带部署路径前缀；不会被服务端请求或从飞书事件的 Host 推导。没有地址也能创建连接和收发消息，审批通知会提示打开对应 Sage 会话。用户需能在自己的设备上访问该地址。

在飞书开发者后台启用机器人，选择**使用长连接接收事件**，订阅 `im.message.receive_v1`，申请单聊读取权限（如 `im:message.p2p_msg:readonly`）与 `im:message:send_as_bot`，并发布自建应用、设置可用范围。先在 Sage 创建连接并启动客户端，再保存飞书后台的长连接订阅配置。

凭据在创建前通过 SDK 验证，失败不会占用账号；同一 App ID 不能重复认领。连接只能绑定本人 Agent，创建后账号与 Agent 固定。App Secret 加密保存且不回传，不进入浏览器存储或进程参数。

## 加密密钥与升级

服务端首次启动自动生成 `${data_root}/secrets/im-credentials.key`，文件权限 `0600`、目录 `0700`，重启复用；多进程首次启动安全发布同一文件。密钥需要随数据目录备份。

已有连接的密钥丢失、损坏、被替换或凭据解密失败时，服务继续启动，受影响连接显示不可用并停用。不会自动生成新密钥覆盖已有数据；恢复备份后测试凭据并重新启用。不同连接的解密故障互相隔离。

原 Webhook 连接会在启动时迁移为 SDK 配置：保留 App ID、App Secret、本人配对、会话、收发记录和 Run，移除旧租户及回调配置。旧连接未保存 Sage 地址时提示打开会话。历史重复 App ID 连接会停用冲突项，不阻断服务启动。旧 Webhook HTTP 路由已移除，不保留双接入模式。

## 本人配对与操作

1. 创建飞书连接，查看长连接状态。
2. 生成本人配对码，在飞书私聊机器人发送 `/pair <code>`。
3. 收到绑定成功回复后发送文本，复用现有 Sage Agent/Run 链路。

配对码十分钟有效、最多五次尝试，关闭或过期后从前端清除。只受理已配对本人的文本私聊；忽略其他发送人、群聊、机器人消息和非文本消息。SDK 验证的应用与事件中的企业信息须一致，企业标识不由用户手填。

- `/new`：切换新 Sage 会话，旧代次的待发内容失效。
- `/stop`：取消当前任务，包括受理窗口、运行中和等待审批的任务。
- 审批通知进入现有 Sage 登录与审批页面；`cancel` 终止 Run，`deny` 仅拒绝该次调用。

SDK 的长连接存在进程级事件循环，因此每个应用使用隔离接收进程，启停互不影响。凭据只通过私有 stdin 管道传入。父进程退出时，接收进程即使空闲也会退出。每个 Server 实例最多同时保持八个接收进程，其他连接显示“等待连接资源”，释放资源后自动接入；不会无限拉起原配置上限的全部连接。

状态接口返回 `connecting`、`connected`、`reconnecting`、`disconnected`、`capacity`、`disabled` 或 `unavailable`。本人配对状态独立显示。凭据测试通过不等于长连接在线或消息权限已验收。

## 管理 API

管理接口使用 Sage 登录和本人归属校验，不接受管理员代配或 view-as 写入。

| 接口 | 用途 |
| --- | --- |
| `GET /api/im/plugins` | 获取渠道配置与能力 |
| `POST /api/im/connections` | 创建本人连接 |
| `GET /api/im/connections` | 查看本人连接 |
| `GET /api/im/connections/{id}` | 查看本人连接详情，不回传密钥 |
| `PATCH /api/im/connections/{id}` | 按当前 revision 启停 |
| `POST /api/im/connections/{id}/test` | 验证应用凭据 |
| `POST /api/im/connections/{id}/pairings` | 生成本人配对码 |
| `GET /api/im/connections/{id}/status` | 查询长连接与配对状态 |
| `GET /api/im/connections/{id}/deliveries` | 按状态筛选、分页查看投递 |
| `POST /api/im/deliveries/{id}/retries` | 按 revision 重试；unknown 须 `allow_duplicate=true` |
| `DELETE /api/im/deliveries/{id}?revision=...` | 丢弃失败/未知投递 |
| `DELETE /api/im/connections/{id}?revision=...` | 删除连接及收发状态，保留 Sage 会话 |

## 模型最终通知

绑定通知目标的根 Run 获得内置 `im_notify(content)`，模型为 IM 单独编写 1–20000 字符的结果正文。目标用户、连接、私聊与 Run 由服务端绑定，模型不能指定收件人；子 Run 与 Plan 不暴露此工具。

返回 `{"notification_id":123,"status":"prepared"}` 表示已持久化，不代表送达。Run 完成后发送准备的正文；没调用工具时使用公开最终答案兜底。取消/失败发送状态提示，不发送准备的成功文案。审批挂起只投递该 suspension 的通知一次；恢复后最终通知只生成一次。

网页输入框可选择本人的已启用、已配对连接，默认不通知，新会话清空选择。飞书私聊发起的 Run 自动绑定原私聊。外部定时调用复用 Run API：

```json
{
  "session_id": "daily-report",
  "runId": "daily-report-20261102-0900",
  "messages": [{"id": "m1", "role": "user", "content": "整理报告并通知我"}],
  "notification_connection_id": "im_<own-connection-id>"
}
```

登录用户调用 `POST /api/agent`；外部调度器调用 `POST /api/agents/{agent_id}/runs`，使用本人 Agent API key（`a2a:invoke`）与 `SAGE-TENANT-ID: <本人 Sage user_id>`。这是现有外部 Run 身份头，与飞书企业标识无关，不是飞书连接配置。不同计划触发使用不同 `runId`，同次触发重试保留原输入与目标。V2 没有独立 cron 管理模块。

## 持久收发与恢复

官方 SDK 帧处理必须等到 Sage 将事件提交业务数据库后才确认；失败返回失败确认。IPC 单帧有界、ACK 关联事件，长文本不会被默认 64KiB 读取限制截断。入站继续按 event/message ID 去重、同 key 不同内容冲突，每连接最多 1000 项普通待处理输入；满队列仍接受 `/new`、`/stop`。

只有持有数据库连接租约的 worker 启动接收，回调在提交事务中复核 worker 与授权代次，旧进程不能绕过停用或租约变更。Run 受理前冻结 StartRun，重启按原幂等 key 找回同一个 Run，不创建第二个通知 Run。

通知复用 `im_deliveries.run_context` 保存操作性意图，不新增审计表或聊天副本；工具中断通过现有 reconcile 核对 SQL 草稿。审批已失效或来源授权已撤销的 failed/unknown 通知自动失效，避免阻塞后续合法通知。同一活跃 suspension 的去重标记不随七天回执清理丢失。

出站使用官方 SDK 原始 API，并保留固定 UUID，不使用 SDK 高层自动重试。平台明确接受后记为 `platform_accepted`，不代表用户已读；限流/未连接有界退避，发送后超时或进程失联记为 `unknown`，不自动重发。有效 unknown/failed 按目标保序阻塞，须按当前 revision 重试或丢弃；unknown 人工重试可能重复发送，需明确确认。

连接租约 60 秒，正常关闭主动释放，崩溃后过期接管。已接受出站正文即时清空；已完成去重记录保留七天，未解决 failed/unknown 不自动删除。多副本 MySQL/Redis 选主与真实飞书网络需部署验收，不能由本地 SQLite 恢复测试替代。

## 验证

```bash
python -m pytest tests/app/v2/server/im -q
```

测试使用真实 V2 Host、业务仓储、文件 SessionStore、官方 SDK 帧与隔离接收进程，模型及平台网络使用替身；覆盖落库前不 ACK、异常失败 ACK、长文本、父进程退出、双应用独立启停、配对、取消、审批、Run 恢复和 unknown 管理。

真实联调顺序：创建连接 → 飞书后台启用长连接与消息权限 → 本人配对 → 文本回复 → `/new` → `/stop` → 审批与取消 → Server 重启后继续收发。未将本地替身测试声明为真实飞书联调完成。

依据：[官方 Python SDK](https://github.com/larksuite/oapi-sdk-python)、[官方长连接接入](https://open.feishu.cn/document/ukTMukTMukTM/uYDNxYjL2QTM24iN0EjN/event-subscription-configure-)。
