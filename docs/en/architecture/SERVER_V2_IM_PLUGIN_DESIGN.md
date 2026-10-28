---
layout: default
title: Server V2 IM Plugin Design
parent: Architecture
nav_order: 30
nav_exclude: true
lang: en
ref: v2-architecture-SERVER_V2_IM_PLUGIN_DESIGN
---

{% include lang_switcher.html %}

# Sage Server V2 IM Plugin Design

Status: Feishu P0 is implemented; see the [IM setup guide](../../../app/v2/server/im/README.md) for local validation and setup. Other platforms, groups, and extensions remain proposals. Research date: 2026-10-22.

Add a shared IM Gateway to ServerHost and load platform adapters through existing ExtensionRegistration / ExtensionHost contracts. All conversations enter existing RunAdmission, RunService, and Sage Sessions. Connections, routing, and delivery are server product capabilities; Agent loops, tools, approval state, and history remain owned by the existing framework.

IM here means channels such as Feishu, DingTalk, WeCom, Telegram, Slack, and Discord. Research covers representative approaches, not all of GitHub. External source and documentation were read from official repositories at main/master at different times, without a common pinned commit or executing those projects. Implementation must pin source/dependencies. The original research separated observations from Sage-specific recommendations; this retained proposal contains the recommendations after removal of the comparison section.

## 1. Existing Sage foundations

| Current source | Existing responsibility | IM integration |
| --- | --- | --- |
| `app/v2/server/bootstrap.py` | ServerHost assembly and shared-resource lifecycle | Load providers/Gateway; stop channel reception first on shutdown |
| `conversations/admission.py` | User/Session ownership, Agent selection, package/Skill snapshots, authorization | Authorize normalized input before `RunAdmission.prepare()` |
| `conversations/runs.py` | Detached runs, cancel, steer, interaction recovery | Run through `native`; an IM connection closing does not stop execution |
| `conversations/orm.py` | `threads` index and immutable `session_bindings` | Preserve Sage ownership; bind external addresses separately |
| `conversations/a2a/service.py` | Protocol projection from canonical Run events | Project the same facts, without duplicate chat history |
| `runtime/sdk_plugins.py`, `sagents/v2/runtime/extensions/` | Descriptors, factories, dependencies, scopes, rollback, shutdown | Reuse the same extension contract |
| `config/plugins.py` | Admin defaults, revisions, restart activation | Keep existing semantics; manage individual IM accounts separately |
| `runtime/policy.py`, `identity/context.py` | Frozen authorization, live tightening, user context | Add trusted ingress grants; never grant external senders unrestricted `for_user()` context |
| `config/settings.py`, `config/manifest.py` | Local/Redis deployment guarantees | Match listener ownership and delivery claims to deployment mode |

SDK assembly adds the native adapter, and `SAgentApplication.run_interface()` enters unified native execution. No platform-specific Agent loop or Feishu-to-AG-UI round trip is required.

Legacy `mcp_servers/im_server/` contains providers, sessions, and sending tools, but its client still imports `sagents.v1.context.messages`, its database is separate SQLite, and configuration includes user/Agent files. Platform SDK calls are references, not a ready V2 runtime/identity layer. This proposal does not delete that directory; any migration needs a separate dependency inventory.

Source takes precedence over README deployment descriptions. Settings already allow Redis/MySQL SessionStore with the Redis distributed scheduler, so Server is not universally single-process. That does not make new IM listeners automatically safe across replicas.

## 3. User-visible capabilities and domain objects

Provide **IM integration**, where users add connections and bind authorized Agents. A platform can have multiple bot accounts, an account can route conversations to different Agents, and an Agent can accept several platforms.

| Object | Meaning | Invariant |
| --- | --- | --- |
| ChannelPlugin | Platform implementation and capability description | No global per-user current chat, credentials, or RequestContext |
| Connection | Bot account, Sage owner, organization, configuration, secret reference | Stable ID; replacing the external account creates a new connection |
| RouteRule | DM/group/topic routing within a connection | Authorized Agents only; reject equal-priority conflicts; no cross-user fallback |
| ConversationBinding | External scope mapped to a Sage Session | Immutable owner/Agent; `/new` advances generation and creates a Session |
| InboundEvent | Verified message, command, or interaction | Explicit identity, event-ID, and content provenance |
| Destination | Connection, organization, chat/topic, necessary reply address | Outlives inbound objects; proactive sending needs an authorized target |
| Delivery | Outbound send/edit intent and receipt | Separate from Run success; queued is not platform-accepted |

Include connection tests, start/stop/status/errors, routing, DM/group rules, resets, cancellation, approval entry points, long-task notifications, files, and controlled failed-delivery retry.

## 4. Modules and plugin contracts

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

Suggested module layout:

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

These responsibilities need not each become replaceable plugins in the first version. Platform differences belong in adapters; shared identity and Run state must not be redefined by them.

The minimal channel protocols separate account construction, delivery, and durable admission:

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

These type names are proposals, not existing repository APIs. `start()` returns when connected or explicitly failed; the connection host owns continuous listeners, so startup cannot block forever. `stop()` is idempotent and cancels listeners, unbinds callbacks, and releases clients/file handles. IngressPort is bound to connection ID and generation; event fields cannot select another account.

Webhook, editing, typing, streaming, uploads, and receipt lookup use declared capabilities and optional interfaces. Shared webhook routing passes the raw request to the connection handler for verification/decryption; the handler admits only through its bound IngressPort. Challenges follow platform rules. Non-asyncio SDK callbacks use a controlled thread-safe bridge rather than directly accessing queues or databases across threads.

Capabilities include `receives_messages`, `sends_replies`, `proactive_send`, `edit_message`, `native_streaming`, `interactive_actions`, `upload_file`, and `query_receipt`, with text/file limits, MIME support, and destination restrictions. Deployment mode and platform permissions can narrow them; unknown capabilities default off.

### 4.1 Reuse ExtensionHost

Capabilities should declare receiving, final replies, editing, native streaming, attachments, interactive cards, thread/group support, and proactive sending. Unsupported features need explicit fallback; they cannot all be inferred from one platform name. Connections should be disabled by default.

Register factories as `ExtensionRegistration`, such as `com.sage.im.feishu` with named capability `im.channel-factory:feishu`; Telegram provides another name of the same capability. Use an explicit protocol version, such as `1`, distinct from SDK descriptor versions, and explicit requirement ranges rather than the default `>=2,<3`.

ServerHost must explicitly plan/open an ExtensionHost scope for IM factories from trusted registrations. Reuse dependency validation, parameter schemas, availability, owned/borrowed lifetimes, and rollback. Factories have process lifetime; Gateway-managed Connections are account resources with independent secrets, limits, and generations.

Adding a `runtime.capabilities` key does not make Server consume it: host assembly is required. Factories cannot depend on ConversationService before it exists; start actual connections after that service is ready. Gateway closes all connections before the extension scope closes.

Ordinary Agent packages cannot choose listeners, carry bot secrets, or register routes. Do not add IM settings to `AGENT_DEFAULTS`. Deployment owns plugin installation/upgrades. Version one permits explicitly installed trusted packages; adding a connection never triggers pip installation or arbitrary imports.

### 4.2 Message normalization

`InboundEvent` includes connection binding, organization, event/message IDs, event type/time, sender, conversation, topic/thread, reply target, mentions, text, and attachment references. Untrusted platform extensions belong in bounded metadata.

Project content into existing `TextBlock/ImageBlock/AudioBlock/FileBlock/ResourceRefBlock` types. Mentions, quotations, and destination addresses are channel context, not another model-message format. External text is always user input; payload roles, system content, tool results, and claimed Sage user IDs are not trusted instructions.

Download attachments through authorized platform access into existing controlled attachment/workspace paths. Validate size, MIME, paths, and ownership; do not expose credential-bearing URLs to the model. RunConfig stores necessary origin/address snapshots, never bot secrets or temporary download tokens.

## 5. Identity, Sessions, and Agent routing

### 5.1 Identity precedes admission

Distinguish connection owner, external organization, bot account, sender, Sage principal, and target Agent. URL `connection_id` is not authentication; display names, group-admin status, and self-reported user IDs grant no Sage permissions.

Default to personal connections: start short-lived pairing from authenticated Sage management, verify callback sender and a single-use code, and bind the owner's external identity. Only that identity may invoke private chat. Unknown senders are rejected. Pairing is attempt/time bounded and cannot use nicknames to claim an account.

Team connections are a later explicit mode: individually verified members use their own Sage users, or a group uses a dedicated user/Agent. An administrator owning a connection does not grant members access to private Agents, Shell, files, or memory.

Effective permissions intersect Server, Sage user, Agent, IM ingress grants, and current authorization. Existing `RunAdmission` and `live_execution_policy` need trusted ingress references and live checks; a one-time Gateway check is insufficient, and IM scope must not masquerade as an A2A key. Include tool/Skill grants, workspace access, and approval eligibility. Revocation must affect queued/recovered work, tools, and final delivery.

### 5.2 Session keys

Suggested logical key:

```text
tenant + sage_principal + connection_id + external_org
+ conversation_kind + external_chat + optional_topic
+ isolation_scope + agent_id + generation
```

Index a versioned stable digest of the normalized tuple, preserving platform-specific case semantics. Generate internal Session IDs server-side with unique mappings; never reuse external chat IDs as Sage Session IDs.

| Scenario | Default scope |
| --- | --- |
| Owner DM | Connection plus verified sender |
| Individual conversation in a group | Group, sender, optional topic; authorized principal required |
| Shared group | Group and optional topic; explicitly enabled dedicated principal/Agent |
| Native discussion thread | Parent conversation plus thread/topic |
| Cross-platform merge | Disabled initially; later requires explicit binding and verification of both identities |

NoneBot's OneBot [group-session implementation](https://github.com/nonebot/adapter-onebot/blob/master/nonebot/adapters/onebot/v11/event.py) includes both group and sender, illustrating why Sage must define its own isolation semantics.

Workspaces and long-term memory are also user/Agent resources: distinct Sessions do not isolate private resources of the same principal. Individual group mode does not make group replies private. Personal material should use authorized DM delivery or a private Sage page.

Use deterministic routing: topic rule, then conversation rule, then connection default. Validate Agent ownership/grants, rejecting equal-priority ambiguity. Pin the Agent on initial Session admission. Default changes affect new bindings only; `/agent` creates a new Session rather than changing ownership, and `/new` advances generation. Old Runs cannot send by reading a newer Session's last-chat address.

## 6. Inbound admission, concurrency, and recovery

1. Check request size, verify/decrypt and prevent replay, parse events, and retain normalized business input only after verification. Challenges and ignored events use platform-specific ACK rules.
2. Check connection generation, identity, trigger, and routing. Ignore self/echo, unauthorized senders, and unsupported edits/deletions; groups require a mention or command by default.
3. Commit durable inbox state with dedupe key, content digest, principal, selected Agent/scope, destination snapshot, and configuration revision. Duplicates reuse receipts; conflicting content is rejected. ACK only after commit. Freeze the resolved route, not merely a mutable reference.
4. Workers recheck live authorization, persist a frozen StartRun request, then call RunAdmission/RunService. Derive Run idempotency from connection, message ID, and supported event version.
5. Link `run_id` and observe canonical events.

Event IDs deduplicate callbacks; message IDs identify messages. Distinct event kinds/versions must not let ordinary retries create another Run. Version one does not turn edits/deletions into automatic input.

Inbox and SessionStore may use different transactions, especially MySQL and Redis. Recovery first resolves the stable admission key and reuses an existing accepted command/Run; otherwise it submits the persisted frozen request. Never rebuild the same key from the latest Agent package. Test crashes after Run acceptance but before inbox linkage.

Memory queues are bounded wakeups, not durable work. Persisted overflow remains claimable; unpersisted overflow uses retryable platform responses. ACK followed by an asyncio task is not reliable admission.

Reuse per-Session SERIAL rules and existing user/global quotas. Initially queue additional messages, route `/stop` through cancellation, and prioritize approval interactions. Steering is a later explicit capability, not automatic injection into the current Run.

## 7. Replies, streaming, approvals, and proactive delivery

### 7.1 Projection and visibility

Project canonical RuntimeEvent and RunResult into user-visible assistant text, authorized artifacts, interaction requests, and public errors. Exclude reasoning, raw tool arguments, diagnostic logs, and internal material.

Deltas are disposable previews; durable events own final content, suspended interactions, and terminal state. Use platform streaming, throttled edits, or final-only delivery. Shared delivery owns throttling, length, Markdown conversion, and ordering across text/attachments; adapters encode platform messages. Final replies suffice for version one.

### 7.2 Approvals and continuation

Render Sage interactions as cards or authenticated Sage links. Verify platform signatures, real operators, and approval grants. Bind tokens to connection, chat/topic, Run, interaction, required revisions, expiry, and one-time identity.

Decisions use existing ReplyInteraction/ResumeRun and CAS. Reuse interaction state/idempotent commands instead of duplicating approvals. Repeated clicks, stale cards, and expired grants cannot advance a Run. Group-admin status is not approval authorization; platforms without reliable operator identity send Sage-login links only.

### 7.3 Proactive sending and MCP

Normal replies are host projections, without an IM model tool. Long tasks, schedules, and explicit proactive messages share Delivery and authorized Destination snapshots, never global current-chat or recent-contact state. Outbound-only webhooks declare `receives_messages=false`; limited reply windows cannot imply unrestricted proactive capability.

An optional later `im_send` tool/MCP wrapper accepts controlled `destination_ref`. Server checks owner, Agent, permitted target, and file access. Models cannot gain cross-account access by supplying tokens or arbitrary connection IDs. Tools report precise queued/platform-accepted stages, not delivery. Automatic replies and explicit sends have separate purposes; using any IM tool must not globally suppress final replies.

### 7.4 Outbound state and retry

```text
pending → sending → platform_accepted
                  ↘ retry_wait → pending
                  ↘ failed
                  ↘ unknown → 查询/幂等重放协调 → platform_accepted / pending / unknown
```

`platform_accepted` is not user delivery/read confirmation. Each part has stable `part_id` and receipt: confirmed parts are not resent, and unknown parts are not treated as unsent.

Rate-limit accounts and destinations, preserving text/media order within external chat/topic across distinct Sage Sessions. Respect retry-after and bounded backoff. Permanent authorization/target errors stop. Post-request timeouts may be `unknown`; reconcile using platform idempotency or receipt lookup, otherwise retain unknown with an operator action instead of blind retry.

Expired sending leases after crashes cannot automatically become pending. Retry only if no platform request was made can be proven; otherwise mark unknown and reconcile. This provides durable admission, Run idempotency, stable delivery intent, and bounded recovery, not unsupported end-to-end exactly-once guarantees.

## 8. Necessary business storage

Do not add audit-only business storage. Existing Session/events, threads/bindings, and approvals remain authoritative; use StructuredLogger and observability providers.

| Record | Purpose | Minimum fields |
| --- | --- | --- |
| im_connections | Account configuration and access | Owner, plugin, external identity, secret_ref, typed config, identity/routing rules, revision, enabled |
| im_conversation_bindings | Restart lookup and `/new` | Scope, principal, Agent, Session, generation, authorized destination |
| im_inbox | Recover acknowledged input and projection | Dedupe key, temporary input, frozen command, run_id, state, cursor, lease |
| im_deliveries | Recover sends, parts, and unknown receipts | Source/purpose key, Destination, required payload/reference, part, state, retry time, receipt, lease |

Do not duplicate history or create separate IM message/Run/approval/audit tables. Release temporary inbox/request data according to recovery needs; queued payload is delivery state, not another history. Reuse existing storage where it fully satisfies a contract instead of dual-writing.

Use inbox Run/cursor as the recovery entry, with replay-then-subscribe or gapless cursor subscription. Atomically insert unique outbound intent and advance cursor. Source keys deduplicate replay. An in-process finished callback alone can lose replies between Run completion and enqueue. All SessionStore reads require authorization, with explicit handling for revoked/deleted Runs or destinations.

P0 uses self-service connections: the authenticated caller is the owner, and submitted credentials are encrypted in the existing connection record using an independent master key generated automatically on first server startup, persisted at `<data_root>/secrets/im-credentials.key`, and reused on restart. Credentials never enter Runs, events, logs, or UI responses. Do not use the JWT secret or introduce a separate key platform. A missing or damaged key does not block Server startup: only affected connections are disabled and shown as unavailable, with their ciphertext preserved. Restore the key backup, test credentials, and explicitly enable each recovered connection.

Retain configuration/bindings until user deletion and impose business recovery retention/cleanup on input, receipts, and failure payloads. Dedupe keys and Session/Run relationships last through the maximum platform replay window; bodies may expire earlier. Unbounded replay windows preclude permanent deduplication claims after cleanup. Deleting a connection stops reception/delivery and cleans temporary/channel data; existing Sage conversations follow their own deletion semantics, without deleting an entire Agent workspace.

Suspended Runs retain projection association and resume from the old cursor after approval. Suspension is not terminal. Initially `/new` stops unsent ordinary replies from old generations, with results still available in the old Sage conversation. Explicit proactive subscriptions retain independent destinations/grants.

## 9. Lifecycle and deployment

Start database/SessionStore and execution services, load channel configuration/factories, recover inbox/projection, claim connection ownership, then listen/deliver. Shutdown stops new input and listeners, waits a bounded time for durable handoff, then closes IM scope and shared dependencies.

Connection states are disabled, starting, connected, reconnecting, error, and stopping. Configuration uses revision CAS; account edits reconnect only that connection, while plugin upgrades remain deployment restarts. Generation fencing rejects stale callbacks, status writes, and acknowledgments. Reconnection uses bounded backoff; invalid credentials enter error rather than unlimited rapid retries.

Match listeners to actual Server deployment. Multiple processes/replicas require exclusive WebSocket/polling ownership plus durable inbox/delivery leases and fencing. Distributed Run scheduling does not replace channel leader election. Webhooks may use load balancing with database dedupe and bounded claims.

Fencing blocks stale local writes, not already-sent HTTP requests. External uncertainty still requires reconciliation. Version one may explicitly limit IM to one listener host without adding a new message broker by default.

## 10. HTTP APIs and management UI

All interfaces are proposals, following existing JSON errors, field style, and request IDs without changing default-only plugin-save semantics.

| Method and path | Purpose |
| --- | --- |
| `GET /api/im/plugins` | Platform implementations, dependencies, schema, capabilities |
| `GET/POST /api/im/connections` | Owner's paginated list/create |
| `GET/PATCH/DELETE /api/im/connections/{id}` | Read, revision-checked update, delete |
| `GET /api/im/connections/{id}/status` | Actual state, current/desired revisions, redacted errors |
| `POST /api/im/connections/{id}/test` | Validate settings/credentials without messaging contacts by default |
| `POST /api/im/connections/{id}/pairings` | Create owner identity challenge |
| `POST /api/im/connections/{id}/conversation-resets` | Create a new Session after ownership checks |
| `GET /api/im/connections/{id}/deliveries` | Bounded failed/unknown delivery listing |
| `POST /api/im/deliveries/{id}/retries` | Revision-controlled retry; unknown requires explicit duplicate-risk handling |
| `/api/im/webhooks/{id}` | Plugin-method challenge/message/card callbacks |

Management uses Sage login and ownership; webhooks use platform authentication. Validate typed schemas, Agent ownership, duplicate external-account claims, and credentials on create/update. Distinguish configuration, authentication, conflict, and retryable busy errors. Pagination follows ThreadPage.

Navigation is a standalone **IM管理** menu (`/im`), with a title only, without unsolicited subtitles. Show connection name, platform, Agent/routing, state, and actions. Editors contain platform fields, identity/session rules, necessary grants, and secret references. Explain permissions or errors only when relevant to an action, without exposing implementation detail.

Separate plugin catalogs from connection instances: one Feishu plugin may serve many accounts. A successful connection test proves the tested credentials/interface, not production message permissions, group visibility, or complete end-to-end behavior.

## 11. Phases and acceptance

| Phase | Deliverables | Acceptance focus |
| --- | --- | --- |
| P0 contracts and first platform | Gateway, ExtensionHost factory, personal pairing, single-Agent routing, private text/final replies, `/new`, `/stop`, durable inbox/outbox/recovery, approval links | Deduplicated admission, disconnected Run completion, restart recovery, unknown-identity rejection |
| P1 second platform and groups | Different transport, explicit group rules/principal, media, throttled edits, operator-verified approval cards | No Gateway/Run-loop rewrite, no account crossover, no private workspace/memory exposure |
| P2 distribution and proactive tasks | Trusted third-party packages, controlled im_send/MCP, scheduled destinations, distributed ownership when needed | Shared delivery, live revocation, expired-claim/reload fencing |

Suggested first and second platforms are Feishu and Telegram, exercising long-connection/webhook/polling differences. Final order follows user demand, without assuming SDK or enterprise features. Group/card/native-streaming support depends on the selected integration's actual capability.

Required integration scenarios include:

- Two accounts on one platform, identical chat IDs across organizations, and identical sender IDs across Sage users without authorization crossover.
- Duplicate callbacks, conflicting payloads under one key, concurrent reset/Agent changes without repeat execution or ownership overwrite.
- Crashes around ACK, Run admission, terminal projection, and platform acceptance/receipt persistence, including unknown outcomes.
- Two queued messages and permission revocation during tools or approval waits.
- Duplicate, stale, forwarded, wrong-operator, and old-revision approval attempts.
- Ordered text/files, partially successful splitting, rate limits, permanent failure, and unsupported proactive windows.
- Reload/deletion, stale generation callbacks, backpressure, shutdown, temporary attachment cleanup, and media ownership.

Validation needs contract tests, real database/SessionStore recovery tests, and platform sandbox-bot end-to-end tests. None were executed for this proposal; source research is not platform integration evidence.
