# Keyless Keenable Search MCP with SAgents

[Keenable's MCP server](https://docs.keenable.ai/mcp-server) provides
`search_web_pages` and `fetch_page_content`. Without a key, this example uses
`https://api.keenable.ai/mcp-public` and sends no credentials. With
`KEENABLE_API_KEY` set, it uses `https://api.keenable.ai/mcp` and sends the key
in an `X-API-Key` header.

From a Sage checkout, install with Python 3.12+ in a fresh environment:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
python -m examples.v2.keenable_search "Python asyncio TaskGroup documentation"
python -m examples.v2.keenable_search "Python asyncio TaskGroup documentation" \
  --fetch-url https://docs.python.org/3/library/asyncio-task.html
# Optional: keyed endpoint
KEENABLE_API_KEY=... python -m examples.v2.keenable_search "Python asyncio TaskGroup documentation"
```

The example discovers tools through `McpToolPlugin.list_tools`, selects their
Sage names (`mcp_keenable_search_web_pages` and `mcp_keenable_fetch_page_content`),
and calls `McpToolPlugin.execute` with Keenable's own argument names (`query`,
`url`). It prints Sage's `ToolExecutionResult` JSON and exits with an error if a
tool is missing or reports failure. It uses Streamable HTTP, sends a Sage
User-Agent, closes each SDK session, and releases the plugin's per-run state on
exit, including on failure.

Both Keenable tool schemas declare an optional `session_id` argument for grouping
calls from one agent session. The example passes one generated value to both
calls, and only when the advertised schema lists it. This is a tool argument; it
is unrelated to MCP transport sessions, which Sage opens and closes per call (see
[optional session reuse](../../docs/en/MCP_SERVERS.md#optional-session-reuse-for-embedded-hosts)).

This is an explicit host-side catalog/executor demo; it does not run a model or
an Agent. Running the command authorizes its search query and optional fetch URL.
Calling the executor directly does not invoke Sage's Agent policy/approval flow.
For an embedded Agent, follow
[Tools, Skills and MCP](../../docs/en/MCP_SERVERS.md#discover-authorize-call-and-close).
The example does not change any existing provider, default, or saved connection,
and reads no settings other than the optional `KEENABLE_API_KEY`.

## What is sent, and service limits

The search query and, with `--fetch-url`, the URL are sent to Keenable's hosted
service. Per Keenable's
[authentication docs](https://docs.keenable.ai/authentication#try-it-without-a-key),
keyless requests are logged with the query or fetched URL, IP address and user
agent. Keyless access is a shared public tier: Keenable's
[rate limits page](https://docs.keenable.ai/rate-limits) lists 1,000 requests per
hour and 10 per second per IP address, as of 15 Nov 2026. These limits are set by
the service and may change; keyless access is not guaranteed to be unlimited or
permanently free. See also Keenable's [privacy policy](https://keenable.ai/privacy).

## Tests

Mocked coverage (no network; `httpx.MockTransport` behind the real MCP SDK client).
Install the test dependencies from the repository root (`python -m pip install -e '.[test]'`), then run:

```bash
python -m pytest -q tests/sagents/v2/test_keenable_search_example.py
```

It covers public mode (endpoint, User-Agent, no `X-API-Key` or `Authorization`
header), keyed mode (header sent), tool-call arguments and `session_id` reuse,
`session_id` omitted when the schema does not declare it, tool-level errors, a
missing tool, transport and initialization failures (HTTP 401 and 429 and a
JSON-RPC error on `initialize`, surfaced as `SageV2Error`), and cleanup in each
case.

The key checks are scoped to these fixtures: their responses never contain the
key, so the tests show the example itself does not print the key or add it to
the raised error or the config repr. `SecretStr` protects configuration
serialization only. It does not redact text a provider returns or what chained
exceptions carry.

The live command above is an optional smoke test only; it depends on the external
service's availability and limits and is not part of CI.
