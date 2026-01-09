from ..service.knowledge_base import DocumentService
from fastmcp import FastMCP

kdb_mcp = FastMCP("Knowledge Base MCP Server")


@kdb_mcp.tool()
async def retrieve_on_zavixai_db(index_name: str, query: str, top_k: int = 5):
    return await DocumentService().doc_search(index_name, query, top_k)
