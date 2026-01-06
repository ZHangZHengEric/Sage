from __future__ import annotations
from typing import List, Optional
from openai import AsyncOpenAI
from sagents.utils.logger import logger
from sagents.rag.interface.embedding import EmbeddingModel

class OpenAIEmbedding(EmbeddingModel):
    """
    OpenAI Embedding 客户端封装，实现 EmbeddingModel 接口
    """
    def __init__(
        self, 
        api_key: str, 
        base_url: Optional[str] = None, 
        model_name: str = "text-embedding-3-large", 
        dims: int = 1024
    ):
        self.model_name = model_name
        self.dims = dims
        if base_url:
            self.client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        else:
            self.client = AsyncOpenAI(api_key=api_key)
        

    async def embed_documents(self, texts: List[str]) -> List[List[float]]:
        """
        批量生成向量
        """
        results: List[List[float]] = []
        # OpenAI 限制每批次大小，这里简单分批
        chunk_size = 10
        
        for i in range(0, len(texts or []), chunk_size):
            batch = texts[i : i + chunk_size]
            try:
                r = await self.client.embeddings.create(
                    model=self.model_name, input=batch, dimensions=self.dims
                )
                results.extend(item.embedding for item in r.data)
            except Exception as e:
                logger.error(f"Embedding batch failed: {e}")
                # 即使失败也尽量保证返回长度一致？或者抛出异常。这里抛出异常让上层处理。
                raise e

        return results

    async def embed_query(self, text: str) -> List[float]:
        """
        生成单个查询向量
        """
        res = await self.embed_documents([text])
        if not res:
            raise RuntimeError("Failed to embed query")
        return res[0]

    async def close(self) -> None:
        """
        关闭客户端
        """
        try:
            await self.client.close()
        except Exception as e:
            logger.error(f"Failed to close OpenAIEmbedding client: {e}")

