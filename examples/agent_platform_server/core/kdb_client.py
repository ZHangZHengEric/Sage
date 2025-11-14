from __future__ import annotations
from config.settings import ENV, env_str
from typing import Dict, List, Optional, Any
from pydantic import BaseModel
import os
from mcp.client.streamable_http import streamablehttp_client
from mcp import ClientSession


class DocumentInput(BaseModel):
    main_doc_id: Optional[str] = None
    doc_id: str
    doc_content: Optional[str] = None
    origin_content: Optional[str] = None
    path: Optional[str] = None
    title: Optional[str] = None
    metadata: Dict[str, Any] | None = None

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump()


class KnowledgeBaseClient:
    def __init__(self, url: str | None = None, api_key: str | None = None) -> None:
        self.url = env_str(ENV.KB_MCP_URL, "")
        self.api_key = env_str(ENV.KB_MCP_API_KEY, "")
        self.headers: Dict[str, str] = {}
        if len(self.api_key) > 0:
            self.headers["Authorization"] = f"Bearer {self.api_key}"

    async def insert_documents_by_mcp(
        self, index_name: str, docs: List[DocumentInput]
    ) -> Any:
        payload_docs: List[Dict[str, Any]] = [d.to_dict() for d in docs or []]

        async with streamablehttp_client(
            self.url, headers=self.headers, timeout=30
        ) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(
                    "doc_document_insert",
                    {"index_name": index_name, "docs": payload_docs},
                )
                if result.isError:
                    raise Exception(result.content[0].text)
                return result.model_dump()

    async def delete_documents_by_mcp(self, index_name: str, doc_ids: List[str]) -> Any:
        async with streamablehttp_client(
            self.url, headers=self.headers, timeout=30
        ) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(
                    "doc_document_delete",
                    {"index_name": index_name, "doc_ids": doc_ids},
                )
                if result.isError:
                    raise Exception(result.content[0].text)
                return result.model_dump()

    async def clear_knowledge_base_by_mcp(self, index_name: str) -> Any:

        async with streamablehttp_client(
            self.url, headers=self.headers, timeout=30
        ) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(
                    "doc_index_clear",
                    {"index_name": index_name},
                )
                if result.isError:
                    raise Exception(result.content[0].text)
                return result.model_dump()
