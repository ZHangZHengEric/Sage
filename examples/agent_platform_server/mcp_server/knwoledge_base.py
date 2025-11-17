from fastmcp import FastMCP
from core.kb.knowledge_base import DocumentService

kdb_mcp = FastMCP("Knowledge Base MCP Server")


@kdb_mcp.tool()
async def retrieve(index_name: str, query: str, top_k: int = 5):
    return await DocumentService().doc_search(index_name, query, top_k)
