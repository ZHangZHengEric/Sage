# 飞书 IM P0

飞书自建应用通过事件 Webhook 接入 V2 Server。仅处理已配对本人的 `p2p` 文本消息，执行沿用 `RunAdmission`、`RunService(native)`、SessionStore 和现有审批页面。无需启动旧的 `mcp_servers/im_server`。

## 部署配置

安装服务端依赖 `python -m pip install -e '.[server]'`。生产沿用现有 MySQL 与 SessionStore 配置，启动时创建四张缺失的渠道业务表：`im_connections`、`im_conversation_bindings`、`im_inbox`、`im_deliveries`。它们仅存连接、绑定及收发恢复状态，不存第二份聊天历史，不新增审计库。

配置固定的公网地址与一组飞书凭据环境变量，例如：

```dotenv
SAGE_SERVER_PUBLIC_URL=https://sage.example.com
SAGE_IM_FEISHU_PERSONAL_APP_SECRET=replace-me
SAGE_IM_FEISHU_PERSONAL_VERIFICATION_TOKEN=replace-me
SAGE_IM_FEISHU_PERSONAL_ENCRYPT_KEY=replace-me
```

凭据从进程环境或现有 `app/v2/server/.env` 读取，不通过管理接口提交明文。不同机器人使用不同变量名；引用必须以 `SAGE_IM_FEISHU_` 开头。P0 仅管理员可以为一个 Sage 用户配置机器人账号，普通用户只能管理自己的连接、生成配对挑战、查看投递及重试。

`SAGE_SERVER_PUBLIC_URL` 必须为 HTTPS，包含反向代理路径前缀时会原样保留。审批链接使用此配置，不使用外部请求的 Host。此地址需要能打开现有 Sage Web 页面；模型、工具授权和登录继续使用原有配置。

## 创建连接

管理员登录取得现有 Sage Bearer token 后调用 `POST /api/im/connections`，其中 `owner_user_id` 是接入者的 Sage 用户 ID，`agent_id` 必须属于该用户：

```json
{
  "owner_user_id": "user_existing_owner",
  "agent_id": "agent_existing_agent",
  "name": "我的飞书机器人",
  "config": {
    "app_id": "cli_actual_app_id",
    "tenant_key": "actual_tenant_key",
    "app_secret_env": "SAGE_IM_FEISHU_PERSONAL_APP_SECRET",
    "verification_token_env": "SAGE_IM_FEISHU_PERSONAL_VERIFICATION_TOKEN",
    "encrypt_key_env": "SAGE_IM_FEISHU_PERSONAL_ENCRYPT_KEY"
  }
}
```

返回 `data.id`，例如 `im_...`。相同 app/tenant 不能重复认领。P0 Agent 与账号配置在创建后固定；启停使用带 `revision` 的 PATCH，不沿用旧插件页面的全局默认绑定接口。

在飞书开发者后台：

1. 启用自建应用的机器人能力，开放给要配对的本人并发布应用。
2. 为机器人配置接收用户私聊消息及以应用身份发送消息的权限，例如 `im:message.p2p_msg:readonly`、`im:message:send_as_bot`；以应用后台展示的可用权限为准。
3. 选择将事件发送到开发者服务器，配置 Encrypt Key 与 Verification Token，与上述环境变量相同。
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

除 Webhook 使用飞书认证，其余接口均要求 Sage 登录；创建额外要求管理员。

| 接口 | 作用 |
| --- | --- |
| `GET /api/im/plugins` | 飞书插件的配置 Schema 与 P0 能力 |
| `GET /api/im/connections` | 本人连接列表，部署最多 200 个连接 |
| `GET /api/im/connections/{id}` | 本人连接详情，不返回密钥值与配对码 |
| `PATCH /api/im/connections/{id}` | `{"revision": 1, "enabled": false}`，旧版本返回冲突 |
| `GET /api/im/connections/{id}/status` | disabled、awaiting_pairing、webhook_ready；不代表生产消息权限已联调 |
| `POST /api/im/connections/{id}/test` | 验证 tenant token 获取，不发送测试消息 |
| `POST /api/im/connections/{id}/pairings` | 创建或刷新本人配对挑战 |
| `GET /api/im/connections/{id}/deliveries?after=0&limit=50` | 分页读取投递状态与脱敏错误 |
| `DELETE /api/im/connections/{id}?revision=1` | 删除渠道配置与收发状态，保留既有 Sage 会话 |
| `DELETE /api/im/deliveries/{id}?revision=3` | 丢弃已失败/未知投递，解除目标队列阻塞 |
| `POST /api/im/deliveries/{id}/retries` | 重试失败项；需传当前 `revision`；unknown 还须显式传 `{"revision": 3, "allow_duplicate": true}` |

管理 UI 本次沿用 Swagger `/docs` 与现有 Sage 会话/审批页面，没有新增连接配置页面。

## 恢复与投递语义

Webhook 先将有效输入提交业务数据库，再向平台 ACK。后台轮询只做唤醒和领取，普通输入队列满返回可重试错误，不能 ACK 后仅留下一个内存 Task。每连接最多 1000 项待处理输入；`/stop` 与 `/new` 在输入队列满时仍可使用。

入站同时按平台 event ID 和 message ID 去重。同 key 不同内容返回冲突。受理前持久化冻结的 StartRun；若 Run 已接受而 inbox 的 run_id 尚未保存，恢复时按原 key 查找原 Run，不创建第二个 Run，也不读取更新后的 Agent 来替换已冻结命令。

终态与挂起信息从 Sage Session 读取。出站 intent 与 inbox 完成状态在同一业务事务内写入；Run 成功和平台发送成功是两件事。SUSPENDED 保留运行关联，审批后继续投影原 Run；重启不丢失挂起关联。

平台实例通过现有 ExtensionHost 加载命名 `im.channel-factory:feishu`。跨连接最多八路并发，后台以数据库连接租约领取工作，过期领取者不能确认投递。发送按外部会话保序、分片 UUID 固定；响应明确接受后记为 `platform_accepted`，不代表用户已读。临时限流/尚未连接有界退避，最多自动尝试五次；发送后超时、不可解析回执或 worker 在发送中丢失记为 `unknown`，不自动重发。unknown/failed 会阻挡同目标后续发送，须检查后按当前 revision 重试或丢弃；旧版本操作返回冲突。

飞书消息请求携带稳定 `uuid` 作为平台去重辅助；不依赖平台去重窗口来保证任意时间的 exactly-once。unknown 的人工重试可能重复发送，因此接口要求显式接受此风险。inbox 去重记录保留七天，正文与冻结请求在任务完成后即清理；已接受出站载荷也即时清空，已完成记录七天后清理。未解决的 unknown/failed 不自动删除。

连接租约有效期为 60 秒。正常关闭会释放本 worker 的租约；进程崩溃后由下一 worker 在租约到期后接管。P0 的数据库领取机制在本地 SQLite 仓储测试中验证。多副本 MySQL/Redis 的故障选主与真实平台网络场景需要部署验收，不能用本地恢复测试替代。

## 本地验证与真实联调

```bash
python -m pytest tests/app/v2/server/im -q
```

测试使用实际 V2 Host、SQLite 业务仓储、文件 SessionStore 和 scripted model；仅飞书网络传输用 httpx MockTransport/发送替身。包含验签解密、伪造/过期拒绝、私聊与身份隔离、重复回调、重置、运行前/运行中取消、审批恢复与撤权、冻结受理、全 Host 重启和不确定发送恢复。

2026-10-28 本地验证记录：

- IM 专项：30 项通过，包括队列满时仍可取消任务。
- Server 非 live 回归：873 项通过、1 项跳过、1 项失败、1 项 teardown 错误。图片验收的沙箱错误与下载测试 monkeypatch 的 SessionStore 方法缺失，均在未修改的 HEAD 复现。
- 完整 V2 非 live 回归：5083 项通过、59 项跳过，另有 125 项失败与 9 项错误，未全绿。失败包含本机禁止进程资源监控/本地端口监听、缺失 pandas/filelock 与评测数据，以及既有 RSI/SessionStore 用例问题；已在 HEAD 抽查复现非环境断言，不代表逐项完成全量基线核验。
- 本次 Python 文件的 Ruff、diff 空白检查与架构检查通过。文档检查仍报告 HEAD 已有的 RSI 翻译结构和缺少对应文档问题。

真实联调需配置实际应用、回调域名及服务端凭据，再依次验证：challenge → 本人配对 → 文本回复 → `/new` → `/stop` → 需要审批的任务 → Sage 登录批准 → 服务端重启后继续收发。当前实现没有把 mock 结果声明为飞书生产链路已验收。

协议依据：[飞书事件接收](https://open.feishu.cn/document/server-docs/event-subscription-guide/event-subscription-configure-/encrypt-key-encryption-configuration-case)、[接收消息事件](https://open.feishu.cn/document/server-docs/im-v1/message/events/receive)、[发送消息](https://open.feishu.cn/document/server-docs/im-v1/message/create)、[官方 Python SDK 验签](https://github.com/larksuite/oapi-sdk-python/blob/v2_main/lark_oapi/event/dispatcher_handler.py)、[官方解密实现](https://github.com/larksuite/oapi-sdk-python/blob/v2_main/lark_oapi/core/utils/decryptor.py)。
