"""
ES 文档模型
"""

from __future__ import annotations

from pydantic import BaseModel
import asyncio
from typing import List, Dict, Any, Optional
from datetime import datetime
from core.client.es_client import (
    dims,
    index_create,
    document_insert,
    document_delete,
    search as es_search,
    index_exists,
    index_delete,
    index_clear,
)


class DocDocument(BaseModel):
    doc_id: str
    main_doc_id: Optional[str] = None
    emb: List[float] = []
    score: Optional[float] = None
    source: Optional[str] = None
    doc_segment_id: Optional[str] = None
    doc_content: Optional[str] = None
    origin_content: Optional[str] = None
    start: Optional[int] = None
    end: Optional[int] = None
    full_content: Optional[str] = None
    path: Optional[str] = None
    title: Optional[str] = None
    metadata: Dict[str, Any] | None = None
    sender: Optional[str] = None
    receiver: List[str] | None = None
    date: Optional[datetime] = None
    is_attachment: Optional[bool] = None

    def to_doc_source(self) -> Dict[str, Any]:
        return _compact(
            {
                "doc_id": self.doc_id,
                "main_doc_id": self.main_doc_id,
                "emb": self.emb,
                "doc_segment_id": self.doc_segment_id,
                "doc_content": self.doc_content,
                "origin_content": self.origin_content,
                "start": self.start,
                "end": self.end,
                "path": self.path,
                "title": self.title,
                "metadata": self.metadata,
                "sender": self.sender,
                "receiver": self.receiver,
                "date": self.date.isoformat() if self.date else None,
                "is_attachment": self.is_attachment,
            }
        )

    def to_full_source(self) -> Dict[str, Any]:
        return _compact(
            {
                "doc_id": self.doc_id,
                "full_content": self.full_content,
                "origin_content": self.origin_content,
                "path": self.path,
                "title": self.title,
                "metadata": self.metadata,
                "main_doc_id": self.main_doc_id,
            }
        )


def _doc_mapping() -> Dict[str, Any]:
    return {
        "properties": {
            "doc_id": {"type": "keyword", "index": False},
            "doc_segment_id": {"type": "keyword", "index": False},
            "doc_content": {
                "index": True,
                "type": "text",
                "analyzer": "my_ana",
                "similarity": "my_similarity",
            },
            "emb": {"type": "dense_vector", "dims": dims(), "similarity": "cosine"},
            "end": {"type": "long"},
            "start": {"type": "long"},
        }
    }


def _doc_full_mapping() -> Dict[str, Any]:
    return {
        "properties": {
            "doc_id": {"type": "keyword", "index": False},
            "full_content": {
                "index": True,
                "type": "text",
                "analyzer": "my_ana",
                "similarity": "my_similarity",
            },
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


def _to_doc_source(doc: DocDocument) -> Dict[str, Any]:
    return doc.to_doc_source()


def _to_doc_full_source(doc: DocDocument) -> Dict[str, Any]:
    return doc.to_full_source()


async def doc_index_create(index_name: str) -> None:
    for suffix, mapping in {
        IndexSuffixDoc: _doc_mapping(),
        IndexSuffixDocFull: _doc_full_mapping(),
    }.items():
        await index_create(index_name=f"{index_name}_{suffix}", mapping=mapping)


async def doc_document_insert(index_name: str, docs: List[DocDocument]) -> None:
    if not docs:
        return
    doc_index = f"{index_name}_{IndexSuffixDoc}"
    full_index = f"{index_name}_{IndexSuffixDocFull}"
    doc_docs: List[Dict[str, Any]] = []
    for d in docs:
        doc_docs.append(_to_doc_source(d))
    await document_insert(doc_index, doc_docs)
    doc_full_map: Dict[str, Dict[str, Any]] = {}
    for d in docs:
        if d.full_content:
            if d.doc_id not in doc_full_map:
                doc_full_map[d.doc_id] = _to_doc_full_source(d)
    if doc_full_map:
        await document_insert(full_index, list(doc_full_map.values()))


async def doc_document_delete(index_name: str, doc_ids: List[str]) -> None:
    if not doc_ids:
        return
    for suffix in [IndexSuffixDoc, IndexSuffixDocFull]:
        idx = f"{index_name}_{suffix}"
        if await index_exists(idx):
            await document_delete(idx, {"terms": {"doc_id": doc_ids}})


async def get_documents_by_ids(
    index_name: str, doc_ids: List[str]
) -> Dict[str, DocDocument]:
    index_full = f"{index_name}_{IndexSuffixDocFull}"
    res: Dict[str, DocDocument] = {}
    if not doc_ids:
        return res
    sr = await es_search(
        index_full, {"query": {"terms": {"doc_id": doc_ids}}, "size": len(doc_ids)}
    )
    for hit in sr.get("hits", {}).get("hits", []):
        src = hit.get("_source", {})
        doc = DocDocument(
            doc_id=src.get("doc_id"),
            full_content=src.get("full_content"),
            origin_content=src.get("origin_content"),
            path=src.get("path"),
            title=src.get("title"),
            metadata=src.get("metadata"),
            main_doc_id=src.get("main_doc_id"),
            sender=src.get("sender"),
            receiver=src.get("receiver"),
            date=src.get("date"),
        )
        res[doc.doc_id] = doc
    return res


async def doc_search(
    index_name: str, question: str, emb: List[float], size: int
) -> List[DocDocument]:
    index_doc = f"{index_name}_{IndexSuffixDoc}"

    async def _vec():
        r = await es_search(
            index_doc,
            {
                "_source": {"excludes": ["emb"]},
                "knn": [
                    {
                        "field": "emb",
                        "k": size,
                        "num_candidates": 1000,
                        "query_vector": emb,
                    }
                ],
                "size": size,
            },
        )
        items: List[DocDocument] = []
        for h in r.get("hits", {}).get("hits", []):
            s = h.get("_source", {})
            dd = DocDocument(
                doc_id=s.get("doc_id"),
                main_doc_id=s.get("main_doc_id"),
                emb=s.get("emb", []),
                doc_segment_id=s.get("doc_segment_id"),
                doc_content=s.get("doc_content"),
                origin_content=s.get("origin_content"),
                start=s.get("start"),
                end=s.get("end"),
                path=s.get("path"),
                title=s.get("title"),
                metadata=s.get("metadata"),
            )
            dd.score = h.get("_score")
            dd.source = "vec"
            items.append(dd)
        return items

    async def _bm25():
        r = await es_search(
            index_doc,
            {
                "_source": {"excludes": ["emb"]},
                "query": {
                    "bool": {"must": [{"match": {"doc_content": {"query": question}}}]}
                },
                "size": size,
            },
        )
        items: List[DocDocument] = []
        for h in r.get("hits", {}).get("hits", []):
            s = h.get("_source", {})
            dd = DocDocument(
                doc_id=s.get("doc_id"),
                main_doc_id=s.get("main_doc_id"),
                emb=s.get("emb", []),
                doc_segment_id=s.get("doc_segment_id"),
                doc_content=s.get("doc_content"),
                origin_content=s.get("origin_content"),
                start=s.get("start"),
                end=s.get("end"),
                path=s.get("path"),
                title=s.get("title"),
                metadata=s.get("metadata"),
            )
            dd.score = h.get("_score")
            dd.source = "bm25"
            items.append(dd)
        return items

    vec_docs, bm25_docs = await asyncio.gather(_vec(), _bm25())
    docs = vec_docs + bm25_docs
    if not docs:
        return docs
    doc_ids = list({d.doc_id for d in docs if d.doc_id})
    full_map = await get_documents_by_ids(index_name, doc_ids)
    for d in docs:
        if d.doc_id in full_map:
            d.full_content = full_map[d.doc_id].full_content
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
