from typing import List
from sagents.rag.interface.vector_store import VectorStore
from sagents.rag.schema import Document, Chunk, SearchResult
from sagents.rag.post_process import SearchResultPostProcessTool
from app.server.service.knowledge_base.adapter.es_repository import (
    EsChunk,
    EsDocument,
    doc_document_insert,
    doc_document_delete,
    doc_index_clear,
    doc_index_create,
    doc_document_search,
    get_documents_by_ids
)

class EsVectorStore(VectorStore):
    """
    Adapter for the existing ElasticSearch service.
    """
    def __init__(self):
        self.post_processor = SearchResultPostProcessTool()

    async def create_collection(self, collection_name: str) -> None:
        await doc_index_create(collection_name)

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
        
        if es_chunks or es_docs:
            await doc_document_insert(collection_name, chunks=es_chunks, documents=es_docs)

    async def delete_documents(self, collection_name: str, document_ids: List[str]) -> None:
        await doc_document_delete(collection_name, document_ids)

    async def clear_collection(self, collection_name: str) -> None:
        await doc_index_clear(collection_name)

    async def search(self, collection_name: str, query: str, embedding: List[float], top_k: int = 5) -> List[Chunk]:
        # The existing doc_document_search returns List[EsChunk]
        # It performs both vector search and keyword search (BM25)
        es_results = await doc_document_search(collection_name, query, embedding, top_k)
        
        # Convert to SearchResult for post-processing
        search_results = []
        for i, res in enumerate(es_results):
            # Infer source if possible, otherwise rely on order or assume mixed
            # Note: doc_document_search implementation currently doesn't set 'source' explicitly in EsChunk
            # But we can update EsChunk or handle it here. 
            # For now, we wrap it into SearchResult.
            
            # We assume the results are raw and need RRF.
            # But doc_document_search returns a concatenated list of vec + bm25.
            # We need to distinguish them if we want to do proper RRF.
            # However, doc_document_search in doc.py just returns `vec_docs + bm25_docs`.
            # We can't easily distinguish unless we add a 'source' field to EsChunk or handle it inside doc.py
            
            # Let's assume doc.py handles everything or we trust the scores?
            # Actually doc.py just returns a list. RRF works best if we know sources.
            # Since we can't change doc.py's return signature easily to be Dict[str, List], 
            # let's proceed with basic SearchResult wrapping.
            
            # Temporary hack: we don't know the source here. 
            # But since we want to return Chunks, and RRF is optional inside VectorStore (usually managed by Manager),
            # wait, VectorStore.search returns List[Chunk].
            # Manager might do RRF if it calls multiple stores? No, Manager calls vector_store.search.
            
            # If we want to use RRF *inside* this store adapter because it does hybrid search internally:
            # We should have doc_document_search return source info.
            # But for now, let's just return the chunks sorted by score.
            pass

        # Since doc_document_search returns raw concatenated list, we should probably deduplicate/sort.
        # Simple deduplication by ID
        unique_map = {}
        for chunk in es_results:
            if chunk.id not in unique_map:
                unique_map[chunk.id] = chunk
            else:
                # Max score strategy
                if (chunk.score or 0) > (unique_map[chunk.id].score or 0):
                    unique_map[chunk.id] = chunk
        
        sorted_chunks = sorted(unique_map.values(), key=lambda x: x.score or 0, reverse=True)
        return sorted_chunks[:top_k]

    async def get_documents_by_ids(self, collection_name: str, document_ids: List[str]) -> List[Document]:
        es_docs_map = await get_documents_by_ids(collection_name, document_ids)
        documents = []
        for doc_id, es_doc in es_docs_map.items():
            # es_doc is EsDocument which inherits Document
            # We can cast or copy. Since EsDocument is a Document, we can use it directly?
            # Yes, but let's return base Document to be safe with types if needed, 
            # though inheritance allows returning subclass.
            documents.append(es_doc)
        return documents
