from abc import ABC, abstractmethod
from typing import List
from sagents.retrieve_engine.schema import Document, Chunk

class VectorStore(ABC):
    """
    Abstract base class for vector storage.
    """

    @abstractmethod
    async def create_collection(self, collection_name: str) -> None:
        """Create a collection (or index) if it doesn't exist."""
        pass

    @abstractmethod
    async def add_documents(self, collection_name: str, documents: List[Document]) -> None:
        """
        Add documents to the store. 
        Implementation should handle chunk storage and vector indexing.
        """
        pass

    @abstractmethod
    async def delete_documents(self, collection_name: str, document_ids: List[str]) -> None:
        """Delete documents by their IDs."""
        pass
    
    @abstractmethod
    async def clear_collection(self, collection_name: str) -> None:
        """Clear all data in the collection."""
        pass

    @abstractmethod
    async def search(self, collection_name: str, query: str, embedding: List[float], top_k: int = 5) -> List[Chunk]:
        """
        Search for relevant chunks.
        """
        pass

    @abstractmethod
    async def get_documents_by_ids(self, collection_name: str, document_ids: List[str]) -> List[Document]:
        """
        Retrieve full documents by their IDs.
        """
        pass
