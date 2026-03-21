"""
图片生成 Provider 基类
"""

from typing import Optional
from dataclasses import dataclass


@dataclass
class GeneratedImage:
    """统一生成的图片结果格式"""
    image_data: str  # base64 编码的图片数据或 URL
    image_format: str  # 图片格式: jpeg, png, webp 等
    is_base64: bool  # 是否是 base64 编码
    prompt: str  # 使用的提示词
    model: str  # 使用的模型
    provider: str  # 提供商名称


class BaseImageProvider:
    """图片生成 Provider 基类"""

    name: str = ""
    env_key: str = ""  # 环境变量名
    supports_reference_image: bool = False  # 是否支持参考图

    def __init__(self, api_key: str):
        self.api_key = api_key

    @classmethod
    def get_required_env_vars(cls) -> dict:
        """
        获取必需的环境变量说明

        Returns:
            dict: 环境变量名 -> {description, required, url, default}
        """
        raise NotImplementedError

    @classmethod
    def get_config_example(cls) -> str:
        """
        获取配置示例，子类应该重写此方法

        Returns:
            str: 配置示例字符串
        """
        raise NotImplementedError

    async def generate_image(
        self,
        prompt: str,
        aspect_ratio: str = "1:1",
        reference_image: Optional[str] = None,
        **kwargs
    ) -> GeneratedImage:
        """
        生成图片，子类必须实现

        Args:
            prompt: 图片描述提示词
            aspect_ratio: 图片宽高比 (如 "1:1", "16:9", "4:3" 等)
            reference_image: 参考图 URL（如果 provider 支持）
            **kwargs: 其他 provider 特定参数

        Returns:
            GeneratedImage: 生成的图片结果
        """
        raise NotImplementedError
