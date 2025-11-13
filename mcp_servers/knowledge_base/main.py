from typing import Dict, Any, List
import os
import uvicorn
from mcp.server.fastmcp import FastMCP
from fastapi import FastAPI

mcp = FastMCP("Knowledge Base")

@mcp.tool()
async def doc_document_insert(index_name: str, docs: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {"success": True, "index_name": index_name, "count": len(docs)}

@mcp.tool()
async def doc_document_delete(index_name: str, doc_ids: List[str]) -> Dict[str, Any]:
    return {"success": True, "index_name": index_name, "count": len(doc_ids)}

@mcp.tool()
async def doc_index_clear(index_name: str) -> Dict[str, Any]:
    return {"success": True, "index_name": index_name}

app = FastAPI(title="Knowledge Base MCP")
app.mount("/mcp", mcp.streamable_http_app())

if __name__ == "__main__":
    port = int(os.getenv("KB_PORT", "34003"))
    uvicorn.run(app, host="0.0.0.0", port=port)