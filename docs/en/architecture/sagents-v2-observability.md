---
layout: default
title: Model Observability and Langfuse
parent: Architecture
nav_order: 10
lang: en
ref: v2-detail-sagents-v2-observability
---

{% include lang_switcher.html %}

# SAgents V2 Model Observability and Langfuse

## Responsibilities

`DiagnosticSink` saves local model requests/responses and wire requests for the Session model diagnostics view; it is not a recovery source. `TraceSink` represents Agent, model, and tool lifecycles, inputs and outputs, usage, status, and parent relationships. Each consumes execution data directly without reading the other's files or relying on the observability backend for Run recovery. Diagnostic write failures produce warnings without interrupting model calls.

`ObservedRunDriver` owns Agent and tool observations; `RecordingModelProvider` owns model observations. They emit the same vendor-independent `TraceSpan`. `sage.trace.otlp` exports generic/GenAI attributes, while `sage.trace.langfuse` adds Langfuse mappings over the shared OTLP transport. No database tables or durable observability queues are added.

## Trace identity

Each top-level execute/resume starts a new trace. Multiple executions in one Session are linked by session_id, and suspension/resumption by run_id. This changes the previous behavior of using one Jaeger trace for the entire Session; historical data can still be queried by session_id.

Child Agents, models, and tools in one execution inherit the trace. A trusted `RequestContext.trace` can supply trace_id/span_id as an explicit remote parent. ObservedRunDriver writes the current identity into the RequestContext passed to the execution body for downstream propagation. Hosts should forward that context across process boundaries. Independent or resumed executions without it start a new trace rather than reconstructing a parent span from storage. HTTP X-Request-ID remains correlation_id, not a W3C trace ID.

OTLP preserves Sage's 128-bit trace ID and 64-bit span ID. Root spans have no parent; remote or already-ended parents retain their actual parent_span_id. Session, Run, request, tool_call, and trusted user/tenant identities are query attributes. Langfuse sessions use root_session_id to group child Agents; the actual child session_id remains in observation metadata.

## Attributes and content

- model.request: actual model name, model parameters, messages/tools, response text/tool calls, finish_reason, input/output/cache/reasoning tokens, and known cost.
- First token means the first nonempty text or reasoning delta. The first text delta is recorded separately as the first_text event and first_text_ms; a reasoning first token is not treated as user-visible text latency.
- tool.call: tool name, arguments, results, and errors; agent.run: input, final output, and run_state.
- Unreported token usage is not fabricated as zero. Unknown actual model names are not replaced by the `fast/default` binding. Cost comes from UsageSummary.cost in US dollars; Sage does not estimate prices when it is absent.
- Langfuse cache/reasoning tokens are exported as mutually exclusive categories, avoiding double counting them as subsets of total input/output. Configure custom model prices in Langfuse.

`redacted` mode collects content while masking known sensitive keys, Bearer/sk tokens, URL userinfo/query/fragment, and inline/base64 media. `metadata` collects no input/output content. The default per-item content limit is 16384 characters, with a maximum of 65536; oversized content is represented as valid JSON with truncated/preview fields. Structured redaction cannot identify all personal information in free text. Use metadata to disable content collection entirely.

## Server configuration

Install the existing optional dependencies:

```bash
python -m pip install -e '.[server-v2,otel]'
```

Langfuse:

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

Use the root URL of the selected region or self-hosted instance. The plugin appends `/api/public/otel/v1/traces` and uses OTLP/HTTP protobuf with Basic Auth. Version 4 adds the ingestion header; select 3 for a compatible v3 instance. `SAGE_SERVER_LANGFUSE_PUBLIC_URL` can point the browser entry to a specific project. Project keys are read only from the environment; the manifest stores environment variable names. Override those names with `SAGE_SERVER_LANGFUSE_PUBLIC_KEY_ENV` and `SAGE_SERVER_LANGFUSE_SECRET_KEY_ENV`.

Generic OTLP:

```dotenv
SAGE_SERVER_TRACE_BACKEND=otlp
SAGE_SERVER_TRACE_OTLP_ENDPOINT=http://127.0.0.1:4318/v1/traces
SAGE_SERVER_TRACE_OTLP_PROTOCOL=http
```

For gRPC, select `grpc` and use the collector's gRPC address. Set `SAGE_SERVER_TRACE_OTLP_INSECURE=true` only for plaintext gRPC. Without an explicit TRACE_BACKEND, the legacy `SAGE_SERVER_JAEGER_URL` setting continues to select OTLP. Explicit `noop` disables tracing. Both backends support content limits, environment, sampling, and export timeouts. Generic collector authentication can use OTel exporter-header environment settings.

Non-Server hosts select the same plugins through `observability.trace-sink`; configuration schemas are in the official plugin registry. The queue defaults to 2048 and active spans to 4096, adjustable with max_queue_size/max_active_spans. Plugins are process-scoped resources; hosts call stop/close on shutdown. The capability currently selects one backend. Use an external OTel Collector to fan out to multiple backends.

## Failures and validation

Production exports run in background batches. A saturated bounded queue drops spans and counts them without blocking the Agent. Sampling decisions are consistent per trace ID. Export failures produce rate-limited warnings without printing keys or exception responses. Shutdown uses a bounded flush, waiting at most 3 seconds by default. Observability is best effort and does not guarantee delivery of all data before a process crash.

Server `/metrics` exposes cumulative process counters `trace_failed_exports` and `trace_dropped_spans`, plus the current `trace_active_spans` gauge, with the host registry prefix. `/health` trace_enabled/trace_backend indicate configured enablement, not remote reachability; trace_console indicates a configured management entry. Administrators open the selected backend through `/api/observability/console`; Langfuse manages its own login.

Automated tests cover identities and parent relationships, concurrent isolation, model input/output and token mappings, redaction, suspension/resumption, exceptions/cancellation, diagnostic failures, export failures/queue saturation, shutdown timeouts, configuration and administrator authorization, and actual OTLP protobuf received by a local HTTP server.

Deployment acceptance also requires running a conversation with a tool against the target Langfuse instance, checking the Agent/Generation/Tool tree, Session grouping, model usage, and first-token timing. Then make the exporter unreachable and confirm that the conversation still completes. A successful test receiver does not replace integration with the target instance's UI and ingestion endpoint.

Reference: [Langfuse OTLP integration and attribute mappings](https://langfuse.com/integrations/native/opentelemetry).
