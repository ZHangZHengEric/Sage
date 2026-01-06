from typing import List, Optional
from sagents.rag.schema import Document, Chunk
from sagents.rag.interface.vector_store import VectorStore
from sagents.rag.interface.embedding import EmbeddingModel
from sagents.rag.interface.splitter import BaseSplitter
from sagents.rag.splitter import DefaultSplitter
import logging

logger = logging.getLogger(__name__)

class KnowledgeManager:
    """
    Manages the knowledge base operations: ingestion, retrieval, etc.
    This class orchestrates the splitter, embedding model, and vector store.
    """

    def __init__(self, vector_store: VectorStore, embedding_model: EmbeddingModel, splitter: Optional[BaseSplitter] = None):
        self.vector_store = vector_store
        self.embedding_model = embedding_model
        self.splitter = splitter or DefaultSplitter()

    async def add_documents(self, collection_name: str, documents: List[Document]):
        """
        Process and add documents to the knowledge base.
        1. Split documents into chunks.
        2. Generate embeddings for chunks.
        3. Store documents and chunks in vector store.
        """
        # Ensure collection exists
        await self.vector_store.create_collection(collection_name)

        chunks_to_embed = []
        
        # 1. Split
        for doc in documents:
            if not doc.content:
                continue
                
            # Use the injected splitter
            sentences = await self.splitter.split_text(doc.content)
            
            doc.chunks = []
            for s in sentences:
                chunk = Chunk(
                    id=s.get("passage_id"), # Or generate a new ID if passage_id is not unique enough
                    content=s.get("passage_content"),
                    document_id=doc.id,
                    metadata={
                        "start": s.get("start"),
                        "end": s.get("end"),
                        **doc.metadata
                    }
                )
                doc.chunks.append(chunk)
                chunks_to_embed.append(chunk)
        
        # 2. Embed
        if chunks_to_embed:
            texts = [c.content for c in chunks_to_embed]
            embeddings = await self.embedding_model.embed_documents(texts)
            for i, chunk in enumerate(chunks_to_embed):
                chunk.embedding = embeddings[i]

        # 3. Store
        await self.vector_store.add_documents(collection_name, documents)
        logger.info(f"Added {len(documents)} documents with {len(chunks_to_embed)} chunks to collection {collection_name}")

    async def search(self, collection_name: str, query: str, top_k: int = 5) -> List[Chunk]:
        """
        Search for relevant chunks using the query.
        """
        # Generate query embedding
        query_embedding = await self.embedding_model.embed_query(query)
        
        # Search in vector store
        results = await self.vector_store.search(collection_name, query, query_embedding, top_k)
        return results

    async def delete_documents(self, collection_name: str, document_ids: List[str]):
        """
        Delete documents from the knowledge base.
        """
        await self.vector_store.delete_documents(collection_name, document_ids)

    async def get_documents_by_ids(self, collection_name: str, document_ids: List[str]) -> List[Document]:
        """
        Retrieve full documents by their IDs.
        """
        return await self.vector_store.get_documents_by_ids(collection_name, document_ids)

    async def clear_collection(self, collection_name: str):
        """
        Clear the entire collection.
        """
        await self.vector_store.clear_collection(collection_name)
