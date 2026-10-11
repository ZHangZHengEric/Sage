# MCP smoke test: a read-only Sage and OpenQFR case study

A verified run from an existing development environment, documented on **2026-10-11**. Check the tool connection before adding an agent loop. This small smoke test uses Sage v2's MCP bridge to discover tools, read OpenQFR's public record count, search for one record, and fetch it. It checks that each response preserves matching text and structured JSON without truncation.

No model provider, API key, OpenQFR account, or locally running MCP server is needed. Network access to the public endpoint is required. These three OpenQFR operations read public data; the example sends only a fixed search and the returned record ID.

## Tested environment and reproduction boundaries

Use an existing Sage source checkout and its Python 3.12+ environment with MCP support. Run from the checkout root so Python can import `sagents`. This recipe adds one local script; it does not install Sage or change your model configuration. See Sage's [source setup](https://github.com/ZHangZHengEric/Sage#readme) if you have not installed it yet.

The verified source revision is `3cbf427bcb8cc21a8843678750ff0f6a9c21fde8`. The test environment used MCP SDK 1.29.0, HTTPX 0.28.1, Pydantic 2.13.4, and jsonschema 4.26.0. The checkout's full-application dependency pin is MCP SDK 1.28.1; this test does not establish that exact pinned installation. A clean installation was not tested.

A SOCKS-configured network may also require HTTPX's optional SOCKS support; the tested environment already had socksio 1.0.0. Do not disable certificate verification or bypass network restrictions.

Save the following as `openqfr_smoke.py` in the checkout root. It uses Sage's existing `McpToolPlugin`; no Sage source changes are required.

```python
"""Read-only Sage v2 / OpenQFR bridge smoke test. No model or API key."""
import asyncio
import json
from uuid import uuid4

from sagents.v2.contracts.principals import ActorRef, PrincipalType, RequestContext
from sagents.v2.tool import McpServerConfig, McpToolPlugin, ToolCall


async def main():
    plugin = McpToolPlugin((McpServerConfig(
        name="openqfr",
        protocol="streamable_http",
        url="https://openqfr.dev/mcp",
        timeout_seconds=30,
    ),))
    run_id = str(uuid4())
    context = RequestContext(actor=ActorRef(
        principal_id="mcp-smoke-test", principal_type=PrincipalType.USER,
    ))

    async def call(name, arguments):
        result = await plugin.execute(ToolCall(
            tool_call_id=str(uuid4()), tool_name=f"mcp_openqfr_{name}",
            arguments=arguments, operation_id=str(uuid4()),
            idempotency_key=str(uuid4()), owner_run_id=run_id,
        ), context)
        if result.error is not None:
            raise RuntimeError(f"{name}: {result.error}")
        if result.metadata.get("mcp_result_truncated") is not False:
            raise RuntimeError(f"{name}: result truncation check failed")
        texts = [json.loads(block.text) for block in result.content if block.kind == "text"]
        objects = [block.value for block in result.content if block.kind == "json"]
        if not texts or not objects or texts[0] != objects[0]:
            raise RuntimeError(f"{name}: text and structured JSON differ or are missing")
        print(f"PASS {name}: text = structured JSON; not truncated", flush=True)
        return objects[0]

    try:
        names = {tool.name for tool in await plugin.list_tools(run_id=run_id)}
        expected = {f"mcp_openqfr_{name}" for name in ("qfr_stats", "qfr_search", "qfr_get")}
        if not expected.issubset(names):
            raise RuntimeError(f"Missing tools: {sorted(expected - names)}")
        print("PASS discovery: " + ", ".join(sorted(expected)), flush=True)
        stats = await call("qfr_stats", {})
        print(f"Public records: {stats['public_records']}; schema: {stats['schema_version']}", flush=True)
        search = await call("qfr_search", {"symbol": "BTCUSDT", "limit": 1})
        if not search.get("matches"):
            raise RuntimeError("No BTCUSDT record returned; the public dataset may have changed")
        record_id = search["matches"][0]["record_id"]
        record = await call("qfr_get", {"record_id": record_id})
        if record.get("found") is not True or record["record"]["record_id"] != record_id:
            raise RuntimeError("Fetched record does not match the search result")
        print(f"PASS round trip: {record_id}", flush=True)
        print("PASS: discovery + 3 read-only calls; no model used", flush=True)
    finally:
        await plugin.release_run(run_id)


if __name__ == "__main__":
    asyncio.run(main())
```

## Run

From the same checkout root:

```bash
python openqfr_smoke.py
```

Actual output from the validated run (record count and ID may change):

```text
PASS discovery: mcp_openqfr_qfr_get, mcp_openqfr_qfr_search, mcp_openqfr_qfr_stats
PASS qfr_stats: text = structured JSON; not truncated
Public records: 20323; schema: 0.1.0-pilot
PASS qfr_search: text = structured JSON; not truncated
PASS qfr_get: text = structured JSON; not truncated
PASS round trip: qfr:000046995100f1b722fa68ec
PASS: discovery + 3 read-only calls; no model used

Exit code: 0
```

The script discovers tools and makes three tool calls, then releases the run in a `finally` block. Counts and record IDs depend on the live dataset. A successful run exits with status 0; connection, schema, or content failures raise an error instead of printing a final PASS.

## What this establishes

- Sage discovers the three expected tools under the `mcp_openqfr_` prefix. Extra tools added by the server do not break the check.
- Public stats, search, and fetch calls work through Streamable HTTP.
- Text and structured JSON agree for each response, with no result truncation.
- The fetched record matches the record returned by search.

This calls the bridge directly. It does not exercise model reasoning, the agent loop, the host approval UI, authentication, streaming model output, or a production deployment. The bridge conservatively projects these tools as `write` / `requires_approval`; the test does not change that policy or prove an agent can call them without approval. Only use direct execution with operations you have independently verified and authorized.

The public server and dataset may change or become unavailable. An empty `BTCUSDT` search result is reported as a failed dataset assumption. The example retrieves records; it does not verify their research conclusions or make trading recommendations.

## Evidence

The original successful run used Sage `3cbf427bcb8cc21a8843678750ff0f6a9c21fde8`, Python 3.12.14, MCP SDK 1.29.0, HTTPX 0.28.1, and Pydantic 2.13.4. See the [public interoperability report](https://github.com/openqfr-dev/openqfr/issues/2#issuecomment-6098702552).

The shorter script in this recipe also passed a live run: exit status 0, with no stderr output. The run used the existing test environment and the Sage source revision above. A clean virtual-environment installation has not been verified.

[Knowledge hub](../README.md) · [MCP engineering resources](../resources/mcp-engineering-resources.md)
