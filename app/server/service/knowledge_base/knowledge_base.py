from __future__ import annotations

from typing import Any, Dict, List, Optional, Type

from sagents.rag.manager import KnowledgeManager
from sagents.rag.schema import Document as SagentsDocument
from app.server.service.knowledge_base.adapter.es_vector_store import EsVectorStore
from app.server.service.knowledge_base.adapter.server_embedding_adapter import ServerEmbeddingAdapter
from app.server.service.knowledge_base.parser.base import BaseParser
from pydantic import BaseModel

from loguru import logger


class DocumentInput(BaseModel):
    main_doc_id: Optional[str] = None
    doc_id: str
    doc_content: Optional[str] = None
    origin_content: Optional[str] = None
    path: Optional[str] = None
    title: Optional[str] = None
    metadata: Dict[str, Any] | None = None


class DocumentService:
    def __init__(self, parser_cls: Optional[Type[BaseParser]] = None):
        self.vector_store = EsVectorStore()
        self.embedding_model = ServerEmbeddingAdapter()
        self.manager = KnowledgeManager(self.vector_store, self.embedding_model)
        self.parser: Optional[BaseParser] = parser_cls() if parser_cls else None

    async def sync_document(
        self, 
        index_name: str, 
        doc: Any, 
        file: Any, 
        data_source: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        同步文档：清理旧数据并处理新数据
        优先使用实例初始化时的 parser，如果未设置则尝试根据 data_source 获取。
        """
        current_parser = self.parser
        if not current_parser and data_source:
            from app.server.service.knowledge_base.parser import get_document_parser
            current_parser = get_document_parser(data_source)
            
        if not current_parser:
             # 如果既没有 parser 也没有有效的 data_source 导致找不到 parser
             if data_source:
                 raise ValueError(f"Unsupported data source: {data_source}")
             else:
                 raise ValueError("No parser configured and no data_source provided")

        logger.info(f"Syncing document: index={index_name}, doc_id={getattr(doc, 'id', 'unknown')}, parser={type(current_parser).__name__}")
        
        # 1. 清理旧数据
        delete_ids = await current_parser.clear_old(index_name, doc)
        if delete_ids:
            await self.doc_document_delete(index_name, delete_ids)
            
        # 2. 处理新数据
        doc_inputs = await current_parser.process(index_name, doc, file)
        count = 0
        if doc_inputs:
            await self.doc_document_insert(index_name, doc_inputs)
            count = len(doc_inputs)
            
        return {
            "success": True, 
            "index_name": index_name, 
            "deleted_count": len(delete_ids or []),
            "inserted_count": count
        }

    async def doc_document_insert(self, index_name: str, docs: List[DocumentInput]) -> Dict[str, Any]:
        logger.info(f"index: {index_name}, insert docs: {docs}")
        
        sagents_docs = []
        for d in docs:
            if not d.doc_id:
                continue
            
            doc = SagentsDocument(
                id=d.doc_id,
                content=d.doc_content or "",
                metadata={
                    "main_doc_id": d.main_doc_id,
                    "origin_content": d.origin_content,
                    "path": d.path,
                    "title": d.title,
                    **(d.metadata or {})
                }
            )
            sagents_docs.append(doc)
            
        await self.manager.add_documents(index_name, sagents_docs)
        return {"success": True, "index_name": index_name, "doc_count": len(docs or [])}

    async def doc_document_delete(self, index_name: str, doc_ids: List[str]) -> Dict[str, Any]:
        logger.info(f"index: {index_name}, delete docs: {doc_ids}")
        await self.manager.delete_documents(index_name, doc_ids)
        return {"success": True, "index_name": index_name, "count": len(doc_ids or [])}

    async def doc_index_clear(self, index_name: str) -> Dict[str, Any]:
        logger.info(f"index: {index_name}, clear index")
        await self.manager.clear_collection(index_name)
        return {"success": True, "index_name": index_name}

    async def doc_search(self, index_name: str, question: str, query_size: int) -> Dict[str, Any]:
        logger.info(f"index: {index_name}, question: {question}, query_size: {query_size}")
        
        # KnowledgeManager.search handles embedding generation and search
        chunks = await self.manager.search(index_name, question, query_size)
        
        # Enrich with full document info if needed
        doc_ids = list({chunk.document_id for chunk in chunks if chunk.document_id})
        full_docs = await self.manager.get_documents_by_ids(index_name, doc_ids)
        full_map = {doc.id: doc for doc in full_docs}
        
        results = []
        for chunk in chunks:
            res = {
                "doc_id": chunk.document_id,
                "doc_segment_id": chunk.id,
                "doc_content": chunk.content,
                "score": chunk.score,
                "start": chunk.metadata.get("start"),
                "end": chunk.metadata.get("end"),
                "title": chunk.metadata.get("title"),
                "path": chunk.metadata.get("path"),
                "metadata": chunk.metadata,
                # Default values from chunk metadata, override with full doc if available
            }
            
            if chunk.document_id in full_map:
                full_doc = full_map[chunk.document_id]
                res["title"] = full_doc.metadata.get("title") or res["title"]
                res["path"] = full_doc.metadata.get("path") or res["path"]
                # Merge metadata? Or just prefer full doc's?
                # res["metadata"] = full_doc.metadata
                res["full_content"] = full_doc.content
            
            results.append(res)
            
        logger.info(f"index: {index_name}, question: {question}, search_results: {results}")
        return {"success": True, "index_name": index_name, "search_results": results}

