"""
Minimax (海螺AI) 图片生成 Provider
"""

import os
import httpx
from typing import Optional
from .base import BaseImageProvider, GeneratedImage


class MinimaxProvider(BaseImageProvider):
    """Minimax (海螺AI) 图片生成 Provider"""

    name = "minimax"
    env_key = "MINIMAX_API_KEY"
    model_env_key = "MINIMAX_MODEL"  # 模型名称环境变量
    default_model = "image-01"
    supports_reference_image = True  # 支持参考图

    # 支持的宽高比映射
    ASPECT_RATIO_MAP = {
        "1:1": "1:1",
        "16:9": "16:9",
        "4:3": "4:3",
        "3:2": "3:2",
        "2:3": "2:3",
        "9:16": "9:16",
    }

    # API 端点
    API_ENDPOINT = "https://api.minimaxi.com/v1/image_generation"

    @classmethod
    def get_required_env_vars(cls) -> dict:
        """获取必需的环境变量说明"""
        return {
            cls.env_key: {
                "description": "Minimax API Key",
                "required": True,
                "url": "https://platform.minimaxi.com",
            },
            cls.model_env_key: {
                "description": "模型名称（如 image-01）",
                "required": True,
                "url": "https://platform.minimaxi.com/docs",
            },
        }

    @classmethod
    def get_config_example(cls) -> str:
        """获取配置示例"""
        return """# Minimax (海螺AI)
export MINIMAX_API_KEY=your_api_key_here
export MINIMAX_MODEL=image-01"""

    def __init__(self, api_key: str):
        super().__init__(api_key)
        # 模型名称在 generate_image 时动态获取
        self._model = None

    @property
    def model(self) -> str:
        """动态获取模型名称"""
        if self._model is None:
            self._model = os.environ.get(self.model_env_key, self.default_model)
        return self._model

    async def generate_image(
        self,
        prompt: str,
        aspect_ratio: str = "1:1",
        reference_image: Optional[str] = None,
        **kwargs
    ) -> GeneratedImage:
        """
        使用 Minimax 生成图片

        Args:
            prompt: 图片描述提示词
            aspect_ratio: 图片宽高比
            reference_image: 参考图 URL（支持网络图片链接）

        Returns:
            GeneratedImage: 生成的图片结果
        """
        # 构建请求头
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

        # 构建请求体
        payload = {
            "model": self.model,
            "prompt": prompt,
            "aspect_ratio": self.ASPECT_RATIO_MAP.get(aspect_ratio, "1:1"),
            "response_format": "base64",
        }

        # 如果提供了参考图，添加 subject_reference
        if reference_image and self.supports_reference_image:
            payload["subject_reference"] = [
                {
                    "type": "character",
                    "image_file": reference_image,
                }
            ]

        async with httpx.AsyncClient() as client:
            response = await client.post(
                self.API_ENDPOINT,
                headers=headers,
                json=payload,
                timeout=60.0  # 图片生成可能需要较长时间
            )

            if response.status_code == 401 or response.status_code == 403:
                raise Exception(f"Minimax API Key 无效或没有权限，请检查环境变量 {self.env_key}")

            response.raise_for_status()
            data = response.json()

            # 解析响应数据
            images = data.get("data", {}).get("image_base64", [])

            if not images:
                raise Exception("Minimax 返回的图片数据为空")

            # 返回第一张图片
            return GeneratedImage(
                image_data=images[0],
                image_format="jpeg",
                is_base64=True,
                prompt=prompt,
                model=self.model,
                provider=self.name
            )
