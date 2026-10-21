---
layout: default
title: 模型观测、Langfuse 与 Phoenix
parent: 架构
nav_order: 10
lang: zh
ref: v2-detail-sagents-v2-observability
---

{% include lang_switcher.html %}

# SAgents V2 模型观测、Langfuse 与 Phoenix

## 职责

`observability.provider` 是唯一的观测能力配置。Provider 统一创建日志输出、调用链导出、模型诊断、证据查询及其关闭流程；日志、Span 和诊断内容仍使用各自的数据结构与采集规则。旧的三个独立能力配置已删除，不做迁移或兼容。

可选插件为 `sage.observability.local`、`sage.observability.noop`、`sage.observability.otlp`、`sage.observability.langfuse` 和 `sage.observability.phoenix`。本地插件支持控制台/轮转文件日志与文件或独立 SQLite 诊断；SQLite 使用原有观测存储，不扩展业务数据库。外部插件封装导出和受支持的证据查询，不支持的查询明确标记不可用。

`log_level` 控制输出日志；`sample_rate` 和 `content_mode` 控制普通调用链；`diagnostic_content_mode` 独立控制诊断内容。外部原始诊断使用单独的采集传输，避免被普通 Trace 采样丢弃。关闭时先刷新诊断，再关闭导出器。观测写入失败不改变 Run 执行结果，查询仍需宿主先校验 Session 和 Run 归属。

```yaml
capabilities:
  observability.provider:
    plugin: sage.observability.local
    config:
      log_level: info
      log_root: /srv/sage/runtime/logs
      diagnostics_root: /srv/sage/runtime/sessions
      diagnostics_storage: files
```

## 模块组织与查询接口

`runtime/observability` 根目录保留公共契约、Provider 装配及通用日志/Trace 能力。`evidence/` 负责请求转换、脱敏和证据重建；`performance/` 负责有界性能采集、Trace 投影和纯耗时计算；具体文件、SQLite 和外部协议实现在 `plugins/` 中。通用证据与性能代码不依赖后端、HTTP 客户端或数据库。

宿主通过 Provider 的 `export_evidence`、模型记录查询、`report_performance` 和可选 `trace_query` 读取数据。`performance_available` 表示性能查询能力是否可用；`trace_query` 不可用时为 `None`。宿主保留鉴权、HTTP 参数校验和导航，不判断具体诊断实现、不读取存储路径。文件诊断与外部后端的差异由模块内部装配处理，性能计算口径共用，已有业务与诊断存储结构保持不变。

目录职责与维护规则见[模块说明](../../../sagents/v2/runtime/observability/README.md)。旧的根目录后端实现导出及被移动文件的导入路径已移除，调用方使用统一入口，后端测试使用 `plugins/` 中的实现。

## 对话耗时诊断

新增阶段日志使用 DEBUG 和中文文案，事件名保持稳定。通过
`SAGE_SERVER_LOG_LEVEL=debug` 开启，按 `correlation_id` 关联同一次请求；
进入运行后同时携带原生 `run_id` 和 `session_id`。

| 事件 | 耗时含义 |
| --- | --- |
| `server.admission.phase` | `phase` 区分外部归属、会话/绑定读取、无绑定 Session 校验、目录读取、包解析、技能/用户读取、快照/命令构建、归属绑定与会话索引保存；`prepare` 为接纳准备总计 |
| `server.run.preparation.started` / `server.run.agent_load.started` | `lock_wait_ms` 区分工作区锁和 Agent 加载锁的等待 |
| `server.run.agent_load` / `server.run.accepted` | Agent 装载、运行接纳的耗时 |
| `agent.preparation.completed` | `phase` 区分历史读取、自配置、技能预加载、工具选择、上下文构建与整个模型请求准备 |
| `mcp.discovery.completed` | 连接初始化、工具列表读取、连接清理的 `connect_ms/list_tools_ms/close_ms`；缓存命中不会重复发现 |
| `agent.state.commit` | 状态提交整体耗时，`event_types` 标识提交边界 |
| `session.mysql.commit` | 准备、连接等待、SQL 写入、事务提交的 `preparation_ms/connection_wait_ms/write_ms/commit_ms` |
| `model.first_text` | 当前模型请求收到首个非空正文 delta 的 `first_text_ms`，排除 reasoning |
| `agui.first_text` | 从 ConversationService.start 进入到首段 Assistant 正文准备发送 SSE 的耗时；不包含浏览器渲染，重放通过 `replayed` 标识 |

`model.request.completed` 也包含 `first_text_ms`；只返回完整响应、没有正文 delta 的模型该字段为空。
`agui.run.started` 的 `preparation_ms` 记录进入服务到开始准备运行前的耗时，
`agui.run.completed` 的 `duration_ms` 记录包含接纳与收尾的整体耗时。
父子阶段存在重叠，例如上下文构建包含在模型请求准备中，MySQL 提交包含在状态提交中，不能直接相加。
日志只记录身份、阶段、计数和耗时，不记录工具参数或模型正文。

Server 实时执行权限只查询当前 Agent 的策略字段，用户、Agent 和 API Key 使用独立数据库 Session 并行读取；
根权限和子 Agent 权限检查也并行执行。结果仍与接纳时冻结的权限取交集，不缓存实时撤权结果。
单个事务内存在依赖的写入以及工具执行前的持久化边界仍顺序等待。

入口目录读取只加载当前 Agent 及其可达团队成员，不读取无关 Package 或旧技能索引；
普通读取不获取目录行锁，仅首次创建默认目录时使用现有初始化事务。
运行已持有配置快照时，后续装载、工具适配器与模型供应器只读取资源目录，继续获取实时凭据。
会话/归属读取、目录/无绑定 Session 校验、技能/用户读取分别并行；每个数据库操作持有独立 Session，
会话归属绑定与索引保存仍在运行接纳前完成。团队成员按本次读取冻结版本，下一次运行可见成员更新。

可复现的本地目录读取基准：
`python -m scripts.v2.benchmark_admission --agents 100 --samples 7`。
2026-10-19，同一份 SQLite 数据（100 个测试 Agent 和 1 个默认 Agent），
全量路径为 5 条 SQL、101 个包，中位 24.870 ms；限定路径为 2 条 SQL、1 个包，中位 1.419 ms。
这验证了查询和解析范围的缩小，不代表生产冷启动或入口 11 秒等待已被消除；应通过阶段日志复测。

Server 既有诊断 SQLite 的模型记录与运行日志由单线程后台队列顺序写入，最多保留 64 个待处理操作，
不会让推理和工具继续执行等待诊断写盘。队列饱和和写入失败计入 `capture_failures_since_start`。
诊断导出和服务关闭最多等待 3 秒刷入；导出仍有待写入时，manifest 的
`diagnostic_writes_pending` 为 true。关闭超时会取消尚未开始的诊断操作并计数；
这些记录是 best effort 诊断资料，不参与运行恢复，不新增业务表。

## 文件诊断

文件诊断插件的 `root` 指向 SessionStore 的 `sessions` 根目录，使用与 SessionStore 相同的位置映射。请求写入所属 Session 的 `runs/<run_id>/llm_requests`；子会话位于父会话的 `sub_sessions/<session_id>` 中，不另建平铺诊断目录。旧平铺记录仍可读取，在该 Session 下一次诊断写入时迁入正确目录；会话状态和历史不参与此迁移。

内联媒体以 UTF-8 原文的 SHA256 去重，存入该 Session 的 `diagnostics/media/<sha256>.txt`。磁盘请求 JSON 使用 `$sage_diagnostic_media` 引用，`get_model_request` 和 `list_model_requests` 自动校验哈希、长度并还原原文，兼容旧内联记录。导出必须包含整个 Session 目录；媒体不跨 Session 引用，随所属 Session 一起归档或删除。去重只改变诊断存储，不改变实际模型请求、上下文 token 或权威历史。

## Trace 身份

每次顶层 execute/resume 建立新 trace，同一 Session 的多次执行通过 session_id 关联，暂停恢复通过 run_id 关联。这改变了原来的“整个 Session 一个 Jaeger trace”行为；查询历史数据时仍可使用 session_id。

同一次执行的子 Agent、模型与工具继承 trace。可信 `RequestContext.trace` 中的 trace_id/span_id 可以显式传入远程父上下文；ObservedRunDriver 会把当前身份写入传给执行体的 RequestContext，供下游传递。宿主跨进程调用时应透传该上下文；没有上下文的独立/恢复执行建立新 trace，不查库补造父 span。HTTP 的 X-Request-ID 仍作为 correlation_id，不充当 W3C trace ID。

OTLP 导出保留 Sage 的 128 位 trace ID、64 位 span ID，根 span 无父节点，远程或已结束父节点也保留真实 parent_span_id。Session、Run、request、tool_call、可信 user/tenant 等作为查询字段。Langfuse session 使用 root_session_id 聚合子 Agent；实际子 session_id 保留在 observation metadata。

## 字段与内容

- model.request：实际模型名、模型参数、messages/tools、响应文本/tool calls、finish_reason、input/output/cache/reasoning tokens、已知费用。
- 首 token 指首个非空文本或 reasoning delta；首个文本 delta 另记 first_text 事件和 first_text_ms，不把 reasoning 首 token 等同于用户可见文本延迟。
- tool.call：工具名、参数、结果与错误；agent.run：输入、最终输出和 run_state。
- 未报告 token 用量时不伪造零用量；未知实际模型名时不使用 `fast/default` binding 代替。费用字段使用 UsageSummary.cost（美元）；未提供费用时不在 Sage 猜价格。
- Langfuse 的缓存/推理 token 按互斥分类导出，避免它们作为总 input/output 的子集被重复累计。自定义模型价格需要在 Langfuse 配置。

`redacted` 模式采集内容，屏蔽已知敏感键、Bearer/sk token、URL userinfo/query/fragment 和 inline/base64 媒体；`metadata` 不采集输入输出。默认单项内容上限 16384 字符，最大 65536；超长内容以有效 JSON 的 truncated/preview 表达。结构化字段脱敏不能识别自由文本里的所有个人信息，需要完全关闭内容时使用 metadata。

## Server 配置

安装已有可选依赖：

```bash
python -m pip install -e '.[server,otel]'
```

Langfuse：

```dotenv
SAGE_SERVER_TRACE_BACKEND=langfuse
SAGE_SERVER_LANGFUSE_BASE_URL=https://cloud.langfuse.com
LANGFUSE_PUBLIC_KEY=pk-lf-your-project
LANGFUSE_SECRET_KEY=sk-lf-your-project
SAGE_SERVER_TRACE_ENVIRONMENT=production
SAGE_SERVER_TRACE_CONTENT_MODE=redacted
SAGE_SERVER_TRACE_SAMPLE_RATE=1.0
SAGE_SERVER_LANGFUSE_INGESTION_VERSION=4
```

地址应为所选区域/自托管实例的根 URL。插件追加 `/api/public/otel/v1/traces`，使用 OTLP/HTTP protobuf 和 Basic Auth；v4 添加 ingestion header，兼容的 v3 实例选择 3。浏览器入口可通过 `SAGE_SERVER_LANGFUSE_PUBLIC_URL` 指向具体项目。项目密钥仅从环境读取，manifest 只保存环境变量名；可用 `SAGE_SERVER_LANGFUSE_PUBLIC_KEY_ENV` 和 `SAGE_SERVER_LANGFUSE_SECRET_KEY_ENV` 更改名字。

Phoenix（与 Langfuse 独立选择）：

```dotenv
SAGE_SERVER_TRACE_BACKEND=phoenix
SAGE_SERVER_PHOENIX_ENDPOINT=http://127.0.0.1:6006/v1/traces
SAGE_SERVER_PHOENIX_PROJECT_NAME=sage
SAGE_SERVER_PHOENIX_PUBLIC_URL=http://127.0.0.1:6006
# 需要认证的实例才设置；本地无认证实例可以省略
PHOENIX_API_KEY=your-api-key
```

`endpoint` 是完整的 OTLP/HTTP protobuf 接收地址，包含 `/v1/traces`；云端实例填写提供的完整地址并保留路径前缀。API Key 使用 Bearer Auth，可通过 `SAGE_SERVER_PHOENIX_API_KEY_ENV` 更改读取的环境变量名，manifest 不保存密钥值。可选的 `SAGE_SERVER_PHOENIX_PUBLIC_URL` 单独配置浏览器入口。

SDK 插件 ID 为 `sage.observability.phoenix`，配置字段为 `endpoint`、`project_name`、`api_key_env`、`service_name` 及公共 trace 选项。Server 的「观测」能力中可选择 Phoenix；保存后重启 Server 生效。

Phoenix 项目使用资源字段 `openinference.project.name`；Agent、模型、工具分别映射为 OpenInference 的 `AGENT`、`LLM`、`TOOL`。`session.id` 使用根 Session 聚合子 Agent，原始 Sage 身份仍保留。缓存和推理 token 作为 prompt/completion 的子计数，total 仅计算 input + output。内容模式、脱敏和首 token/首正文事件沿用公共观测。此插件导出评测所需的运行数据，不主动发起评测或写入评分。

通用 OTLP：

```dotenv
SAGE_SERVER_TRACE_BACKEND=otlp
SAGE_SERVER_TRACE_OTLP_ENDPOINT=http://127.0.0.1:4318/v1/traces
SAGE_SERVER_TRACE_OTLP_PROTOCOL=http
```

gRPC 时选择 `grpc` 并使用 collector 的 gRPC 地址；只有明文 gRPC 才设置 `SAGE_SERVER_TRACE_OTLP_INSECURE=true`。没有显式 TRACE_BACKEND 时，旧 `SAGE_SERVER_JAEGER_URL` 配置继续选择 OTLP。环境变量显式 `noop` 关闭外部链路并使用本地观测；选择 `sage.observability.noop` 才会关闭全部观测。这些后端都支持内容限制、环境、采样和导出超时。通用 collector 认证可使用 OTel 的 exporter headers 环境配置。

非 Server 宿主通过 `observability.provider` 选择同名插件，配置 schema 见官方插件注册表；队列默认 2048、活动 span 默认 4096，可分别设置 max_queue_size/max_active_spans。插件是进程级资源，宿主关闭时调用 stop/close。当前 capability 单选；需要同时投递多个后端时可在外部 OTel Collector 分流。

## 失败与验证

生产导出在后台批量执行，有界队列饱和时丢弃并计数，不阻塞 Agent。采样按 trace ID 一致决定。导出失败限频告警，不打印密钥/异常响应；关闭时限时 flush，默认最多等待 3 秒。观测采用 best effort，不保证进程崩溃前数据全部送达。

Server `/metrics` 提供进程累计的 `trace_failed_exports`、`trace_dropped_spans` 和当前 `trace_active_spans` gauge（带宿主 registry 前缀）。`/health` 的 trace_enabled/trace_backend 表示配置启用状态，不表示远端可达；trace_console 表示配置了管理入口。管理员通过 `/api/observability/console` 打开选定后端，Langfuse 自己的登录仍由 Langfuse 管理。

自动测试覆盖身份和父子关系、并发隔离、模型输入输出与 token 映射、脱敏、暂停恢复、异常取消、诊断失败、导出失败/队列饱和、关闭超时、配置与管理员鉴权，以及本地 HTTP 接收端的实际 OTLP protobuf。

部署验收还需在目标 Langfuse 中执行一轮带工具的对话，确认 Agent/Generation/Tool 调用树、Session 聚合、模型用量和首 token 时间；再使 exporter 不可达，确认对话仍完成。测试接收端成功不能代替目标实例 UI 和 ingestion 的联调。

参考：[Langfuse OTLP 接入与属性映射](https://langfuse.com/integrations/native/opentelemetry)。

Phoenix 参考：[OTLP 配置](https://arize.com/docs/phoenix/tracing/how-to-tracing/setup-tracing/setup-using-phoenix-otel)、[OpenInference 字段规范](https://github.com/Arize-ai/openinference/blob/main/spec/semantic_conventions.md)。
