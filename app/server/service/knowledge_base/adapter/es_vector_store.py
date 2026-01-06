from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional

from loguru import logger
from sagents.retrieve_engine.interface.vector_store import VectorStore
from sagents.retrieve_engine.schema import Document, Chunk, SearchResult
from sagents.retrieve_engine.post_process import SearchResultPostProcessTool
from core.client.es import (
    dims,
    document_delete,
    document_insert,
    index_clear,
    index_create,
    index_delete,
    index_exists,
    search as es_search,
)


# Constants from es_repository
IndexSuffixDoc = "doc"
IndexSuffixDocFull = "doc_full"
doc_index_suffix = [IndexSuffixDoc, IndexSuffixDocFull]


def _compact(d: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in d.items() if v is not None}


def _doc_mapping() -> Dict[str, Any]:
    return {
        "properties": {
            "doc_id": {"type": "keyword", "index": False},
            "doc_segment_id": {"type": "keyword", "index": False},
            "doc_content": {"index": True, "type": "text", "analyzer": "my_ana", "similarity": "my_similarity"},
            "emb": {"type": "dense_vector", "dims": dims(), "similarity": "cosine"},
            "end": {"type": "long"},
            "start": {"type": "long"},
            "metadata": {"type": "object", "enabled": True},
        }
    }


def _doc_full_mapping() -> Dict[str, Any]:
    return {
        "properties": {
            "doc_id": {"type": "keyword", "index": False},
            "full_content": {"index": True, "type": "text", "analyzer": "my_ana", "similarity": "my_similarity"},
            "origin_content": {"type": "text"},
            "path": {"type": "text"},
            "title": {"type": "text"},
            "metadata": {"type": "object", "enabled": True},
        }
    }


class EsChunk(Chunk):
    """
    ES 存储的分块数据模型，继承自 sagents.retrieve_engine.schema.Chunk
    对应索引: {index_name}_doc
    """
    # 继承字段: id, content, document_id, embedding, metadata, score
    
    def to_es_source(self) -> Dict[str, Any]:
        """转换为 ES 存储格式"""
        return _compact({
            "doc_segment_id": self.id,
            "doc_content": self.content,
            "doc_id": self.document_id,
            "emb": self.embedding,
            "metadata": self.metadata,
            # 兼容旧字段，如果 metadata 中有则提取，否则为 None
            "start": self.metadata.get("start"),
            "end": self.metadata.get("end"),
            "path": self.metadata.get("path"),
            "title": self.metadata.get("title"),
            "main_doc_id": self.metadata.get("main_doc_id"),
        })

    @classmethod
    def from_es_source(cls, source: Dict[str, Any], score: float | None = None) -> EsChunk:
        """从 ES 结果构建对象"""
        metadata = source.get("metadata") or {}
        # 确保关键元数据存在
        for key in ["start", "end", "path", "title", "main_doc_id"]:
            if key in source and key not in metadata:
                metadata[key] = source[key]

        return cls(
            id=source.get("doc_segment_id") or "",
            content=source.get("doc_content") or "",
            document_id=source.get("doc_id") or "",
            embedding=source.get("emb"),
            metadata=metadata,
            score=score
        )


class EsDocument(Document):
    """
    ES 存储的完整文档模型，继承自 sagents.retrieve_engine.schema.Document
    对应索引: {index_name}_doc_full
    """
    # 继承字段: id, content, metadata, chunks
    
    # 额外字段，用于兼容旧逻辑（如果需要）
    origin_content: Optional[str] = None
    path: Optional[str] = None
    title: Optional[str] = None
    main_doc_id: Optional[str] = None

    def to_es_source(self) -> Dict[str, Any]:
        """转换为 ES 存储格式"""
        return _compact({
            "doc_id": self.id,
            "full_content": self.content,
            "metadata": self.metadata,
            # 提取显式定义的字段
            "origin_content": self.origin_content or self.metadata.get("origin_content"),
            "path": self.path or self.metadata.get("path"),
            "title": self.title or self.metadata.get("title"),
            "main_doc_id": self.main_doc_id or self.metadata.get("main_doc_id"),
        })

    @classmethod
    def from_es_source(cls, source: Dict[str, Any]) -> EsDocument:
        """从 ES 结果构建对象"""
        return cls(
            id=source.get("doc_id") or "",
            content=source.get("full_content") or "",
            metadata=source.get("metadata") or {},
            origin_content=source.get("origin_content"),
            path=source.get("path"),
            title=source.get("title"),
            main_doc_id=source.get("main_doc_id"),
        )


class EsVectorStore(VectorStore):
    """
    Adapter for the existing ElasticSearch service.
    """
    def __init__(self):
        self.post_processor = SearchResultPostProcessTool()

    async def create_collection(self, collection_name: str) -> None:
        for suffix, mapping in {IndexSuffixDoc: _doc_mapping(), IndexSuffixDocFull: _doc_full_mapping()}.items():
            if not await index_exists(index_name=f"{collection_name}_{suffix}"):
                await index_create(index_name=f"{collection_name}_{suffix}", mapping=mapping)

    async def add_documents(self, collection_name: str, documents: List[Document]) -> None:
        es_chunks: List[EsChunk] = []
        es_docs: List[EsDocument] = []

        for doc in documents:
            # 1. Prepare EsDocument
            es_doc = EsDocument(
                id=doc.id,
                content=doc.content,
                metadata=doc.metadata,
                origin_content=doc.metadata.get("origin_content"),
                path=doc.metadata.get("path"),
                title=doc.metadata.get("title"),
                main_doc_id=doc.metadata.get("main_doc_id"),
            )
            es_docs.append(es_doc)

            # 2. Prepare EsChunks
            for chunk in doc.chunks:
                # Merge document-level metadata into chunk metadata if not present
                chunk_meta = chunk.metadata.copy()
                for k, v in doc.metadata.items():
                    if k not in chunk_meta:
                        chunk_meta[k] = v

                es_chunk = EsChunk(
                    id=chunk.id,
                    content=chunk.content,
                    document_id=doc.id,
                    embedding=chunk.embedding,
                    metadata=chunk_meta,
                    score=chunk.score
                )
                es_chunks.append(es_chunk)

        # Insert Chunks
        if es_chunks:
            doc_index = f"{collection_name}_{IndexSuffixDoc}"
            chunk_sources = [chunk.to_es_source() for chunk in es_chunks]
            await document_insert(doc_index, chunk_sources)

        # Insert Full Documents
        if es_docs:
            full_index = f"{collection_name}_{IndexSuffixDocFull}"
            # Deduplicate by doc_id just in case
            doc_map = {doc.id: doc for doc in es_docs}
            doc_sources = [doc.to_es_source() for doc in doc_map.values()]
            if doc_sources:
                await document_insert(full_index, doc_sources)

    async def delete_documents(self, collection_name: str, document_ids: List[str]) -> None:
        if not document_ids:
            return
        for suffix in doc_index_suffix:
            idx = f"{collection_name}_{suffix}"
            if await index_exists(idx):
                await document_delete(idx, {"terms": {"doc_id": document_ids}})

    async def clear_collection(self, collection_name: str) -> None:
        for suffix in doc_index_suffix:
            idx = f"{collection_name}_{suffix}"
            try:
                if await index_exists(idx):
                    await index_clear(idx)
            except Exception as e:
                logger.error(f"Failed to clear index {idx}: {e}")

    async def search(self, collection_name: str, query: str, embedding: List[float], top_k: int = 5) -> List[Chunk]:
        index_doc = f"{collection_name}_{IndexSuffixDoc}"
        if not await index_exists(index_doc):
            return []

        async def _vec() -> List[SearchResult]:
            r = await es_search(index_doc, {
                "_source": {"excludes": ["emb"]},
                "knn": [{
                    "field": "emb",
                    "k": top_k,
                    "num_candidates": 1000,
                    "query_vector": embedding,
                }],
                "size": top_k,
            })
            items: List[SearchResult] = []
            for h in r.get("hits", {}).get("hits", []):
                s = h.get("_source", {})
                chunk = EsChunk.from_es_source(s, score=h.get("_score"))
                items.append(SearchResult(chunk=chunk, score=h.get("_score"), source="vector"))
            return items

        async def _bm25() -> List[SearchResult]:
            r = await es_search(index_doc, {
                "_source": {"excludes": ["emb"]},
                "query": {"bool": {"must": [{"match": {"doc_content": {"query": query}}}]}},
                "size": top_k,
            })
            items: List[SearchResult] = []
            for h in r.get("hits", {}).get("hits", []):
                s = h.get("_source", {})
                chunk = EsChunk.from_es_source(s, score=h.get("_score"))
                items.append(SearchResult(chunk=chunk, score=h.get("_score"), source="bm25"))
            return items

        # Run vector search and bm25 search in parallel
        vec_results, bm25_results = await asyncio.gather(_vec(), _bm25())

        all_results = vec_results + bm25_results

        # Use post_processor for RRF fusion
        fused_results = self.post_processor.process_search_results(all_results)

        # Sort by the new fused score
        fused_results.sort(key=lambda x: x.score, reverse=True)

        # Take top_k
        final_results = fused_results[:top_k]

        # Convert back to chunks and update scores
        final_chunks = []
        for res in final_results:
            chunk = res.chunk
            chunk.score = res.score
            final_chunks.append(chunk)

        return final_chunks

    async def get_documents_by_ids(self, collection_name: str, document_ids: List[str]) -> List[Document]:
        index_full = f"{collection_name}_{IndexSuffixDocFull}"
        documents = []
        if not document_ids:
            return documents

        sr = await es_search(index_full, {"query": {"terms": {"doc_id": document_ids}}, "size": len(document_ids)})

        for hit in sr.get("hits", {}).get("hits", []):
            src = hit.get("_source", {})
            doc = EsDocument.from_es_source(src)
            documents.append(doc)

        return documents
