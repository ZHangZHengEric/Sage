"""
阿里云百炼 (Qwen) 图片生成 Provider

文档: https://bailian.console.aliyun.com/
支持模型: 万相-文生图V2, 万相-文生图V1, 千问-文生图等
"""

import asyncio
import os
import httpx
from typing import Optional
from .base import BaseImageProvider, GeneratedImage


class QwenProvider(BaseImageProvider):
    """阿里云百炼 (Qwen) 图片生成 Provider"""

    name = "qwen"
    env_key = "QWEN_API_KEY"  # 阿里云百炼 API Key
    model_env_key = "QWEN_MODEL"  # 模型名称环境变量
    default_model = "wanx2.1-t2i-plus"  # 万相-文生图V2
    supports_reference_image = True  # 支持图生图

    # API 端点 (阿里云百炼)
    API_ENDPOINT = "https://dashscope.aliyuncs.com/api/v1/services/aigc/text2image/image-synthesis"

    # 支持的模型列表
    SUPPORTED_MODELS = {
        "wanx2.1-t2i-plus": "万相-文生图V2 (推荐)",
        "wanx2.1-t2i-turbo": "万相-文生图V2-Turbo",
        "wanx2.1-t2i": "万相-文生图V2-标准版",
        "wanx-v1": "万相-文生图V1",
        "qwen-t2i": "千问-文生图",
    }

    # 支持的尺寸 (宽x高)
    SIZE_MAP = {
        "1:1": "1024x1024",
        "16:9": "1024x576",
        "9:16": "576x1024",
        "4:3": "1024x768",
        "3:4": "768x1024",
        "3:2": "1024x682",
        "2:3": "682x1024",
    }

    @classmethod
    def get_required_env_vars(cls) -> dict:
        """获取必需的环境变量说明"""
        return {
            cls.env_key: {
                "description": "阿里云百炼 API Key",
                "required": True,
                "url": "https://bailian.console.aliyun.com/?tab=api#/api",
            },
            cls.model_env_key: {
                "description": "模型名称（如 wanx2.1-t2i-plus, wanx2.1-t2i-turbo, wanx-v1）",
                "required": True,
                "url": "https://bailian.console.aliyun.com/?tab=api#/api",
            },
        }

    @classmethod
    def get_config_example(cls) -> str:
        """获取配置示例"""
        return """# 阿里云百炼 (Qwen)
export QWEN_API_KEY=your_api_key_here
export QWEN_MODEL=wanx2.1-t2i-plus"""

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
        使用阿里云百炼生成图片

        Args:
            prompt: 图片描述提示词
            aspect_ratio: 图片宽高比
            reference_image: 参考图 URL (部分模型支持)

        Returns:
            GeneratedImage: 生成的图片结果
        """
        # 构建请求头
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "X-DashScope-Async": "enable",  # 异步模式
        }

        # 构建请求体
        size = self.SIZE_MAP.get(aspect_ratio, "1024x1024")
        payload = {
            "model": self.model,
            "input": {
                "prompt": prompt,
            },
            "parameters": {
                "size": size,
                "n": 1,  # 生成1张图片
            }
        }

        # 如果提供了参考图且模型支持
        if reference_image and self.supports_reference_image:
            # 万相部分模型支持参考图
            payload["input"]["ref_img"] = reference_image

        async with httpx.AsyncClient() as client:
            # 第一步：提交任务
            response = await client.post(
                self.API_ENDPOINT,
                headers=headers,
                json=payload,
                timeout=30.0
            )

            if response.status_code == 401 or response.status_code == 403:
                raise Exception(f"阿里云百炼 API Key 无效或没有权限，请检查环境变量 {self.env_key}")

            response.raise_for_status()
            data = response.json()

            # 获取任务ID
            task_id = data.get("output", {}).get("task_id")
            if not task_id:
                raise Exception("未能获取任务ID")

            # 第二步：轮询任务结果
            result_url = f"https://dashscope.aliyuncs.com/api/v1/tasks/{task_id}"
            max_retries = 30
            retry_delay = 2  # 秒

            for _ in range(max_retries):
                await asyncio.sleep(retry_delay)

                result_response = await client.get(
                    result_url,
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    timeout=30.0
                )
                result_response.raise_for_status()
                result_data = result_response.json()

                task_status = result_data.get("output", {}).get("task_status")

                if task_status == "SUCCEEDED":
                    # 任务成功，获取图片URL
                    results = result_data.get("output", {}).get("results", [])
                    if results and len(results) > 0:
                        image_url = results[0].get("url")
                        if image_url:
                            return GeneratedImage(
                                image_data=image_url,
                                image_format="png",
                                is_base64=False,
                                prompt=prompt,
                                model=self.model,
                                provider=self.name
                            )
                    raise Exception("任务成功但未返回图片URL")

                elif task_status == "FAILED":
                    error_message = result_data.get("output", {}).get("message", "未知错误")
                    raise Exception(f"图片生成任务失败: {error_message}")

                # 继续轮询 (PENDING, RUNNING)

            raise Exception("等待图片生成超时")
