import os
import uuid
import asyncio
from typing import List, Dict, Any, Optional
from loguru import logger

# Import ChromaDB
try:
    import chromadb
    from chromadb.config import Settings
except ImportError:
    chromadb = None

# Import interfaces
from sagents.retrieve_engine.interface.vector_store import VectorStore
from sagents.retrieve_engine.schema import Chunk, Document

# ChromaDB Client
CHROMA_CLIENT = None

def get_chroma_client():
    global CHROMA_CLIENT
    if CHROMA_CLIENT is None:
        db_path = os.path.join(os.getcwd(), "vectors")
        os.makedirs(db_path, exist_ok=True)
        # Using persistent client for local storage
        CHROMA_CLIENT = chromadb.PersistentClient(path=db_path)
    return CHROMA_CLIENT

class LocalVectorStore(VectorStore):
    """
    A local vector store implementation using ChromaDB to replace ElasticSearch.
    """
    def __init__(self):
        self.client = get_chroma_client()
        self.default_ef = 10  # Default embedding function or None if embeddings provided

    async def create_collection(self, collection_name: str) -> None:
        try:
            self.client.get_or_create_collection(name=collection_name)
        except Exception as e:
            logger.error(f"Failed to create collection {collection_name}: {e}")

    async def add_documents(self, collection_name: str, documents: List[Document]) -> None:
        """
        Add documents to ChromaDB collection.
        Documents contain chunks with embeddings.
        """
        if not documents:
            return

        collection = self.client.get_or_create_collection(name=collection_name)
        
        ids = []
        embeddings = []
        metadatas = []
        documents_text = []

        for doc in documents:
            for chunk in doc.chunks:
                # Chroma requires unique IDs per chunk
                ids.append(chunk.id)
                embeddings.append(chunk.embedding)
                
                # Create metadata
                meta = chunk.metadata.copy() if chunk.metadata else {}
                meta.update({
                    "document_id": doc.id,
                    "doc_segment_id": chunk.id,
                    "score": chunk.score or 0.0,
                    # Add document level metadata
                    "origin_content": doc.metadata.get("origin_content", ""),
                    "path": doc.metadata.get("path", ""),
                    "title": doc.metadata.get("title", ""),
                    "main_doc_id": doc.metadata.get("main_doc_id", "")
                })
                metadatas.append(meta)
                documents_text.append(chunk.content)

        if ids:
            collection.add(
                ids=ids,
                embeddings=embeddings,
                metadatas=metadatas,
                documents=documents_text
            )
            logger.info(f"Added {len(ids)} chunks to collection {collection_name}")

    async def delete_documents(self, collection_name: str, document_ids: List[str]) -> None:
        if not document_ids:
            return
            
        try:
            collection = self.client.get_collection(name=collection_name)
            # Delete by document_id metadata filter
            collection.delete(where={"document_id": {"$in": document_ids}})
            logger.info(f"Deleted documents {document_ids} from {collection_name}")
        except Exception as e:
            logger.error(f"Failed to delete documents: {e}")

    async def clear_collection(self, collection_name: str) -> None:
        try:
            self.client.delete_collection(name=collection_name)
            self.client.create_collection(name=collection_name)
            logger.info(f"Cleared collection {collection_name}")
        except Exception as e:
            logger.error(f"Failed to clear collection: {e}")

    async def search(self, collection_name: str, query: str, embedding: List[float], top_k: int = 5) -> List[Chunk]:
        """
        Search for similar chunks using vector similarity.
        """
        try:
            collection = self.client.get_collection(name=collection_name)
        except Exception:
            return []

        results = collection.query(
            query_embeddings=[embedding],
            n_results=top_k,
            include=["metadatas", "documents", "distances"]
        )
        
        chunks = []
        if not results['ids']:
            return chunks

        # Chroma returns list of lists (one per query)
        ids = results['ids'][0]
        metadatas = results['metadatas'][0]
        docs = results['documents'][0]
        distances = results['distances'][0]

        for i in range(len(ids)):
            meta = metadatas[i]
            # Chroma returns distance (lower is better), we need score (higher is better)
            # Simple conversion: 1 / (1 + distance) or just pass distance if handled downstream
            score = 1.0 / (1.0 + distances[i]) 
            
            chunk = Chunk(
                id=ids[i],
                content=docs[i],
                document_id=meta.get("document_id", ""),
                embedding=[], # We don't fetch embeddings back to save bandwidth
                metadata=meta,
                score=score
            )
            chunks.append(chunk)
            
        return chunks

    async def get_documents_by_ids(self, collection_name: str, document_ids: List[str]) -> List[Document]:
        """
        Retrieve full documents by IDs. 
        Note: Chroma stores chunks, not full documents structure.
        We need to reconstruct documents from chunks or store full docs separately.
        Assuming we store chunks, we can aggregate them.
        """
        try:
            collection = self.client.get_collection(name=collection_name)
        except Exception:
            return []

        # Query by document_id
        results = collection.get(
            where={"document_id": {"$in": document_ids}},
            include=["metadatas", "documents"]
        )

        doc_map = {}
        
        ids = results['ids']
        metadatas = results['metadatas']
        contents = results['documents']
        
        for i, chunk_id in enumerate(ids):
            meta = metadatas[i]
            doc_id = meta.get("document_id")
            if not doc_id:
                continue
                
            if doc_id not in doc_map:
                doc_map[doc_id] = Document(
                    id=doc_id,
                    content="", # Will aggregate
                    metadata=meta,
                    chunks=[]
                )
            
            chunk = Chunk(
                id=chunk_id,
                content=contents[i],
                document_id=doc_id,
                metadata=meta
            )
            doc_map[doc_id].chunks.append(chunk)
            # Create full content by joining chunks (simple heuristic)
            # Real implementation might store full content separately in SQLite or a specific "full_doc" collection
            doc_map[doc_id].content += contents[i] + "\n"

        return list(doc_map.values())
