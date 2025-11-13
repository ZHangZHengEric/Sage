from __future__ import annotations

from typing import Any, Dict, List, Optional
from pydantic import BaseModel

from loguru import logger

from core.document_split import DocumentSplit

from core.client.embed_client import (
    embedding,
)
from es.doc import (
    doc_index_create,
    doc_document_insert,
    doc_document_delete,
    doc_index_clear,
    DocDocument,
)


class DocumentInput(BaseModel):
    main_doc_id: Optional[str] = None
    doc_id: str
    doc_content: Optional[str] = None
    origin_content: Optional[str] = None
    path: Optional[str] = None
    title: Optional[str] = None
    metadata: Dict[str, Any] | None = None


class DocumentService:
    async def doc_document_insert(
        self, index_name: str, docs: List[DocumentInput]
    ) -> Dict[str, Any]:

        try:
            await doc_index_create(index_name)
        except Exception as e:
            logger.error(f"index init failed: {e}")

        splitter = DocumentSplit()
        doc_documents: List[DocDocument] = []
        total_segments = 0
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
                total_segments += len(sentences)
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
        # 处理doc_documents 的doc_content embedding
        doc_contents = [d.doc_content for d in doc_documents if d.doc_content]
        embeddings = await embedding(doc_contents)
        for i, d in enumerate(doc_documents):
            d.embedding = embeddings[i]

        await doc_document_insert(index_name, doc_documents)
        return {
            "success": True,
            "index_name": index_name,
            "doc_count": len(docs or []),
            "segment_count": total_segments,
        }

    async def doc_document_delete(
        self, index_name: str, doc_ids: List[str]
    ) -> Dict[str, Any]:
        await doc_document_delete(index_name, doc_ids)
        return {"success": True, "index_name": index_name, "count": deleted}

    async def doc_index_clear(self, index_name: str) -> Dict[str, Any]:
        await doc_index_clear(index_name)
        return {"success": True, "index_name": index_name, "cleared_indices": cleared}
