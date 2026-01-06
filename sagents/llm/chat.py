from __future__ import annotations
from typing import Optional
from openai import AsyncOpenAI
from sagents.utils.logger import logger

class OpenAIChat:
    """
    OpenAI Chat 客户端封装
    """
    def __init__(
        self, 
        api_key: str, 
        base_url: Optional[str] = "https://api.openai.com/v1", 
        model_name: Optional[str] = "gpt-4o"
    ):
        self.model_name = model_name
        self.client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        # 将 model_name 绑定到 client 上，方便后续获取（虽然这不是标准做法，但保持兼容性）
        self.client.model_name = model_name
        

    @property
    def raw_client(self) -> AsyncOpenAI:
        return self.client

    async def close(self) -> None:
        """
        关闭客户端
        """
        try:
            await self.client.close()
        except Exception as e:
            logger.error(f"Failed to close OpenAIChat client: {e}")

