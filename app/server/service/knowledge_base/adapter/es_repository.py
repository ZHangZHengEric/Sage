from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional

from core.client.es import (
    dims,
    document_delete,
    document_insert,
    index_clear,
    index_create,
    index_delete,
    index_exists,
)
from core.client.es import (
    search as es_search,
)
from sagents.rag.schema import Chunk, Document


class EsChunk(Chunk):
    """
    ES 存储的分块数据模型，继承自 sagents.rag.schema.Chunk
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
    ES 存储的完整文档模型，继承自 sagents.rag.schema.Document
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


IndexSuffixDoc = "doc"
IndexSuffixDocFull = "doc_full"
doc_index_suffix = [IndexSuffixDoc, IndexSuffixDocFull]


def _compact(d: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in d.items() if v is not None}


async def doc_index_create(index_name: str) -> None:
    for suffix, mapping in {IndexSuffixDoc: _doc_mapping(), IndexSuffixDocFull: _doc_full_mapping()}.items():
        if not await index_exists(index_name=f"{index_name}_{suffix}"):
            await index_create(index_name=f"{index_name}_{suffix}", mapping=mapping)


async def doc_document_insert(index_name: str, chunks: List[EsChunk], documents: List[EsDocument] | None = None) -> None:
    """
    插入文档和分块
    :param index_name: 索引前缀
    :param chunks: 分块列表 (插入 _doc 索引)
    :param documents: 完整文档列表 (插入 _doc_full 索引)，可选
    """
    # 1. Insert Chunks
    if chunks:
        doc_index = f"{index_name}_{IndexSuffixDoc}"
        chunk_sources = [chunk.to_es_source() for chunk in chunks]
        await document_insert(doc_index, chunk_sources)

    # 2. Insert Full Documents
    if documents:
        full_index = f"{index_name}_{IndexSuffixDocFull}"
        # Deduplicate by doc_id just in case
        doc_map = {doc.id: doc for doc in documents}
        doc_sources = [doc.to_es_source() for doc in doc_map.values()]
        if doc_sources:
            await document_insert(full_index, doc_sources)


async def doc_document_delete(index_name: str, doc_ids: List[str]) -> None:
    if not doc_ids:
        return
    for suffix in [IndexSuffixDoc, IndexSuffixDocFull]:
        idx = f"{index_name}_{suffix}"
        if await index_exists(idx):
            await document_delete(idx, {"terms": {"doc_id": doc_ids}})


async def get_documents_by_ids(index_name: str, doc_ids: List[str]) -> Dict[str, EsDocument]:
    index_full = f"{index_name}_{IndexSuffixDocFull}"
    res: Dict[str, EsDocument] = {}
    if not doc_ids:
        return res
    sr = await es_search(index_full, {"query": {"terms": {"doc_id": doc_ids}}, "size": len(doc_ids)})
    for hit in sr.get("hits", {}).get("hits", []):
        src = hit.get("_source", {})
        doc = EsDocument.from_es_source(src)
        res[doc.id] = doc
    return res


async def doc_document_search(index_name: str, question: str, emb: List[float], size: int) -> List[EsChunk]:
    index_doc = f"{index_name}_{IndexSuffixDoc}"
    exists = await index_exists(index_doc)
    if not exists:
        return []

    async def _vec():
        r = await es_search(index_doc, {
            "_source": {"excludes": ["emb"]},
            "knn": [{
                "field": "emb",
                "k": size,
                "num_candidates": 1000,
                "query_vector": emb,
            }],
            "size": size,
        })
        items: List[EsChunk] = []
        for h in r.get("hits", {}).get("hits", []):
            s = h.get("_source", {})
            chunk = EsChunk.from_es_source(s, score=h.get("_score"))
            chunk.score = h.get("_score")
            # chunk.source = "vec" # Chunk schema doesn't have 'source', SearchResult does.
            items.append(chunk)
        return items

    async def _bm25():
        r = await es_search(index_doc, {
            "_source": {"excludes": ["emb"]},
            "query": {"bool": {"must": [{"match": {"doc_content": {"query": question}}}]}},
            "size": size,
        })
        items: List[EsChunk] = []
        for h in r.get("hits", {}).get("hits", []):
            s = h.get("_source", {})
            chunk = EsChunk.from_es_source(s, score=h.get("_score"))
            chunk.score = h.get("_score")
            items.append(chunk)
        return items

    vec_docs, bm25_docs = await asyncio.gather(_vec(), _bm25())
    # Note: Calling function should handle merging/deduplication if needed, 
    # or rely on SearchResultPostProcessTool.
    # Here we just return all raw results.
    docs = vec_docs + bm25_docs
    return docs


async def doc_index_delete(index_name: str) -> None:
    for suffix in doc_index_suffix:
        idx = f"{index_name}_{suffix}"
        try:
            await index_delete(idx)
        except Exception:
            pass


async def doc_index_clear(index_name: str) -> None:
    for suffix in doc_index_suffix:
        idx = f"{index_name}_{suffix}"
        try:
            if await index_exists(idx):
                await index_clear(idx)
        except Exception:
            pass

async def doc_index_delete(index_name: str) -> None:
    for suffix in doc_index_suffix:
        idx = f"{index_name}_{suffix}"
        try:
            await index_delete(idx)
        except Exception:
            pass


async def doc_index_clear(index_name: str) -> None:
    for suffix in doc_index_suffix:
        idx = f"{index_name}_{suffix}"
        try:
            if await index_exists(idx):
                await index_clear(idx)
        except Exception:
            pass