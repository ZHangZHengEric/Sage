from typing import Dict, Any, List
import os
import uvicorn
from mcp.server.fastmcp import FastMCP
from fastapi import FastAPI
from contextlib import asynccontextmanager

from dotenv import load_dotenv

load_dotenv(".env")

mcp = FastMCP("Knowledge Base")


from service.document import DocumentService, DocumentInput
from core.client.es_client import (
    init_es_client,
    close_es_client,
)
from core.client.embed_client import (
    init_embed_client,
    close_embed_client,
)


_doc_service = DocumentService()


@mcp.tool()
async def doc_document_insert(
    index_name: str, docs: List[DocumentInput]
) -> Dict[str, Any]:
    return await _doc_service.doc_document_insert(index_name, docs)


@mcp.tool()
async def doc_document_delete(index_name: str, doc_ids: List[str]) -> Dict[str, Any]:
    return await _doc_service.doc_document_delete(index_name, doc_ids)


@mcp.tool()
async def doc_index_clear(index_name: str) -> Dict[str, Any]:
    return await _doc_service.doc_index_clear(index_name)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_es_client()
    await init_embed_client()
    try:
        yield
    finally:
        await close_embed_client()
        await close_es_client()


app = FastAPI(title="Knowledge Base MCP", lifespan=lifespan)
app.mount("/mcp", mcp.streamable_http_app())


if __name__ == "__main__":
    port = int(os.getenv("KB_PORT", "34003"))
    uvicorn.run(app, host="0.0.0.0", port=port)
