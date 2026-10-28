---
layout: default
title: Server V2 IM 插件设计
parent: 架构
nav_order: 30
nav_exclude: true
lang: zh
ref: v2-architecture-SERVER_V2_IM_PLUGIN_DESIGN
---

{% include lang_switcher.html %}

# Sage Server V2 IM 插件功能设计

状态：飞书 P0 已实现，本地验证范围与接入方式见 [IM 接入说明](../../../app/v2/server/im/README.md)；其余平台、群聊和扩展能力仍为设计提案。调研日期：2026-10-22。

建议在 ServerHost 中增加统一 IM Gateway，通过现有 ExtensionRegistration / ExtensionHost 加载平台适配器；所有 IM 对话进入现有 RunAdmission、RunService 和 Sage Session。连接、路由、投递是服务端产品能力，Agent loop、工具执行、审批状态和对话历史继续由现有框架管理。

本文将 IM 理解为飞书、钉钉、企业微信、Telegram、Slack、Discord 等即时通信渠道。研究覆盖代表性设计路线，不能声称穷尽 GitHub。外部源码来自官方仓库与文档，链接指向读取时的 main/master；抓取时间不同，未锁定同一 commit，也未运行外部项目。实施时需固定源码和依赖版本。下文第二节是观察事实，后续方案是针对 Sage 的设计建议。

## 1. Sage 当前可复用的基础

| 当前源码 | 已有职责 | IM 的接入方式 |
| --- | --- | --- |
| `app/v2/server/bootstrap.py` | ServerHost 装配、启动、关闭共享资源 | 加载 IM provider、启动 Gateway，关闭时先停止渠道接收 |
| `conversations/admission.py` | 用户与 Session 归属、Agent 选择、包与 Skill 快照、执行授权 | 归一消息通过授权后调用 `RunAdmission.prepare()` |
| `conversations/runs.py` | `start_detached_run()`、取消、steer、交互恢复 | 通过 `native` interface 后台执行，IM 请求断开不影响 Run |
| `conversations/orm.py` | `threads` 会话索引、不可变 `session_bindings` 归属 | 继续保存 Sage 会话和归属；外部地址另作绑定 |
| `conversations/a2a/service.py` | 从 canonical Run 事件投影协议视图 | IM 同样投影现有事件，不建第二份聊天事实 |
| `runtime/sdk_plugins.py`、`sagents/v2/runtime/extensions/` | 描述符、工厂、依赖、scope、启动回滚与关闭 | 平台适配器采用同一扩展契约 |
| `config/plugins.py` | 管理员插件默认选择、revision 校验、重启生效 | 保持现有语义；每个 IM 账号配置使用专属业务管理入口 |
| `runtime/policy.py`、`identity/context.py` | 冻结执行授权、实时收紧权限、用户上下文 | 扩展受信任入口授权，不能直接给外部 sender 套用 `for_user()` 全权限 |
| `config/settings.py`、`config/manifest.py` | 本地与 Redis 分布式配置及保证校验 | 渠道连接选主和投递 claim 必须匹配实际部署模式 |

SDK 装配器会补入 native protocol adapter，`SAgentApplication.run_interface()` 最终进入统一原生执行入口。因此无须为每种平台增加一种 Agent loop，也无须先把飞书转 AG-UI 再解析回来。

旧的 `mcp_servers/im_server/` 已有 provider、会话管理和发送工具，但 `agent_client.py` 仍引用 `sagents.v1.context.messages`，`db.py` 使用独立 SQLite，配置还有用户/Agent 文件等来源。平台 SDK 调用可作为参考，不能直接作为 V2 Server 的运行与身份层。当前提案不删除旧目录；后续若迁移，按依赖清单单独处理。

源码优先于 README 中的部署描述：当前设置已允许 Redis/MySQL SessionStore 与 Redis distributed scheduler 的组合，不能一概称 Server 只支持单进程；也不能据此认为新增 IM 监听天然具备分布式安全性。

## 3. 用户可见的功能与领域对象

建议提供「IM 接入」能力，用户添加一个连接实例，再绑定本人拥有的 Agent。一个平台可以有多个机器人账号，一个账号可按会话规则路由不同 Agent；同一个 Agent 可以接受多个平台入口。

| 对象 | 含义 | 不变量 |
| --- | --- | --- |
| ChannelPlugin | 飞书、Telegram 等平台的代码实现和能力描述 | 不持有某个任意用户的全局 current_chat、凭据或 RequestContext |
| Connection | 一组机器人账号、所属 Sage 用户、外部组织、配置和凭据引用 | connection_id 稳定；更换为另一个外部账号必须创建新连接 |
| RouteRule | 连接内指定 DM/群/话题到 Agent 的规则 | 只能指向授权 Agent；同优先级冲突拒绝保存；无匹配不跨用户找默认 Agent |
| ConversationBinding | 外部会话 scope 到一个 Sage session 的映射 | Session 的 owner 和 Agent 不变；`/new` 增加 generation 并切到新 Session |
| InboundEvent | 验证后的消息、命令或交互回调 | 外部身份、事件 ID 与内容均有明确来源 |
| Destination | 连接、组织、外部会话、话题及必要 reply 地址 | 独立于入站对象存活；主动发送必须有明确授权目标 |
| Delivery | 一次对外发送或编辑的业务意图及回执 | 与 Agent Run 成败分开；入队成功不等于平台接受 |

建议交互包括：连接测试、启停、连接状态与最近错误、Agent 路由、私聊与群聊规则、会话重置、取消、审批入口、长任务结果通知、文件发送，以及失败投递的受控重试。

## 4. 模块安排与插件契约

```text
IM 平台
  ⇅ Webhook / WebSocket / polling
Channel Adapter 插件
  ↓ 验签、平台协议解析、归一事件
IM Gateway
  ↓ 身份解析 → 触发/授权 → 会话绑定 → durable inbox
RunAdmission → RunService(native) → 现有 Sage Runtime / Session
  ↓ canonical RuntimeEvent / Interaction / public artifact
IM 输出投影 → durable delivery → Channel Adapter → IM 平台
```

建议目录：

```text
app/v2/server/im/
  contracts.py       插件、消息、目的地、能力与投递结果
  service.py         配置、启停、状态等业务操作
  gateway.py         有界接收、授权、会话路由与受理协调
  connections.py     账号生命周期、generation、重连与连接独占
  routing.py         确定性路由和 scope 计算
  projection.py      canonical 事件转可见回复与交互
  delivery.py        顺序、限流、分片、重试与回执
  recovery.py        入站、事件投影和出站恢复
  repository.py     最小渠道业务存储
  orm.py
  plugins/
    feishu/
    telegram/
app/v2/server/routers/im.py
```

这些是实现中的职责划分，第一版不要求每一项成为可替换插件。真正的平台差异放 Channel Adapter，共享身份和 Run 状态不交给插件重定义。

插件核心接口示意如下；类型名是提案，不是仓库已有接口：

```python
class ChannelFactory(Protocol):
    def describe(self) -> ChannelDescriptor: ...
    async def create(self, config, *, secrets, transport) -> ChannelConnection: ...

class ChannelConnection(Protocol):
    async def start(self, ingress: IngressPort) -> None: ...
    async def deliver(self, operation: DeliveryOperation) -> DeliveryReceipt: ...
    async def stop(self) -> None: ...

class IngressPort(Protocol):
    async def accept(self, event: InboundEvent) -> IngressReceipt: ...
```

`start()` 在连接可用或明确失败时返回，持续监听任务由连接宿主管理；不能无限阻塞整个 Server 启动。`stop()` 幂等，须取消监听、解绑回调、释放客户端和文件句柄。`IngressPort` 绑定 connection_id 与 generation，插件不能通过事件字段切换到别人的账号。

Webhook、编辑、typing、原生流式、媒体上传、回执查询通过能力声明与可选接口提供。统一 Webhook 路由把原始请求交给对应连接的 webhook handler 验签/解密；handler 仅能经绑定的 IngressPort 受理事件。挑战请求按平台规则直接答复。SDK 在非 asyncio 线程回调时，通过受控线程安全桥接提交事件，不直接跨线程操作队列/数据库。

平台能力包括 `receives_messages`、`sends_replies`、`proactive_send`、`edit_message`、`native_streaming`、`interactive_actions`、`upload_file`、`query_receipt`；长度、文件大小、支持 MIME 与目标限制也是契约。运行模式、平台权限可能进一步收紧能力，未知能力默认关闭。

### 4.1 复用现有 ExtensionHost

平台工厂注册为 `ExtensionRegistration`，例如插件 ID `com.sage.im.feishu`，提供命名能力 `im.channel-factory:feishu`；Telegram 提供相同能力的另一个名称。能力协议版本使用本次新接口的版本，例如 `1`，与 SDK 描述符自身版本分开；相关 requirement 显式填写版本范围，避免使用默认的 `>=2,<3`。

ServerHost 从同一组受信任注册中，为 IM 工厂显式执行 `ExtensionHost.plan()` / `open_scope()`。复用依赖校验、参数 Schema、availability、owned/borrowed 和回滚机制。工厂为 process 生命周期；Connection 是工厂创建、由 Gateway 管理的账号资源，每个实例有独立凭据、限流和 generation。

仅往 runtime.capabilities 填一个新键不足以让当前 Server 自动消费它，必须增加宿主装配代码。工厂不依赖尚未创建的 ConversationService，后者就绪后才启动具体连接，避免生命周期依赖环。扩展 scope 关闭前 Gateway 先关闭全部 Connection。

普通 Agent Package 不能选择 IM 监听工厂、携带机器人密钥或注册 HTTP 路由。`AGENT_DEFAULTS` 不增加 IM 配置。插件代码的安装与升级由部署管理，第一版只允许宿主明确安装和注册的受信任包；页面添加连接不触发 pip 安装或任意 import。

### 4.2 消息归一

`InboundEvent` 至少包含：绑定连接、外部组织、event_id、message_id、事件类型、发生时间、sender、conversation、topic/thread、reply_to、mentions、正文和附件引用。非可信平台扩展字段放受限 metadata。

消息正文直接投影为 Sage 已有 `TextBlock/ImageBlock/AudioBlock/FileBlock/ResourceRefBlock` 等。mention、引用、目标地址属于渠道上下文，不为它们再造一套模型消息格式。外部正文始终是 user 输入，不能把平台 payload 中的 role、system、工具执行结果或 Sage user_id 当可信指令。

附件通过平台授权下载到既有受控附件/工作区流程，校验大小、MIME、路径和访问归属；避免让模型直接访问含临时凭据的平台 URL。RunConfig 只保存必要来源和地址快照，不保存机器人密钥与短期下载 token。

## 5. 身份、会话和 Agent 路由

### 5.1 身份必须先于 Agent 受理

需要分别识别连接 owner、外部组织、机器人账号、外部 sender、Sage principal 和目标 Agent。Webhook URL 中的 connection_id 不是凭据；外部昵称、群管理员或 payload 自报 user_id 都不授予 Sage 权限。

第一版默认个人连接：在 Sage 已登录管理界面发起短时配对，验证回调 sender 与一次性配对码后绑定本人外部身份，仅绑定身份可私聊调用。未知 sender 默认拒绝。配对码单次消费、有次数和时限限制，不能凭平台昵称认领账号。

团队连接作为后续明确模式：每位成员经已验证身份映射到自己的 Sage 用户，或整群绑定专用 Sage 用户和专用 Agent。连接 owner 是管理员不意味着所有群成员可使用其私人 Agent、Shell、文件和记忆。

实际权限取 Server、Sage 用户、Agent、IM 入口授权及当前授权的交集。现有 `RunAdmission` 与 `live_execution_policy` 只认识既有用户/Agent/key 等来源，必须增加受信任入口授权引用与实时校验；不能只在 Gateway 检查一次，也不能把 im scope 伪装成 A2A key。范围包含工具/Skill grant、工作区访问和审批资格，排队、恢复、工具执行及最终投递时权限撤销仍须生效。

### 5.2 会话键

建议逻辑键：

```text
tenant + sage_principal + connection_id + external_org
+ conversation_kind + external_chat + optional_topic
+ isolation_scope + agent_id + generation
```

将规范化元组做带版本的稳定摘要作索引键，外部大小写按平台语义保留。内部 Session 使用服务端生成 ID，建立唯一映射；不能直接用外部 chat_id 作为 Sage session_id。

| 场景 | 默认 scope |
| --- | --- |
| 本人 DM | 连接 + 已验证 sender |
| 群内个人对话 | 群 + sender + 可选话题；必须具备对应主体授权 |
| 共享群对话 | 群 + 可选话题，显式启用，使用群专用主体与 Agent |
| 平台原生讨论串 | 父会话 + topic/thread ID |
| 跨平台合并 | 第一版关闭；后续只能显式绑定且核实双方身份 |

NoneBot 的 OneBot 适配器[群 session](https://github.com/nonebot/adapter-onebot/blob/master/nonebot/adapters/onebot/v11/event.py)包含群与 sender，说明 IM 平台的 session 含义并不统一，必须由 Sage 明确隔离语义。

Sage 的工作区与长期记忆也关联用户/Agent，仅分 Session 不能隔离同一主体的私有资源。群内按人模式也不能保证回答只有本人可见，因为群回复本身对群成员可见；涉及个人信息应改为已授权 DM 投递或 Sage 私有页面。

路由使用确定性规则：显式话题规则 → 会话规则 → 连接默认 Agent；每条规则须校验 Agent owner/授权，同优先级歧义拒绝。Session 首次受理后钉住 Agent。修改默认 Agent 只影响新绑定；`/agent` 切换创建新 Session，不改旧 Session 归属。`/new` 更新 generation；旧 Run 的结果不能读取新会话的“最后聊天地址”后发送。

## 6. 入站受理、并发和运行恢复

推荐处理链：

1. 连接检查请求大小、验签/解密、防重放，解析事件；只记录验证成功的正常化业务输入。平台挑战和忽略事件遵循相应 ACK 规则。
2. Gateway 核对连接 generation、身份、触发和路由。默认忽略机器人自身/回声、无授权 sender 和不支持的编辑/撤回事件；群聊默认需 @或命令。
3. 在业务数据库提交 inbox，保存稳定 dedupe key、内容摘要、已解析主体、已选 Agent/scope、目的地快照和配置 revision；重复事件复用已有回执，内容冲突拒绝。提交成功后才向平台确认受理。冻结实际路由结果，避免配置更新后只能找到一个已失效的路由引用。
4. Worker 复查实时授权，准备并持久化冻结的 StartRun 请求；随后调用 RunAdmission / RunService。Run 的 idempotency key 由连接、消息 ID 和受支持事件版本确定。
5. 标记 inbox 已关联 run_id，继续观察该 Run 的 canonical 事件。

平台 event_id 用于回调去重，message_id 用于消息身份；若同一消息会触发不同事件，需要明确事件类型与版本，不能让普通重试再创建 Run。第一版不把编辑/撤回自动转为新输入。

inbox 与 SessionStore 可能不是同一事务，尤其 Redis SessionStore 不可能与 MySQL inbox 自动原子提交。恢复时先按稳定 key 找已受理 StartRun，存在则复用原命令/Run；没有才提交持久化冻结请求。禁止重试时读取最新 Agent 包重造同一个 key。对“Run 已接受、inbox 尚未更新”的崩溃窗口必须有测试。

内存队列仅作为唤醒机制，容量有界；可靠任务以 inbox 为准。容量满时已持久化项留待领取，尚未持久化时按平台规则返回可重试失败。不要先 ACK 再创建 asyncio task 就声称可靠。

同 Session 复用已有 SERIAL 运行规则，跨 Session 复用现有每用户/全局额度。第一版追加消息排队；`/stop` 走既有 cancel，审批回调优先按 interaction 处理。steering 可后续明确启用，不能随意把任何新消息投给当前 Run。

## 7. 回复、流式、审批和主动发送

### 7.1 回复投影与可见性

IM 输出从 canonical RuntimeEvent 和 RunResult 投影。只发送用户可见的 assistant 正文、经授权 artifact、交互请求与可公开错误；不输出 reasoning、原始工具参数、诊断日志或其他内部内容。

实时 delta 是可丢失预览；最终内容、挂起交互和终态以持久事件为准。按平台能力使用原生流式、合并编辑一条消息或终态发送；节流、限长、Markdown 转换和跨文本/附件顺序由共享 delivery 编排，平台编码在适配器内实现。第一版最终回复即可，流式不作为接入每个平台的前置条件。

### 7.2 审批与继续运行

将 Sage interaction 呈现为卡片或 Sage 页面链接。回调先验平台签名，再验证真实操作人及审批授权；令牌绑定 connection、chat/topic、run_id、interaction_id、所需 revisions、到期时间和一次性标识。

最终决定通过既有 ReplyInteraction / ResumeRun 和 CAS 生效，一次性语义优先复用 interaction 状态与幂等命令，不另建审批副本。重复点击、旧卡片、过期授权均不能推进 Run。群管理员身份不自动获得审批权。卡片出现在群里不代表群内所有人都可批准；无法可靠识别操作者的平台只发送要求 Sage 登录的链接。

### 7.3 主动消息和 MCP

普通对话回复由宿主投影发送，无须模型调用 IM 工具。长任务、计划任务与显式主动发送共用 Delivery 服务，使用授权 Destination 快照，不使用全局 current_chat 或“最近联系人”。Webhook 机器人仅支持出站时，可声明 `receives_messages=false`；回复窗口受限时也不能宣称可任意主动发送。

后续可提供可选 `im_send` 工具或 MCP 包装。工具接收受控 destination_ref，由服务器解析并核对 owner、Agent、允许目标及文件权限；模型不能提交机器人 token 或任意连接 ID 获得跨账号发送权。工具只能准确报告 queued/platform_accepted 等阶段，不能将入队称为送达。自动回复与显式 send 分别是 delivery purpose，不能因为调用过任意 IM 工具就全局吞掉最终回复。

### 7.4 出站状态与重试

```text
pending → sending → platform_accepted
                  ↘ retry_wait → pending
                  ↘ failed
                  ↘ unknown → 查询/幂等重放协调 → platform_accepted / pending / unknown
```

`platform_accepted` 仅表示平台接受，除非有明确回执，不称为用户收到或已读。分片各有稳定 part_id 与回执，已确认片段不重发；未知片段不能当作未发送。

对账号和目的地实施限流，同一外部会话/话题跨文本与媒体保序，不按 Sage sender 隔离的 Session 各自乱序发送。临时限流尊重 retry-after，网络故障有限退避；无权限、目标失效等永久错误停止。请求已发出后超时可能是 unknown，平台支持幂等键/回执查询时协调，否则保留 unknown 并向管理者显示处理动作，不能盲目自动重发。

进程崩溃后领取租约过期的 sending 项同样不能直接回 pending；仅当能够证明尚未发起平台请求时才安全重试，否则先转 unknown，查询回执或使用平台幂等机制协调。

此方案实现持久受理、Run 幂等、稳定出站意图及有界恢复；不承诺平台不支持的端到端 exactly-once。

## 8. 必要业务存储

不为审计单独扩展业务存储。现有 Session/事件、threads/session_bindings、审批交互继续是各自权威；日志、指标和 Trace 沿用 StructuredLogger 与 observability.provider。

建议新增以下四类渠道业务记录，物理建表在实现时确认：

| 记录 | 必要业务用途 | 最小内容 |
| --- | --- | --- |
| im_connections | 配置多个机器人与访问规则 | owner、plugin、外部账号身份、secret_ref、Schema 配置、身份/路由规则、revision、enabled |
| im_conversation_bindings | 重启后定位会话、支持 `/new` | scope key、主体、Agent、session_id、generation、授权目的地引用 |
| im_inbox | ACK 后恢复输入、避免重复执行、恢复事件投影 | dedupe key、短期输入、冻结命令引用/快照、run_id、状态、投影 cursor、领取租约 |
| im_deliveries | 恢复发送、分片和未知回执 | 稳定 source/purpose key、Destination 快照、必要发送载荷/引用、part、状态、重试时间、回执、领取租约 |

不复制完整聊天历史，不新增 im_messages、im_runs、im_approvals 或审计专用表。inbox 的输入与冻结请求是执行前暂存，受理后按恢复需求释放；投递载荷是待发送状态，不作为第二份历史。若复用现有库存已能完整满足某项契约，应删去对应重复记录，而不是双写。

投影以 inbox 上的 run_id/cursor 为恢复入口，先回放再订阅或使用无缝 cursor 订阅。一次事务内插入唯一出站意图并推进 cursor；并发或崩溃重放由 source key 去重。不能只依赖进程内 on_finished 回调，否则 Run 完成与出站入队之间可能丢回复。所有从 SessionStore 读取都经授权；撤销、删除、失效的 Run/目标必须有显式停止处理规则。

P0 已采用用户自助配置：owner 仅来自当前登录身份，平台凭据通过页面提交，使用服务端首次启动自动生成并持久化的独立主密钥（`<data_root>/secrets/im-credentials.key`，重启复用）加密后存入现有连接记录。值不进入 Run、事件、日志或前端回显，禁止借 JWT secret 充当密钥，也不为此临时搭一套独立密钥平台。密钥丢失或损坏不阻止 Server 启动；仅停用无法解密的连接，保留原密文并在 IM 管理中显示不可用，恢复备份后可测试并重新启用。

配置与必要绑定保留到用户删除；inbox 输入、已完成回执与失败载荷设业务恢复期和清理策略，默认不无限增长。去重键和原始 Session/Run 对应关系至少保留到平台最大重试/重放窗口结束，正文可更早清理；若无法约束平台重放窗口，就不能宣称清理后仍永久防重。配置不因审计需求保留历史副本。删除连接先停止接收并禁用投递，清理临时文件及渠道记录；既有 Sage 会话按现有删除语义单独处理，不能因删一个连接误删整个 Agent 工作区。

SUSPENDED Run 仍需保留投影关联，审批后从原 cursor 继续；不能把一次挂起当作最终结束而停止后续投递。`/new` 后第一版停止旧 generation 尚未发出的普通回复，旧任务结果仍可在 Sage 原会话查看；明确订阅的主动通知使用自己的目标与授权，不随“最近聊天”变化。

## 9. 生命周期与部署

Server 启动顺序为：数据库/SessionStore 与运行链路就绪 → 加载渠道配置与 factory → 恢复 inbox/出站投影 → 领取连接所有权 → 启动监听和投递。关闭时先禁止新输入，再停止连接监听，有限等待持久任务交接，最后关闭 IM scope 与 Sage 共享依赖。

连接状态为 disabled、starting、connected、reconnecting、error、stopping。配置使用 revision CAS；普通实例改动只重连该连接，插件代码安装/升级仍随部署重启。切换 generation 后拒绝旧监听提交、旧状态回写和旧领取者确认。重连有退避与上限，失效凭据进入 error，不能每秒无限尝试。

部署默认采用与当前 Server 模式相符的连接宿主。若允许多进程/多副本，WebSocket/polling 连接必须独占领取；inbox/投递领取也要持久租约和 fencing。Run scheduler 的分布式支持不能替代渠道选主。Webhook 可经负载均衡进入，数据库去重和有界 claim 负责协调。

fencing 只能拦住过期 worker 的本地写入，不能撤回已经发给平台的 HTTP 请求；外部不确定结果仍按 unknown 协调。第一版可限制单 IM listener 宿主，同时明确部署限制；不应默认新建另一套消息中间件。

## 10. HTTP 与管理页面

接口均为提案，沿用 Sage 现有字段风格、JSON 错误和 request_id，不修改现有插件保存接口的 default-only 语义。

| 方法与路径 | 用途 |
| --- | --- |
| `GET /api/im/plugins` | 平台实现、可用依赖、配置 Schema 和能力 |
| `GET/POST /api/im/connections` | 本人连接的分页列表与创建 |
| `GET/PATCH/DELETE /api/im/connections/{id}` | 详情、带 revision 更新与删除 |
| `GET /api/im/connections/{id}/status` | 实际连接状态、当前/期望 revision、脱敏错误 |
| `POST /api/im/connections/{id}/test` | 校验配置与平台凭据；默认不向联系人发消息 |
| `POST /api/im/connections/{id}/pairings` | 创建本人身份配对挑战 |
| `POST /api/im/connections/{id}/conversation-resets` | 经过归属校验后生成新 Session |
| `GET /api/im/connections/{id}/deliveries` | 有界分页读取失败/未知投递等业务状态 |
| `POST /api/im/deliveries/{id}/retries` | 带 revision 的受控重试；unknown 须明确重复风险 |
| `/api/im/webhooks/{id}` | 由平台插件按方法处理挑战、消息与卡片回调 |

管理接口使用 Sage 登录鉴权与 owner 检查，Webhook 使用平台认证；两者不能混用。创建/更新校验 typed schema、Agent 归属、外部账号重复认领与当前凭据权限，返回统一可区分的配置错误、认证错误、冲突和可重试繁忙错误。列表游标和过滤参考现有 ThreadPage。

页面采用独立一级菜单「IM管理」（`/im`），只设置标题，不主动添加副标题说明。列表显示名称、平台、Agent/路由、状态、操作；编辑连接时显示平台对应字段、身份规则、会话策略、必要权限和凭据引用。只有会影响操作的权限或失败信息才在相应控件附近说明，不用实现细节填充页面。

插件目录与连接实例分开展示：一个飞书插件可对应多个连接。测试成功只表示凭据/接口测试通过，不保证生产消息权限、群聊可见性和完整端到端流程都正确。

## 11. 实施分期与验收

| 阶段 | 交付范围 | 验收重点 |
| --- | --- | --- |
| P0 契约与首个平台 | Gateway、ExtensionHost 工厂、个人身份配对、单 Agent 路由、文本私聊、最终回复、`/new`、`/stop`、inbox/outbox 与恢复、审批页面链接 | 相同消息只受理一次；Run 可在断连后完成；重启不丢已确认输入和待投递结果；未知身份拒绝 |
| P1 第二个平台与群 | 以第二种传输验证接口、显式群规则/专用主体、媒体、节流编辑、真实操作人可验证的审批卡片 | 新平台不改 Gateway/Run loop；多账号不串会话；群无法读取个人工作区或记忆 |
| P2 扩展与主动任务 | 第三方受信任包分发、受控 im_send/MCP、计划任务目的地、确有需要时分布式连接领取 | 工具/计划任务共用投递；撤权后不能发送；领取过期和配置重载不产生双监听/重复确认 |

候选首个平台为飞书，候选第二个平台为 Telegram，用长连接/Webhook/polling 差异检验接口；这是实施顺序建议，最终按实际用户渠道确定，不预设平台 SDK 或企业版能力。群聊、卡片和原生流式均以选定接入模式的实际能力为准。

必须覆盖的集成场景：

- 同平台两个账号、不同外部组织相同 chat ID、两用户相同 sender ID 不发生交叉授权。
- 重复回调、同 key 不同 payload、重置会话与改 Agent 并发，不能重复执行或覆写旧归属。
- ACK 前后、Run 接受前后、终态投影前后、平台接受后确认前分别注入崩溃，验证恢复和 unknown。
- 两条输入排队、工具执行、审批等待期间撤销身份或连接，权限实时收紧。
- 重复审批、过期卡片、转发卡片、错误操作者和旧 revision 都不能推进执行。
- 同目标文本/文件顺序、长文本分片部分成功、限流、永久失败、不支持主动发送窗口等实际降级。
- 连接配置重载/删除、旧 generation 回调、队列背压、shutdown、临时附件清理与媒体归属。

验证分为纯契约测试、真实数据库/SessionStore 恢复测试、平台 sandbox bot 端到端测试；本提案没有执行这些测试，也没有把源码调研当成平台联调证据。
