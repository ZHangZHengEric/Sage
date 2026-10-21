---
layout: default
title: Model Observability, Langfuse and Phoenix
parent: Architecture
nav_order: 10
lang: en
ref: v2-detail-sagents-v2-observability
---

{% include lang_switcher.html %}

# SAgents V2 Model Observability, Langfuse and Phoenix

The only observation selection is `observability.provider`. Its provider owns log outputs, spans, model diagnostics, supported evidence queries and shutdown. Select `sage.observability.local`, `sage.observability.noop`, `sage.observability.otlp`, `sage.observability.langfuse` or `sage.observability.phoenix`. Previous separate observation capability selections are rejected without compatibility. Log severity, trace sampling/content and diagnostic content are independently configured; raw evidence uses a separate unsampled transport. Existing isolated observation storage is reused; no business audit tables are added.

## Responsibilities

`DiagnosticSink` saves local model requests/responses and wire requests for the Session model diagnostics view; it is not a recovery source. `TraceSink` represents Agent, model, and tool lifecycles, inputs and outputs, usage, status, and parent relationships. Each consumes execution data directly without reading the other's files or relying on the observability backend for Run recovery. Diagnostic write failures produce warnings without interrupting model calls.

`ObservedRunDriver` owns Agent and tool observations; `RecordingModelProvider` owns model observations. They emit the same vendor-independent `TraceSpan`. `sage.observability.otlp` exports generic/GenAI attributes, while `sage.observability.langfuse` and `sage.observability.phoenix` add their respective platform mappings over the shared OTLP transport. No database tables or durable observability queues are added.

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

## Module organization and query interface

The `runtime/observability` root contains public contracts, Provider composition and shared logging/tracing. `evidence/` owns request conversion, redaction and evidence reconstruction. `performance/` owns bounded timing capture, trace projection and pure timing calculations. Concrete file, SQLite and external protocol adapters live in `plugins/`. Shared evidence and performance code does not depend on adapters, HTTP clients or databases.

Hosts read through the Provider's `export_evidence`, model-history methods, `report_performance` and optional `trace_query`. `performance_available` reports performance-query availability; unsupported trace queries are represented by `None`. Hosts retain authorization, HTTP validation and navigation without inspecting diagnostic implementation types or storage paths. Backend differences are composed inside the module, timing calculations are shared, and existing business and diagnostic storage schemas are unchanged.

See the [module guide](../../../sagents/v2/runtime/observability/README.md) for maintenance rules. Root-level concrete adapter exports and moved module import paths have been removed; callers use the unified entry point, while adapter tests import implementations under `plugins/`.

## Conversation latency diagnostics

Enable `SAGE_SERVER_LOG_LEVEL=debug` to collect phase logs. Stable event names correlate through `correlation_id`, then native `run_id` and `session_id` after admission. Log messages are Chinese; fields contain identities, phases, counts and timings, without tool arguments or model bodies.

| Event | Timing |
| --- | --- |
| `server.admission.phase` | Ownership, Session/binding reads, unbound Session validation, catalog reads, package parsing, Skills/user reads, snapshot/command construction, binding and Session index writes; `prepare` is total admission preparation |
| `server.run.preparation.started` / `server.run.agent_load.started` | Workspace and Agent load lock waits in `lock_wait_ms` |
| `server.run.agent_load` / `server.run.accepted` | Agent loading and Run admission |
| `agent.preparation.completed` | History, self-configuration, Skill preload, tool selection, context construction and total model-request preparation |
| `mcp.discovery.completed` | `connect_ms/list_tools_ms/close_ms`; cache hits do not rediscover |
| `agent.state.commit` | Total state commit; `event_types` identifies its boundary |
| `session.mysql.commit` | `preparation_ms/connection_wait_ms/write_ms/commit_ms` |
| `model.first_text` | `first_text_ms` to the first nonempty body delta, excluding reasoning |
| `agui.first_text` | ConversationService.start to preparing the first Assistant body SSE; excludes browser rendering; `replayed` marks replay |

`model.request.completed` also records `first_text_ms`, which is empty for models without body deltas. `agui.run.started.preparation_ms` covers entry to Run preparation, and `agui.run.completed.duration_ms` includes admission and cleanup. Nested phases overlap and must not be added together.

Live execution authorization reads current Agent policy, user and API Key concurrently with separate database Sessions. Root and child checks also run concurrently, intersected with frozen admission permissions. Revocation results are not cached. Dependent transaction writes and pre-tool durable boundaries remain sequential.

Catalog reads load only the selected Agent and reachable Team members. Ordinary reads do not lock catalog rows; default initialization retains its existing transaction. Frozen configurations retain current credential lookup while subsequent loads read only resource catalogs. Session/ownership, catalog/unbound Session checks and Skills/user reads run concurrently with separate Sessions. Binding and index writes finish before admission. Team member versions are frozen for each Run.

Reproduce the local catalog benchmark with `python -m scripts.v2.benchmark_admission --agents 100 --samples 7`. On 2026-10-19, the same SQLite dataset with 100 test Agents and one default Agent took a median 24.870 ms for five SQL statements and 101 packages versus 1.419 ms for two statements and one package. This verifies reduced query scope, not production cold-start latency or elimination of an observed eleven-second entry wait.

Server diagnostic SQLite writes use a single background worker and at most 64 pending operations. Inference and tools do not wait for diagnostic disk writes. Saturation and failures increment `capture_failures_since_start`. Export and shutdown flush for at most three seconds; exports mark pending writes with `diagnostic_writes_pending`. Shutdown timeout cancels queued operations and counts them. These best-effort records do not participate in recovery or add business tables.

## Filesystem diagnostics

The filesystem diagnostic plugin's `root` is the SessionStore's `sessions` root. Both use the same location map. Requests live in their owning Session's `runs/<run_id>/llm_requests`, including nested children under `sub_sessions/<session_id>`. Old flat records remain readable and move into the owning Session on its next diagnostic write; Session state and history are not migrated by the sink.

Inline media is deduplicated by the SHA256 of its original UTF-8 text into the owning Session's `diagnostics/media/<sha256>.txt`. On-disk JSON contains `$sage_diagnostic_media` references. `get_model_request` and `list_model_requests` verify length and hash and restore the original strings, while retaining compatibility with inline records. Export the whole Session directory; media never references another Session and follows its owner during archive or deletion. This changes diagnostic storage only, not actual model requests, context tokens, or authoritative history.

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
python -m pip install -e '.[server,otel]'
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

Phoenix (selected independently from Langfuse):

```dotenv
SAGE_SERVER_TRACE_BACKEND=phoenix
SAGE_SERVER_PHOENIX_ENDPOINT=http://127.0.0.1:6006/v1/traces
SAGE_SERVER_PHOENIX_PROJECT_NAME=sage
SAGE_SERVER_PHOENIX_PUBLIC_URL=http://127.0.0.1:6006
# Only needed for authenticated instances; omit for local unauthenticated instances.
PHOENIX_API_KEY=your-api-key
```

The endpoint is the complete OTLP/HTTP protobuf traces URL, including `/v1/traces`. For cloud instances, preserve the provided path prefix. Authentication uses a Bearer API key; `SAGE_SERVER_PHOENIX_API_KEY_ENV` overrides the environment variable name. Manifests store only that reference. The optional `SAGE_SERVER_PHOENIX_PUBLIC_URL` configures the browser entry separately.

The SDK plugin is `sage.observability.phoenix`, with `endpoint`, `project_name`, `api_key_env`, `service_name`, and shared trace options. Select Phoenix in the Server observation settings; saved selections take effect after restarting the Server.

Project routing uses the `openinference.project.name` resource attribute. Agent, model, and tool spans map to `AGENT`, `LLM`, and `TOOL`. Root Sessions group child Agents through `session.id`; original Sage identities remain available. Cache and reasoning tokens are subsets of prompt/completion; total is input + output. Content policies, redaction, and first-token/first-text events use the shared transport. This plugin exports runtime data for evaluation; it does not initiate evaluations or submit scores.

Generic OTLP:

```dotenv
SAGE_SERVER_TRACE_BACKEND=otlp
SAGE_SERVER_TRACE_OTLP_ENDPOINT=http://127.0.0.1:4318/v1/traces
SAGE_SERVER_TRACE_OTLP_PROTOCOL=http
```

For gRPC, select `grpc` and use the collector's gRPC address. Set `SAGE_SERVER_TRACE_OTLP_INSECURE=true` only for plaintext gRPC. Without an explicit TRACE_BACKEND, the legacy `SAGE_SERVER_JAEGER_URL` setting continues to select OTLP. Explicit `noop` disables tracing. All backends support content limits, environment, sampling, and export timeouts. Generic collector authentication can use OTel exporter-header environment settings.

Non-Server hosts select the same plugins through `observability.provider`; configuration schemas are in the official plugin registry. The queue defaults to 2048 and active spans to 4096, adjustable with max_queue_size/max_active_spans. Plugins are process-scoped resources; hosts call stop/close on shutdown. The capability currently selects one backend. Use an external OTel Collector to fan out to multiple backends.

## Failures and validation

Production exports run in background batches. A saturated bounded queue drops spans and counts them without blocking the Agent. Sampling decisions are consistent per trace ID. Export failures produce rate-limited warnings without printing keys or exception responses. Shutdown uses a bounded flush, waiting at most 3 seconds by default. Observability is best effort and does not guarantee delivery of all data before a process crash.

Server `/metrics` exposes cumulative process counters `trace_failed_exports` and `trace_dropped_spans`, plus the current `trace_active_spans` gauge, with the host registry prefix. `/health` trace_enabled/trace_backend indicate configured enablement, not remote reachability; trace_console indicates a configured management entry. Administrators open the selected backend through `/api/observability/console`; Langfuse manages its own login.

Automated tests cover identities and parent relationships, concurrent isolation, model input/output and token mappings, redaction, suspension/resumption, exceptions/cancellation, diagnostic failures, export failures/queue saturation, shutdown timeouts, configuration and administrator authorization, and actual OTLP protobuf received by a local HTTP server.

Deployment acceptance also requires running a conversation with a tool against the target Langfuse instance, checking the Agent/Generation/Tool tree, Session grouping, model usage, and first-token timing. Then make the exporter unreachable and confirm that the conversation still completes. A successful test receiver does not replace integration with the target instance's UI and ingestion endpoint.

Reference: [Langfuse OTLP integration and attribute mappings](https://langfuse.com/integrations/native/opentelemetry).

Phoenix references: [OTLP setup](https://arize.com/docs/phoenix/tracing/how-to-tracing/setup-tracing/setup-using-phoenix-otel), [OpenInference semantic conventions](https://github.com/Arize-ai/openinference/blob/main/spec/semantic_conventions.md).
