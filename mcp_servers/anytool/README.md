# AnyTool MCP

Independent MCP tool simulator. No dependency on Sage v1, Sage v2, application
configuration, or databases. Requires Python with `mcp`, `httpx`, and `loguru`.

Run over stdio:

```bash
python -m mcp_servers.anytool /absolute/path/anytool.json
```

Example configuration:

```json
{
  "name": "AnyTool",
  "simulator": {
    "protocol": "openai-chat-completions",
    "api_key": "YOUR_API_KEY",
    "base_url": "https://api.openai.com/v1",
    "model": "YOUR_MODEL",
    "temperature": 0.2,
    "max_tokens": 4096
  },
  "tools": [{
    "name": "lookup",
    "description": "Simulate a lookup",
    "parameters": {"type": "object", "properties": {"query": {"type": "string"}}},
    "returns": {"type": "object", "properties": {"result": {"type": "string"}}, "required": ["result"]}
  }]
}
```

Supported protocols: `openai-chat-completions`, `openai-responses`, and
`anthropic-messages`. OpenAI base URLs include `/v1`; Anthropic URLs may include
it or use the API origin. Chat-specific extensions can be supplied explicitly
in `simulator.extra_body`; AnyTool does not infer provider capabilities from Sage.

Hosts can use `build_anytool_server` with their own result generator. The v1
adapter selects its model using legacy application data. Desktop v2 supplies
configuration from its own catalog. Neither adapter is imported by this package.
