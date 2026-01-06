from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field

class Chunk(BaseModel):
    """
    Represents a segment of a document, usually used for vector search.
    """
    id: str
    content: str
    document_id: str
    embedding: Optional[List[float]] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    score: Optional[float] = None  # Similarity score

class Document(BaseModel):
    """
    Represents a full document (e.g. a file).
    """
    id: str
    content: str
    metadata: Dict[str, Any] = Field(default_factory=dict)
    chunks: List[Chunk] = Field(default_factory=list)

class SearchResult(BaseModel):
    """
    Represents a search result item, wrapping a Chunk with additional search context.
    """
    chunk: Chunk
    source: str = "vector" # e.g., 'vector', 'bm25'
    score: float = 0.0
    ranking: Optional[int] = None
    normalized_score: Optional[float] = None
