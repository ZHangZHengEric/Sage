"""Small local MCP service used by the runnable standard host."""
import json
import sys

for line in sys.stdin:
    message = json.loads(line)
    if "id" not in message:
        continue
    method = message["method"]
    if method == "initialize":
        result = {"protocolVersion": message["params"]["protocolVersion"],
                  "capabilities": {"tools": {}}, "serverInfo": {"name": "host-demo", "version": "1"}}
    elif method == "tools/list":
        result = {"tools": [{"name": "echo", "description": "Echo a message",
                              "inputSchema": {"type": "object", "properties": {"message": {"type": "string"}},
                                              "required": ["message"], "additionalProperties": False}}]}
    elif method == "tools/call":
        result = {"content": [{"type": "text", "text": message["params"]["arguments"]["message"]}]}
    elif method == "ping":
        result = {}
    else:
        print(json.dumps({"jsonrpc": "2.0", "id": message["id"],
                          "error": {"code": -32601, "message": "unknown method"}}), flush=True)
        continue
    print(json.dumps({"jsonrpc": "2.0", "id": message["id"], "result": result}), flush=True)
