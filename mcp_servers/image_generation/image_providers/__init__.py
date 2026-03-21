"""
图片生成 Provider 模块

提供统一的图片生成接口，支持多个图片生成提供商：
- Minimax (海螺AI)
- 可扩展更多 provider

"""

from dataclasses import dataclass
from enum import Enum

from .base import BaseImageProvider
from .minimax_provider import MinimaxProvider
from .qwen_provider import QwenProvider
from .seedream_provider import SeedreamProvider


@dataclass
class GeneratedImage:
    """统一生成的图片结果格式"""
    image_data: str  # base64 编码的图片数据或 URL
    image_format: str  # 图片格式: jpeg, png, webp 等
    is_base64: bool  # 是否是 base64 编码
    prompt: str  # 使用的提示词
    model: str  # 使用的模型
    provider: str  # 提供商名称


class ImageProviderEnum(Enum):
    """支持的图片生成提供商枚举"""
    MINIMAX = "minimax"  # 海螺AI
    QWEN = "qwen"  # 阿里云百炼
    SEEDREAM = "seedream"  # 火山引擎 Seedream


__all__ = [
    "GeneratedImage",
    "BaseImageProvider",
    "ImageProviderEnum",
    "MinimaxProvider",
    "QwenProvider",
    "SeedreamProvider",
]
