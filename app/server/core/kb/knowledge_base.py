from __future__ import annotations

from typing import Any, Dict, List, Optional

from core.client.llm import embedding
from core.kb.document_split import DocumentSplit
from core.kb.es.doc import (
    DocDocument,
    doc_document_delete,
    doc_document_insert,
    doc_document_search,
    doc_index_clear,
    doc_index_create,
    get_documents_by_ids,
)
from core.kb.search_result_post_process import SearchResultPostProcessTool
from pydantic import BaseModel

from sagents.utils.logger import logger


class DocumentInput(BaseModel):
    main_doc_id: Optional[str] = None
    doc_id: str
    doc_content: Optional[str] = None
    origin_content: Optional[str] = None
    path: Optional[str] = None
    title: Optional[str] = None
    metadata: Dict[str, Any] | None = None


class DocumentService:
    async def doc_document_insert(self, index_name: str, docs: List[DocumentInput]) -> Dict[str, Any]:
        logger.info(f"index: {index_name}, insert docs: {docs}")
        try:
            await doc_index_create(index_name)
        except Exception as e:
            logger.error(f"index init failed: {e}")

        splitter = DocumentSplit()
        doc_documents: List[DocDocument] = []
        for d in docs or []:
            doc_id = d.doc_id
            if not doc_id:
                continue

            full_content = d.doc_content
            origin_content = d.origin_content
            main_doc_id = d.main_doc_id
            path = d.path
            title = d.title
            metadata = d.metadata
            if full_content:
                split_res = await splitter.split_text_by_punctuation(full_content)
                sentences = split_res.get("sentences_list", [])
                logger.info(f"doc_id: {doc_id}, 拆分段落数: {len(sentences)}")
                for s in sentences:
                    doc_documents.append(
                        DocDocument(
                            doc_id=doc_id,
                            main_doc_id=main_doc_id,
                            doc_segment_id=s.get("passage_id"),
                            doc_content=s.get("passage_content"),
                            full_content=full_content,
                            origin_content=origin_content,
                            start=s.get("start"),
                            end=s.get("end"),
                            path=path,
                            title=title,
                            metadata=metadata,
                        )
                    )
        doc_contents = [d.doc_content for d in doc_documents if d.doc_content]
        embeddings = await embedding(doc_contents)
        for i, d in enumerate(doc_documents):
            d.emb = embeddings[i]

        await doc_document_insert(index_name, doc_documents)
        return {"success": True, "index_name": index_name, "doc_count": len(docs or [])}

    async def doc_document_delete(self, index_name: str, doc_ids: List[str]) -> Dict[str, Any]:
        logger.info(f"index: {index_name}, delete docs: {doc_ids}")
        await doc_document_delete(index_name, doc_ids)
        return {"success": True, "index_name": index_name, "count": len(doc_ids or [])}

    async def doc_index_clear(self, index_name: str) -> Dict[str, Any]:
        logger.info(f"index: {index_name}, clear index")
        await doc_index_clear(index_name)
        return {"success": True, "index_name": index_name}

    async def doc_search(self, index_name: str, question: str, query_size: int) -> Dict[str, Any]:
        logger.info(f"index: {index_name}, question: {question}, query_size: {query_size}")
        embs = await embedding([question])
        emb = embs[0]
        pre_docs = await doc_document_search(index_name, question, emb, query_size)
        pre_docs_dicts = [d.model_dump() for d in pre_docs]
        docs = SearchResultPostProcessTool().process_search_results(pre_docs_dicts)
        doc_ids = list({d.get("doc_id") for d in docs if d.get("doc_id")})
        full_map = await get_documents_by_ids(index_name, doc_ids)
        for d in docs:
            doc_id = d.get("doc_id")
            if doc_id and doc_id in full_map:
                d["title"] = full_map[doc_id].title
                d["path"] = full_map[doc_id].path
                d["metadata"] = full_map[doc_id].metadata
                d["full_content"] = full_map[doc_id].full_content
        docs = docs[:query_size]
        logger.info(f"index: {index_name}, question: {question}, search_results: {docs}")
        return {"success": True, "index_name": index_name, "search_results": docs}