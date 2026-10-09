# SAgents V2 模型观测与 Langfuse

## 职责

`DiagnosticSink` 保存本地模型请求/响应及 wire request，供 Session 的模型诊断查看使用；它不是恢复依据。`TraceSink` 表达 Agent、模型、工具的生命周期、输入输出、用量、状态与父子关系。两者直接消费执行时的数据，互不读取对方的文件，也不依赖观测后端恢复 Run。诊断写入失败只告警，不中断模型调用。

`ObservedRunDriver` 负责 Agent 与工具，`RecordingModelProvider` 负责模型。它们产生同一份厂商无关 `TraceSpan`，`sage.trace.otlp` 导出通用/GenAI 字段，`sage.trace.langfuse` 在公共 OTLP 传输上添加 Langfuse 映射。没有新增数据库表或持久化观测队列。

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
python -m pip install -e '.[server-v2,otel]'
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

通用 OTLP：

```dotenv
SAGE_SERVER_TRACE_BACKEND=otlp
SAGE_SERVER_TRACE_OTLP_ENDPOINT=http://127.0.0.1:4318/v1/traces
SAGE_SERVER_TRACE_OTLP_PROTOCOL=http
```

gRPC 时选择 `grpc` 并使用 collector 的 gRPC 地址；只有明文 gRPC 才设置 `SAGE_SERVER_TRACE_OTLP_INSECURE=true`。没有显式 TRACE_BACKEND 时，旧 `SAGE_SERVER_JAEGER_URL` 配置继续选择 OTLP。显式 `noop` 关闭观测。两种后端都支持内容限制、环境、采样和导出超时。通用 collector 认证可使用 OTel 的 exporter headers 环境配置。

非 Server 宿主通过 `observability.trace-sink` 选择同名插件，配置 schema 见官方插件注册表；队列默认 2048、活动 span 默认 4096，可分别设置 max_queue_size/max_active_spans。插件是进程级资源，宿主关闭时调用 stop/close。当前 capability 单选；需要同时投递多个后端时可在外部 OTel Collector 分流。

## 失败与验证

生产导出在后台批量执行，有界队列饱和时丢弃并计数，不阻塞 Agent。采样按 trace ID 一致决定。导出失败限频告警，不打印密钥/异常响应；关闭时限时 flush，默认最多等待 3 秒。观测采用 best effort，不保证进程崩溃前数据全部送达。

Server `/metrics` 提供进程累计的 `trace_failed_exports`、`trace_dropped_spans` 和当前 `trace_active_spans` gauge（带宿主 registry 前缀）。`/health` 的 trace_enabled/trace_backend 表示配置启用状态，不表示远端可达；trace_console 表示配置了管理入口。管理员通过 `/api/observability/console` 打开选定后端，Langfuse 自己的登录仍由 Langfuse 管理。

自动测试覆盖身份和父子关系、并发隔离、模型输入输出与 token 映射、脱敏、暂停恢复、异常取消、诊断失败、导出失败/队列饱和、关闭超时、配置与管理员鉴权，以及本地 HTTP 接收端的实际 OTLP protobuf。

部署验收还需在目标 Langfuse 中执行一轮带工具的对话，确认 Agent/Generation/Tool 调用树、Session 聚合、模型用量和首 token 时间；再使 exporter 不可达，确认对话仍完成。测试接收端成功不能代替目标实例 UI 和 ingestion 的联调。

参考：[Langfuse OTLP 接入与属性映射](https://langfuse.com/integrations/native/opentelemetry)。
