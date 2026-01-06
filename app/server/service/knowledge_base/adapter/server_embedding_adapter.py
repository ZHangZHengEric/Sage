from typing import List
from sagents.rag.interface.embedding import EmbeddingModel
from app.server.core.client.embed import get_embed_client

class ServerEmbeddingAdapter(EmbeddingModel):
    """
    Adapter for the existing server-side embedding service.
    Proxies calls to the global OpenAIEmbedding instance managed by Server.
    """
    async def embed_documents(self, texts: List[str]) -> List[List[float]]:
        client = get_embed_client()
        return await client.embed_documents(texts)

    async def embed_query(self, text: str) -> List[float]:
        client = get_embed_client()
        return await client.embed_query(text)

