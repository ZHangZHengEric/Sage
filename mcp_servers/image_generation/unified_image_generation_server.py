#!/usr/bin/env python3
"""
统一图片生成服务
支持多个图片生成提供商：Minimax(海螺AI) 等
自动根据环境变量选择可用的提供商
"""

import os
import json
import base64
from typing import List, Optional, Tuple
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from .image_providers import (
    GeneratedImage,
    ImageProviderEnum,
    MinimaxProvider,
    QwenProvider,
    SeedreamProvider,
)
from .image_providers.base import BaseImageProvider
from sagents.tool.mcp_tool_base import sage_mcp_tool
from sagents.utils.logger import logger

# 初始化 MCP 服务器
mcp = FastMCP("Unified Image Generation Service")


# Provider 类映射
PROVIDER_CLASSES = {
    ImageProviderEnum.MINIMAX: MinimaxProvider,
    ImageProviderEnum.QWEN: QwenProvider,
    ImageProviderEnum.SEEDREAM: SeedreamProvider,
}


def get_available_providers() -> List[BaseImageProvider]:
    """每次调用时重新检测可用的图片生成提供商"""
    available_providers = []
    for provider_enum, provider_class in PROVIDER_CLASSES.items():
        api_key = os.environ.get(provider_class.env_key)
        if api_key:
            try:
                provider_instance = provider_class(api_key)
                available_providers.append(provider_instance)
                logger.info(f"检测到可用图片生成提供商: {provider_enum.value}")
            except Exception as e:
                logger.warning(f"初始化图片生成提供商 {provider_enum.value} 失败: {e}")
    
    if not available_providers:
        logger.warning("未检测到任何可用的图片生成API密钥")
    
    return available_providers


def get_config_status() -> dict:
    """获取详细的配置状态"""
    status = {
        "available": [],
        "missing": [],
        "details": {}
    }

    for provider_enum, provider_class in PROVIDER_CLASSES.items():
        provider_name = provider_enum.value
        env_vars = provider_class.get_required_env_vars()

        # 检查每个环境变量
        provider_status = {
            "name": provider_name,
            "env_vars": {},
            "is_available": True
        }

        for var_name, var_info in env_vars.items():
            current_value = os.environ.get(var_name, "")
            is_set = bool(current_value)

            provider_status["env_vars"][var_name] = {
                "description": var_info.get("description", ""),
                "required": var_info.get("required", True),
                "is_set": is_set,
                "url": var_info.get("url", ""),
                "default": var_info.get("default", ""),
            }

            # 如果必需的环境变量未设置，标记为不可用
            if var_info.get("required", True) and not is_set:
                provider_status["is_available"] = False

        status["details"][provider_name] = provider_status

        if provider_status["is_available"]:
            status["available"].append(provider_name)
        else:
            status["missing"].append(provider_name)

    return status


def get_config_error() -> str:
    """获取配置错误提示信息"""
    status = get_config_status()

    lines = [
        "未配置任何可用的图片生成提供商。",
        "",
        "请检查以下环境变量设置:",
        "=" * 60,
        ""
    ]

    for provider_name, provider_status in status["details"].items():
        lines.append(f"【{provider_name}】")

        for var_name, var_info in provider_status["env_vars"].items():
            is_set = var_info["is_set"]
            required = var_info["required"]
            description = var_info["description"]
            url = var_info.get("url", "")
            default = var_info.get("default", "")

            status_icon = "✓" if is_set else "✗"
            required_text = "(必需)" if required else "(可选)"

            lines.append(f"  {status_icon} {var_name} {required_text}")
            lines.append(f"    说明: {description}")

            if url:
                lines.append(f"    获取地址: {url}")

            if default and not is_set:
                lines.append(f"    默认值: {default}")

            if not is_set and required:
                lines.append("    ⚠️  未设置，请配置此环境变量")

            lines.append("")

    lines.extend([
        "=" * 60,
        "",
        "配置示例:",
        "",
    ])

    # 从每个 provider 获取配置示例
    for provider_enum, provider_class in PROVIDER_CLASSES.items():
        try:
            example = provider_class.get_config_example()
            lines.append(example)
            lines.append("")
        except Exception:
            pass

    lines.extend([
        "支持的模型:",
    ])

    # 从每个 provider 获取支持的模型信息
    for provider_enum, provider_class in PROVIDER_CLASSES.items():
        provider_name = provider_enum.value
        try:
            env_vars = provider_class.get_required_env_vars()
            if provider_class.model_env_key in env_vars:
                model_info = env_vars[provider_class.model_env_key]
                description = model_info.get("description", "")
                # 提取模型名称示例
                lines.append(f"  - {provider_name}: {description}")
        except Exception:
            pass

    # 获取支持参考图的提供商
    ref_providers = []
    for provider_enum, provider_class in PROVIDER_CLASSES.items():
        if provider_class.supports_reference_image:
            ref_providers.append(provider_enum.value)

    lines.extend([
        "",
        f"支持参考图的提供商: {', '.join(ref_providers)}",
    ])

    return "\n".join(lines)


def get_reference_image_providers(providers: List[BaseImageProvider]) -> List[BaseImageProvider]:
    """获取支持参考图的提供商列表"""
    return [p for p in providers if p.supports_reference_image]


def _save_base64_image(base64_data: str, output_path: str):
    """保存 base64 图片到文件"""
    # 确保目录存在
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    
    # 解码并保存
    image_bytes = base64.b64decode(base64_data)
    with open(output_path, "wb") as f:
        f.write(image_bytes)


async def generate_image_impl(
    prompt: str,
    aspect_ratio: str = "1:1",
    reference_image: Optional[str] = None,
    output_path: Optional[str] = None,
) -> Tuple[Optional[GeneratedImage], Optional[str]]:
    """
    生成图片
    
    Args:
        prompt: 图片描述提示词
        aspect_ratio: 图片宽高比 (1:1, 16:9, 4:3, 3:2, 2:3, 9:16)
        reference_image: 参考图 URL（可选）
        output_path: 图片保存路径（可选，如果不提供则返回 base64）
        
    Returns:
        (生成的图片结果, 错误信息)
    """
    available_providers = get_available_providers()
    
    if not available_providers:
        return None, get_config_error()
    
    # 如果提供了参考图，优先使用支持参考图的提供商
    providers = available_providers
    if reference_image:
        ref_providers = get_reference_image_providers(available_providers)
        if ref_providers:
            providers = ref_providers
        else:
            return None, "没有支持参考图的提供商"
    
    # 尝试每个可用的提供商
    last_error = None
    for provider in providers:
        try:
            result = await provider.generate_image(
                prompt=prompt,
                aspect_ratio=aspect_ratio,
                reference_image=reference_image,
            )
            
            # 如果指定了输出路径，保存图片
            if output_path and result.is_base64:
                _save_base64_image(result.image_data, output_path)
                result.image_data = output_path
                result.is_base64 = False
            
            logger.info(f"使用 {provider.name} 生成图片成功")
            return result, None
            
        except Exception as e:
            logger.warning(f"图片生成提供商 {provider.name} 失败: {e}")
            last_error = str(e)
            continue
    
    error_msg = "所有图片生成提供商都失败了"
    if last_error:
        error_msg += f"。最后一个错误: {last_error}"
    return None, error_msg


@mcp.tool(
    name="generate_image",
    description="根据文本描述生成图片。支持参考图生成（保持人物一致性）。自动选择可用的提供商。"
)
@sage_mcp_tool(server_name="unified_image_generation_server")
async def generate_image(
    prompt: str,
    aspect_ratio: str = "1:1",
    reference_image: str = "",
    output_path: str = "",
) -> str:
    """
    根据文本描述生成图片

    Args:
        prompt: 图片描述提示词（必填）。详细描述你想要的图片内容，包括场景、风格、人物、光线等
        aspect_ratio: 图片宽高比（默认1:1）。可选: 1:1, 16:9, 4:3, 3:2, 2:3, 9:16
        reference_image: 参考图URL（可选）。提供参考图可以生成风格一致或人物一致的图片
        output_path: 图片保存路径（可选）。如果提供，图片将保存到该路径；否则返回base64编码的图片数据

    Returns:
        JSON格式的生成结果，包含图片数据或保存路径
    """
    # 检查是否有可用的提供商
    available_providers = get_available_providers()
    if not available_providers:
        config_error = get_config_error()
        return json.dumps({
            "success": False,
            "error": "未配置任何可用的图片生成提供商",
            "config_help": config_error,
            "message": "请先配置图片生成提供商的环境变量后再使用此功能"
        }, ensure_ascii=False, indent=2)

    # 执行图片生成
    result, error = await generate_image_impl(
        prompt=prompt,
        aspect_ratio=aspect_ratio,
        reference_image=reference_image if reference_image else None,
        output_path=output_path if output_path else None,
    )

    if error:
        return json.dumps({
            "error": error,
            "success": False,
        }, ensure_ascii=False, indent=2)
    
    # 构建返回结果
    response = {
        "success": True,
        "prompt": result.prompt,
        "model": result.model,
        "provider": result.provider,
        "aspect_ratio": aspect_ratio,
        "image_format": result.image_format,
        "is_base64": result.is_base64,
    }
    
    if result.is_base64:
        # 返回 base64 数据（截断显示）
        response["image_data"] = result.image_data[:100] + "..." if len(result.image_data) > 100 else result.image_data
        response["image_data_full"] = result.image_data  # 完整的 base64 数据
    else:
        # 返回文件路径
        response["image_path"] = result.image_data
    
    return json.dumps(response, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    mcp.run()
