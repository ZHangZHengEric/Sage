from __future__ import annotations
import itertools
from collections import defaultdict
from typing import Optional, Dict, List, Any
from openai import AsyncOpenAI
from sagents.utils.logger import logger
from sagents.llm.sage_openai import SageAsyncOpenAI


class OpenAIChat:
    """
    OpenAI Chat 客户端封装
    支持标准模型和快速模型双配置
    """
    def __init__(
        self,
        api_key: str,
        base_url: Optional[str] = "https://api.openai.com/v1",
        model_name: Optional[str] = "gpt-4o",
        # 快速模型配置（可选）
        fast_api_key: Optional[str] = None,
        fast_base_url: Optional[str] = None,
        fast_model_name: Optional[str] = None,
        model_capabilities: Optional[Dict[str, Any]] = None,
    ):
        self.model_name = model_name
        self.model_capabilities = model_capabilities or {}
        
        # 创建标准模型客户端
        self._standard_client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        
        # 创建快速模型客户端（如果配置了）
        self._fast_client = None
        if fast_model_name:
            fast_key = fast_api_key or api_key
            fast_url = fast_base_url or base_url
            self._fast_client = AsyncOpenAI(api_key=fast_key, base_url=fast_url)
            logger.info(f"Fast model configured: {fast_model_name}")
        
        # 创建 SageAsyncOpenAI 实例
        self._sage_client = SageAsyncOpenAI(
            standard_client=self._standard_client,
            fast_client=self._fast_client,
            model_capabilities=self.model_capabilities,
            model_name=model_name,
            fast_model_name=fast_model_name,
        )

    @property
    def raw_client(self) -> SageAsyncOpenAI:
        """返回 SageAsyncOpenAI 实例"""
        return self._sage_client

    async def close(self) -> None:
        """
        关闭客户端
        """
        try:
            await self._sage_client.close()
        except Exception as e:
            logger.error(f"Failed to close OpenAIChat client: {e}")


class ChatClientPool:
    """
    Chat 客户端代理池
    支持多模型、多Provider、轮询
    """
    def __init__(self):
        # Map: model_name -> List[OpenAIChat]
        self._clients: Dict[str, List[OpenAIChat]] = defaultdict(list)
        # Map: model_name -> Iterator
        self._iterators: Dict[str, Any] = {}
        self.default_model_name: Optional[str] = None

    def add_client(self, client: OpenAIChat):
        if not client.model_name:
            logger.warning("Client has no model_name, skipping add to pool")
            return
        
        self._clients[client.model_name].append(client)
        
        # Reset iterator for this model to include new client
        self._iterators[client.model_name] = itertools.cycle(self._clients[client.model_name])
        logger.debug(f"Added client for model {client.model_name} to pool. Total: {len(self._clients[client.model_name])}")

    def set_default_model(self, model_name: str):
        self.default_model_name = model_name
        logger.debug(f"Set default model to {model_name}")

    def get_client(self, model_name: Optional[str] = None) -> Optional[OpenAIChat]:
        """
        获取客户端实例
        :param model_name: 指定模型名称，如果为 None 则使用默认模型
        :return: OpenAIChat 实例 or None
        """
        target_model = model_name or self.default_model_name
        
        # 如果没有指定 target_model，且池子不为空，尝试取第一个模型
        if not target_model and self._clients:
            target_model = next(iter(self._clients.keys()))

        if not target_model:
            logger.warning("No model specified and no clients in pool")
            return None

        iterator = self._iterators.get(target_model)
        if not iterator:
             # 如果请求的模型没有，尝试回退到默认模型
             if self.default_model_name and self.default_model_name in self._iterators:
                 logger.debug(f"Model {target_model} not found, falling back to default {self.default_model_name}")
                 target_model = self.default_model_name
                 iterator = self._iterators[target_model]
             else:
                 logger.warning(f"Model {target_model} not found in pool and no fallback available")
                 return None
        
        return next(iterator)

    async def close(self):
        for model, clients in self._clients.items():
            for client in clients:
                await client.close()
        self._clients.clear()
        self._iterators.clear()
