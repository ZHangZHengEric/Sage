#!/usr/bin/env python3
"""
统一搜索引擎服务
支持多个搜索引擎：SerpApi, Serper, Tavily, Brave, Zhipu(智谱), Bocha(博查), Shuyan(数眼)
自动根据环境变量选择可用的搜索引擎
"""

import os
import json
from typing import List, Optional, Dict, Tuple

from mcp.server.fastmcp import FastMCP

from .search_providers import (
    SearchResult,
    ImageResult,
    SearchProviderEnum,
    SerpApiProvider,
    SerperProvider,
    TavilyProvider,
    BraveProvider,
    ZhipuProvider,
    BochaProvider,
    ShuyanProvider,
)
from .search_providers.base import BaseSearchProvider
from sagents.tool.mcp_tool_base import sage_mcp_tool
from sagents.utils.logger import logger

# 初始化 MCP 服务器
mcp = FastMCP("Unified Search Service")


# Provider 类映射
PROVIDER_CLASSES = {
    SearchProviderEnum.SERPAPI: SerpApiProvider,
    SearchProviderEnum.SERPER: SerperProvider,
    SearchProviderEnum.TAVILY: TavilyProvider,
    SearchProviderEnum.BRAVE: BraveProvider,
    SearchProviderEnum.ZHIPU: ZhipuProvider,
    SearchProviderEnum.BOCHA: BochaProvider,
    SearchProviderEnum.SHUYAN: ShuyanProvider,
}


def get_available_providers() -> List[BaseSearchProvider]:
    """每次调用时重新检测可用的搜索引擎提供商"""
    available_providers = []
    for provider_enum, provider_class in PROVIDER_CLASSES.items():
        api_key = os.environ.get(provider_class.env_key)
        if api_key:
            try:
                provider_instance = provider_class(api_key)
                available_providers.append(provider_instance)
                logger.info(f"检测到可用搜索引擎: {provider_enum.value}")
            except Exception as e:
                logger.warning(f"初始化搜索引擎 {provider_enum.value} 失败: {e}")
    
    if not available_providers:
        logger.warning("未检测到任何可用的搜索引擎API密钥")
    
    return available_providers


def get_config_error() -> str:
    """获取配置错误提示信息"""
    lines = [
        "未配置任何搜索引擎API密钥。",
        "",
        "请检查以下环境变量设置:",
        "=" * 60,
        ""
    ]

    # 从每个 provider 获取配置信息
    for provider_enum, provider_class in PROVIDER_CLASSES.items():
        provider_name = provider_enum.value

        try:
            env_vars = provider_class.get_required_env_vars()
            lines.append(f"【{provider_name}】")

            for var_name, var_info in env_vars.items():
                description = var_info.get("description", "")
                url = var_info.get("url", "")

                lines.append(f"  - {var_name}")
                lines.append(f"    说明: {description}")
                if url:
                    lines.append(f"    获取地址: {url}")
                lines.append("")
        except Exception:
            pass

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

    # 获取支持图片搜索的引擎
    image_providers = []
    for provider_enum, provider_class in PROVIDER_CLASSES.items():
        if provider_class.supports_images:
            image_providers.append(provider_enum.value)

    # 获取支持时间范围筛选的引擎
    time_range_providers = []
    for provider_enum, provider_class in PROVIDER_CLASSES.items():
        if provider_class.supports_time_range:
            time_range_providers.append(provider_enum.value)

    lines.extend([
        f"支持图片搜索的引擎: {', '.join(image_providers)}",
        f"支持时间范围筛选的引擎: {', '.join(time_range_providers)}",
    ])

    return "\n".join(lines)


async def search_web(
    query: str,
    count: int = 10,
    time_range: str = ""
) -> Tuple[List[SearchResult], Optional[str]]:
    """
    执行网页搜索
    
    Args:
        query: 搜索查询
        count: 返回结果数量
        time_range: 时间范围 (day, week, month, year, 空字符串表示不限)
        
    Returns:
        (搜索结果列表, 错误信息)
    """
    available_providers = get_available_providers()
    
    if not available_providers:
        return [], get_config_error()
    
    # 尝试每个可用的搜索引擎
    last_error = None
    for provider in available_providers:
        try:
            results = await provider.search_web(query, count, time_range)
            if results:
                logger.info(f"使用 {provider.name} 搜索成功，返回 {len(results)} 条结果")
                return results, None
        except Exception as e:
            logger.warning(f"搜索引擎 {provider.name} 失败: {e}")
            last_error = str(e)
            continue
    
    error_msg = "所有搜索引擎都失败了"
    if last_error:
        error_msg += f"。最后一个错误: {last_error}"
    return [], error_msg


async def search_images(
    query: str,
    count: int = 10,
    time_range: str = ""
) -> Tuple[List[ImageResult], Optional[str]]:
    """
    执行图片搜索
    
    Args:
        query: 搜索查询
        count: 返回结果数量
        time_range: 时间范围 (day, week, month, year, 空字符串表示不限)
        
    Returns:
        (图片结果列表, 错误信息)
    """
    available_providers = get_available_providers()
    image_providers = [p for p in available_providers if p.supports_images]
    
    if not image_providers:
        return [], (
            "未配置支持图片搜索的搜索引擎API密钥。\n"
            "支持图片搜索的引擎: serpapi, serper, tavily, brave, bocha\n"
            "请设置以下任一环境变量:\n"
            "- SERPAPI_API_KEY: SerpApi (searchapi.io)\n"
            "- SERPER_API_KEY: Serper (serper.dev)\n"
            "- TAVILY_API_KEY: Tavily (tavily.com)\n"
            "- BRAVE_API_KEY: Brave (brave.com/search/api)\n"
            "- BOCHA_API_KEY: 博查 (bochaai.com)"
        )
    
    # 尝试每个可用的搜索引擎
    last_error = None
    for provider in image_providers:
        try:
            results = await provider.search_images(query, count, time_range)
            if results:
                logger.info(f"使用 {provider.name} 图片搜索成功，返回 {len(results)} 条结果")
                return results, None
        except Exception as e:
            logger.warning(f"搜索引擎 {provider.name} 图片搜索失败: {e}")
            last_error = str(e)
            continue
    
    error_msg = "所有搜索引擎都失败了"
    if last_error:
        error_msg += f"。最后一个错误: {last_error}"
    return [], error_msg


@mcp.tool(
    name="search_web_page",
    description="搜索网页内容。支持多个搜索引擎，自动选择可用的引擎。"
)
@sage_mcp_tool(server_name="unified_search_server")
async def search_web_page(
    query: str,
    count: int = 10,
    time_range: str = ""
) -> str:
    """
    搜索网页内容。支持多个搜索引擎，自动选择可用的引擎。
    
    Args:
        query: 搜索查询词（必填）
        count: 返回结果数量（默认10，最大100）
        time_range: 时间范围筛选（可选: day, week, month, year），空字符串表示不限时间
        
    Returns:
        JSON格式的搜索结果列表
    """
    # 执行搜索
    results, error = await search_web(query, count, time_range)
    
    if error:
        return json.dumps({
            "error": error,
            "results": []
        }, ensure_ascii=False, indent=2)
    
    # 转换为字典列表
    results_dict = [
        {
            "title": r.title,
            "url": r.url,
            "snippet": r.snippet,
            "source": r.source
        }
        for r in results
    ]
    
    return json.dumps({
        "query": query,
        "count": len(results_dict),
        "time_range": time_range if time_range else "不限",
        "results": results_dict
    }, ensure_ascii=False, indent=2)


@mcp.tool(
    name="search_image_from_web",
    description="搜索网络图片。支持多个搜索引擎，自动选择可用的引擎。"
)
@sage_mcp_tool(server_name="unified_search_server")
async def search_image_from_web(
    query: str,
    count: int = 10,
    time_range: str = ""
) -> str:
    """
    搜索网络图片。支持多个搜索引擎，自动选择可用的引擎。
    
    Args:
        query: 搜索查询词（必填）
        count: 返回结果数量（默认10，最大100）
        time_range: 时间范围筛选（可选: day, week, month, year），空字符串表示不限时间
        
    Returns:
        JSON格式的图片搜索结果列表
    """
    # 执行搜索
    results, error = await search_images(query, count, time_range)
    
    if error:
        return json.dumps({
            "error": error,
            "results": []
        }, ensure_ascii=False, indent=2)
    
    # 转换为字典列表
    results_dict = [
        {
            "title": r.title,
            "image_url": r.image_url,
            "thumbnail_url": r.thumbnail_url,
            "source": r.source
        }
        for r in results
    ]
    
    return json.dumps({
        "query": query,
        "count": len(results_dict),
        "time_range": time_range if time_range else "不限",
        "results": results_dict
    }, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    mcp.run()
