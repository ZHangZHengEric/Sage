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
        self.url = url or env_str(ENV.KB_MCP_URL)
        self.api_key = api_key or env_str(ENV.KB_MCP_API_KEY, "")
        self.headers: Dict[str, str] = {}
        if self.api_key:
            self.headers["Authorization"] = f"Bearer {self.api_key}"
        self._http_cm = None
        self._session_cm = None
        self.session: ClientSession | None = None

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.close()

    async def connect(self) -> None:
        self._http_cm = streamablehttp_client(self.url, headers=self.headers)
        read, write, _ = await self._http_cm.__aenter__()
        self._session_cm = ClientSession(read, write)
        self.session = await self._session_cm.__aenter__()
        await self.session.initialize()

    async def close(self) -> None:
        try:
            if self._session_cm is not None:
                await self._session_cm.__aexit__(None, None, None)
        finally:
            self.session = None
        try:
            if self._http_cm is not None:
                await self._http_cm.__aexit__(None, None, None)
        finally:
            self._http_cm = None
            self._session_cm = None

    async def insert_documents_by_mcp(
        self, index_name: str, docs: List[DocumentInput]
    ) -> Any:
        if self.session is None:
            raise RuntimeError("session not initialized")
        payload_docs: List[Dict[str, Any]] = [d.to_dict() for d in docs or []]
        result = await self.session.call_tool(
            "doc_document_insert",
            {"index_name": index_name, "docs": payload_docs},
        )
        return result.model_dump()

    async def delete_documents_by_mcp(self, index_name: str, doc_ids: List[str]) -> Any:
        if self.session is None:
            raise RuntimeError("session not initialized")
        result = await self.session.call_tool(
            "doc_document_delete",
            {"index_name": index_name, "doc_ids": doc_ids},
        )
        return result.model_dump()

    async def clear_knowledge_base_by_mcp(self, index_name: str) -> Any:
        if self.session is None:
            raise RuntimeError("session not initialized")
        result = await self.session.call_tool(
            "doc_index_clear",
            {"index_name": index_name},
        )
        return result.model_dump()
