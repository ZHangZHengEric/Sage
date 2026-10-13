# MCP tools are visible, but calls fail: a five-step diagnostic

Discovery is a checkpoint. To locate a failed call, follow one request from the host to the server and back. Stop at the first boundary for which you lack evidence.

**Source check: 2026-10-12.** Protocol examples target MCP **2026-07-28**, the revision currently reached by the official `latest` link. Sage notes below come from source inspection at [`904a0ce`](https://github.com/ZHangZHengEric/Sage/tree/904a0cefe8f96932870a009c8d3684a961e92a78). This is a diagnostic procedure, not a new live test or compatibility certification. Use the specification matching the protocol revision your connection actually uses.

## Before you start

Choose one already-authorized, bounded, read-only operation with non-sensitive test data. Record the host/server/SDK versions, protocol revision, transport, exact tool name, arguments, request ID, and timestamp. Keep the raw response and host error separately. Redact credentials and private data before sharing evidence. If an earlier call could have changed remote state, reconcile that state before retrying; Sage explicitly treats a lost result as an uncertain side effect. [Sage bridge](https://github.com/ZHangZHengEric/Sage/blob/904a0cefe8f96932870a009c8d3684a961e92a78/sagents/v2/tool/plugins/mcp.py)

## 1. Visible in settings, but no invocation reaches the server

**Inspect:** Is the exact tool present in the final model request, or only the connection's catalog? Then check the selected name, arguments, actor scopes, and pending approval. In Sage, policy and tool selection can narrow the model-visible catalog. MCP tools require `tool.external_side_effect` and are projected as `WRITE` with `requires_approval=True`; the configured host policy determines the approval interaction. [Runtime guide](https://github.com/ZHangZHengEric/Sage/blob/904a0cefe8f96932870a009c8d3684a961e92a78/sagents/v2/README.md) · [Sage authorization](https://github.com/ZHangZHengEric/Sage/blob/904a0cefe8f96932870a009c8d3684a961e92a78/docs/en/MCP_SERVERS.md)

**Next:** Correct the intended Agent allowlist or legitimate authorization through the host's normal flow. If the model never selected the tool, investigate selection before changing the server. A direct bridge call is not evidence that the Agent's approval path works.

## 2. A call starts, but only an HTTP status or timeout is visible

**Inspect:** Match the response to the request ID. For Streamable HTTP, inspect the JSON body or the final response in the SSE stream. HTTP success alone cannot establish RPC or tool success. A `202` notification acknowledgement is not a tool-call result. Distinguish Streamable HTTP's SSE response from the older SSE transport. [HTTP transport](https://modelcontextprotocol.io/specification/2026-07-28/basic/transports/streamable-http)

**Next:** If there is no final response, preserve the timeout, content type, and server-side evidence; do not invent a result from a connection indicator. Check endpoint, transport, credentials, and version agreement. Do not disable TLS checks. The current protocol changed session and request-metadata handling; Sage's inspected adapter still calls the SDK's `initialize()`. That source observation does not establish support for every current protocol feature. [Sage session adapter](https://github.com/ZHangZHengEric/Sage/blob/904a0cefe8f96932870a009c8d3684a961e92a78/sagents/v2/tool/_mcp_session.py) · [HTTP compatibility](https://modelcontextprotocol.io/specification/2026-07-28/basic/transports/streamable-http#backward-compatibility)

## 3. A response arrives: classify the failure before fixing it

**Inspect:** A top-level JSON-RPC `error` is different from `result.isError: true`. The former reports a protocol/request failure; the latter reports a tool execution failure. [Error handling](https://modelcontextprotocol.io/specification/2026-07-28/server/tools#error-handling)

**Fictional example A: unknown tool, protocol error.** Valid error-response shape; not a captured server response.

```json
{"jsonrpc":"2.0","id":17,"error":{"code":-32602,"message":"Unknown tool: lookup_archived_note"}}
```

**Next:** Refresh discovery and compare the exact remote name and input schema with the sent request. In Sage, public names are prefixed and normalized; the bridge routes them to remote names. `tool.arguments_invalid` is a local preflight failure, before `session.call_tool`. [Sage bridge](https://github.com/ZHangZHengEric/Sage/blob/904a0cefe8f96932870a009c8d3684a961e92a78/sagents/v2/tool/plugins/mcp.py)

**Fictional example B: tool execution error.** Valid completed-result shape; assume this fictional tool declares no output schema.

```json
{"jsonrpc":"2.0","id":18,"result":{"resultType":"complete","content":[{"type":"text","text":"Invalid limit: choose an integer from 1 to 20."}],"isError":true}}
```

**Next:** Follow the actionable error, correct the bounded argument, and retry only within the original authorization. Do not report this as success because the HTTP request completed. Sage maps `isError` to `mcp.tool_error`. [Sage bridge](https://github.com/ZHangZHengEric/Sage/blob/904a0cefe8f96932870a009c8d3684a961e92a78/sagents/v2/tool/plugins/mcp.py)

The current schema requires `resultType`; an older-version response without it is interpreted as complete. `input_required` instead needs the supported input flow before completion. Diagnose against the actual revision. [Response schema](https://modelcontextprotocol.io/specification/2026-07-28/schema#calltoolresultresponse)

## 4. The result says success, but your parser rejects it

**Inspect:** Retrieve that tool's actual `outputSchema`. With one declared, the server must produce conforming structured output and clients should validate it. Without one, missing `structuredContent` is not automatically a bug: tools can return text or other content. Structured content is server data, not the model provider's structured-output feature. [Output schema](https://modelcontextprotocol.io/specification/2026-07-28/server/tools#output-schema)

**Fictional example C: deliberate output-schema violation.** Suppose the declared schema is `{"type":"object","properties":{"count":{"type":"integer"}},"required":["count"]}`. This response has a valid MCP envelope but deliberately violates that tool contract: `count` is a string.

```json
{"jsonrpc":"2.0","id":19,"result":{"resultType":"complete","content":[{"type":"text","text":"{\"count\":\"3\"}"}],"structuredContent":{"count":"3"},"isError":false}}
```

**Next:** Report the failing path (`count`), expected type (`integer`), and actual type (`string`) with the schema. Fix the producer or contract rather than silently coercing the evidence. When a serialized JSON text copy is also provided, parse and compare it with `structuredContent`; do not demand that every text block be JSON or that narrative text equal structured data. The protocol recommends a serialized copy for backward compatibility. [Structured content](https://modelcontextprotocol.io/specification/2026-07-28/server/tools#structured-content)

## 5. The server returned data, but Sage shows missing content

**Inspect:** Compare the raw response with Sage's projected content and metadata: `mcp_result_received`, `mcp_result_truncated`, and `mcp_result_size_bytes`. `mcp_result_size_bytes` measures Sage’s serialized representation of the SDK result, not necessarily the raw HTTP response size. The inspected bridge replaces an oversized result with an omission notice; `max_result_bytes` defaults to **4,194,304 bytes**. This limit is distinct from model context or UI display limits. `_content` projects text and non-null structured content into separate blocks. [Sage bridge](https://github.com/ZHangZHengEric/Sage/blob/904a0cefe8f96932870a009c8d3684a961e92a78/sagents/v2/tool/plugins/mcp.py)

**Next:** Prefer a smaller query, fewer records, or server-supported pagination. Recheck the same boundary after narrowing the result. If raw data is complete but the projected result differs without truncation, preserve both for an adapter report. If the model received the correct result but answered incorrectly, investigate its consumption of the result separately.

## A useful bug report

- Host, server, SDK, and protocol versions; Sage commit if applicable
- Transport and redacted endpoint; exact discovered and invoked names
- Minimal authorized reproduction, arguments, request ID, timestamp
- Expected outcome; actual HTTP/RPC/tool/host error and redacted response
- Relevant input/output schema; truncation metadata; first failing step above
- What was actually tested, and what remains untested

## How this differs from the existing smoke test

The [OpenQFR smoke-test article](mcp-smoke-test.md), documented on 2026-10-11, draws on an [interoperability run on 2026-10-10](https://github.com/openqfr-dev/openqfr/issues/2#issuecomment-6098702552) at Sage `3cbf427`, using MCP SDK **1.29.0**, while the full-application pin was **1.28.1**. Its text/JSON equality checks are specific to those responses. It did not establish a clean pinned installation, model selection, Agent-loop approvals, authentication, or production behavior. The original report did not capture the protocol revision separately. This diagnostic neither reruns that test nor extends its evidence to other servers.

[Knowledge hub](../README.md) · [MCP engineering resources](../resources/mcp-engineering-resources.md)
