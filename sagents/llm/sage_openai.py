"""
SageAsyncOpenAI - 支持多模型模式的 OpenAI 客户端封装

使用方式与 AsyncOpenAI 完全兼容，新增 model_type 参数：
- model_type="standard" (默认): 使用标准模型
- model_type="fast": 使用快速模型（如果配置了）
"""
from typing import Any, AsyncGenerator, Dict, Optional
from openai import AsyncOpenAI
from openai.types.chat import ChatCompletionChunk
from sagents.utils.logger import logger
from sagents.llm.capabilities import sanitize_model_request_kwargs


class SageAsyncOpenAI:
    """
    Sage 封装的 AsyncOpenAI，支持标准和快速两种模型模式
    
    特点：
    1. 完全兼容 AsyncOpenAI 的接口
    2. 通过 model_type 参数切换模型
    3. 未配置快速模型时，自动回退到标准模型
    """
    
    def __init__(
        self,
        standard_client: AsyncOpenAI,
        fast_client: Optional[AsyncOpenAI] = None,
        model_capabilities: Optional[Dict[str, Any]] = None,
        model_name: Optional[str] = None,
        fast_model_name: Optional[str] = None,
    ):
        """
        初始化 SageAsyncOpenAI
        
        Args:
            standard_client: 标准模型客户端（必须）
            fast_client: 快速模型客户端（可选）
        """
        self._standard = standard_client
        self._fast = fast_client
        self.model_capabilities: Dict[str, Any] = model_capabilities or {}
        self.model_name = model_name or getattr(standard_client, 'model_name', 'unknown')
        self.fast_model_name = fast_model_name
        
        # 暴露 base_url 和 api_key 属性（从底层客户端获取）
        self.base_url = getattr(standard_client, '_base_url', None) or getattr(standard_client, 'base_url', None)
        self.api_key = getattr(standard_client, '_api_key', None) or getattr(standard_client, 'api_key', None)

        # 常见能力位直接挂到对象上，便于调用点与日志中读取。
        self.supports_multimodal = bool(self.model_capabilities.get("supports_multimodal", False))
        self.supports_structured_output = bool(self.model_capabilities.get("supports_structured_output", False))
        self.supports_image_input = bool(self.model_capabilities.get("supports_multimodal", False))

    def get_model_capabilities(self) -> Dict[str, Any]:
        """返回当前客户端绑定的模型能力报告。"""
        return dict(self.model_capabilities)
    
    @property
    def chat(self) -> "SageChatCompletions":
        """获取封装的 chat.completions 接口"""
        return SageChatCompletions(self)
    
    async def close(self) -> None:
        """关闭所有客户端连接"""
        try:
            await self._standard.close()
        except Exception as e:
            logger.error(f"Failed to close standard client: {e}")
        
        if self._fast:
            try:
                await self._fast.close()
            except Exception as e:
                logger.error(f"Failed to close fast client: {e}")


class SageChatCompletions:
    """封装的 chat.completions 接口"""
    
    def __init__(self, sage_client: SageAsyncOpenAI):
        self._sage = sage_client
        # 添加 completions 属性指向自己，兼容 ObservableChat 的访问模式
        self.completions = self
    
    def create(
        self,
        *,
        model_type: str = "standard",  # 新增参数：standard 或 fast
        **kwargs
    ) -> AsyncGenerator[ChatCompletionChunk, None]:
        """
        创建聊天完成请求
        
        Args:
            model_type: 模型类型，"standard" 或 "fast"，默认 "standard"
            **kwargs: 其他参数，与 AsyncOpenAI.chat.completions.create 相同
        
        Returns:
            AsyncGenerator: 流式响应
        """
        # 选择客户端
        if model_type == "fast" and self._sage._fast:
            client = self._sage._fast
            logger.debug(f"Using FAST model: {self._sage.fast_model_name or 'unknown'}")
        else:
            client = self._sage._standard
            if model_type == "fast":
                logger.debug("Fast model not configured, falling back to standard")
        
        # 移除内部使用的参数，避免传递给 OpenAI API
        kwargs.pop('fast_api_key', None)
        kwargs.pop('fast_base_url', None)
        kwargs.pop('fast_model_name', None)
        kwargs = sanitize_model_request_kwargs(
            kwargs,
            client=self._sage,
            model_config=self._sage.model_capabilities,
        )
        
        # 调用底层客户端
        return client.chat.completions.create(**kwargs)
