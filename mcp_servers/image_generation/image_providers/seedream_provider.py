"""
Seedream (火山引擎/方舟大模型) 图片生成 Provider

文档: https://www.volcengine.com/docs/82379/1541523
"""

import os
import httpx
from typing import Optional
from .base import BaseImageProvider, GeneratedImage


class SeedreamProvider(BaseImageProvider):
    """Seedream (火山引擎) 图片生成 Provider"""

    name = "seedream"
    env_key = "SEEDREAM_API_KEY"  # 方舟平台 API Key
    model_env_key = "SEEDREAM_MODEL"  # 模型名称环境变量
    default_model = "doubao-seedream-5.0-lite"
    supports_reference_image = True  # 支持图生图

    # API 端点
    API_ENDPOINT = "https://ark.cn-beijing.volces.com/api/v3/images/generations"

    # 支持的尺寸映射 (宽度x高度)
    SIZE_MAP = {
        "1:1": "2048x2048",
        "4:3": "2304x1728",
        "3:4": "1728x2304",
        "16:9": "2848x1600",
        "9:16": "1600x2848",
        "3:2": "2496x1664",
        "2:3": "1664x2496",
        "21:9": "3136x1344",
    }

    @classmethod
    def get_required_env_vars(cls) -> dict:
        """获取必需的环境变量说明"""
        return {
            cls.env_key: {
                "description": "火山引擎方舟平台 API Key",
                "required": True,
                "url": "https://console.volcengine.com/ark",
            },
            cls.model_env_key: {
                "description": "模型名称（如 doubao-seedream-5.0-lite, doubao-seedream-4.5, doubao-seedream-3.0-t2i）",
                "required": True,
                "url": "https://www.volcengine.com/docs/82379/1541523",
            },
        }

    @classmethod
    def get_config_example(cls) -> str:
        """获取配置示例"""
        return """# Seedream (火山引擎/方舟大模型)
export SEEDREAM_API_KEY=your_api_key_here
export SEEDREAM_MODEL=doubao-seedream-5.0-lite"""

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
        使用 Seedream 生成图片

        Args:
            prompt: 图片描述提示词（建议不超过300个汉字或600个英文单词）
            aspect_ratio: 图片宽高比
            reference_image: 参考图 URL 或 Base64

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
        }

        # 添加尺寸参数
        size = self.SIZE_MAP.get(aspect_ratio, "2048x2048")
        payload["size"] = size

        # 如果提供了参考图，添加 image 参数
        if reference_image and self.supports_reference_image:
            payload["image"] = reference_image

        async with httpx.AsyncClient() as client:
            response = await client.post(
                self.API_ENDPOINT,
                headers=headers,
                json=payload,
                timeout=60.0
            )

            if response.status_code == 401 or response.status_code == 403:
                raise Exception(f"Seedream API Key 无效或没有权限，请检查环境变量 {self.env_key}")

            response.raise_for_status()
            data = response.json()

            # 解析响应数据
            # Seedream 返回的是 b64_json 格式
            if "data" in data and len(data["data"]) > 0:
                image_data = data["data"][0].get("b64_json", "")
                if not image_data:
                    raise Exception("Seedream 返回的图片数据为空")

                return GeneratedImage(
                    image_data=image_data,
                    image_format="png",  # Seedream 默认返回 png
                    is_base64=True,
                    prompt=prompt,
                    model=self.model,
                    provider=self.name
                )
            else:
                raise Exception("Seedream 返回的数据格式不正确")
