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


class SearchEngineManager:
    """搜索引擎管理器，自动检测并管理可用的搜索引擎"""
    
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
    
    def __init__(self):
        self.available_providers: List[BaseSearchProvider] = []
        self._detect_available_providers()
    
    def _detect_available_providers(self):
        """检测可用的搜索引擎提供商"""
        for provider_enum, provider_class in self.PROVIDER_CLASSES.items():
            api_key = os.environ.get(provider_class.env_key)
            if api_key:
                try:
                    provider_instance = provider_class(api_key)
                    self.available_providers.append(provider_instance)
                    logger.info(f"检测到可用搜索引擎: {provider_enum.value}")
                except Exception as e:
                    logger.warning(f"初始化搜索引擎 {provider_enum.value} 失败: {e}")
        
        if not self.available_providers:
            logger.warning("未检测到任何可用的搜索引擎API密钥")
    
    def get_available_providers(self) -> List[BaseSearchProvider]:
        """获取可用的搜索引擎列表"""
        return self.available_providers.copy()
    
    def get_provider_names(self) -> List[str]:
        """获取可用的搜索引擎名称列表"""
        return [p.name for p in self.available_providers]
    
    def get_image_providers(self) -> List[BaseSearchProvider]:
        """获取支持图片搜索的搜索引擎列表"""
        return [p for p in self.available_providers if p.supports_images]
    
    def get_image_provider_names(self) -> List[str]:
        """获取支持图片搜索的搜索引擎名称列表"""
        return [p.name for p in self.available_providers if p.supports_images]
    
    def get_config_error(self) -> str:
        """获取配置错误提示信息"""
        env_vars = [cls.env_key for cls in self.PROVIDER_CLASSES.values()]
        env_list = "\n".join([f"- {v}" for v in env_vars])
        return (
            f"未配置任何搜索引擎API密钥。请设置以下任一环境变量:\n"
            f"{env_list}\n\n"
            f"支持的搜索引擎:\n"
            f"- SERPAPI_API_KEY: SerpApi Google搜索 (searchapi.io)\n"
            f"- SERPER_API_KEY: Serper Google搜索 (serper.dev)\n"
            f"- TAVILY_API_KEY: Tavily搜索 (tavily.com)\n"
            f"- BRAVE_API_KEY: Brave搜索 (brave.com/search/api)\n"
            f"- ZHIPU_API_KEY: 智谱AI搜索 (bigmodel.cn)\n"
            f"- BOCHA_API_KEY: 博查搜索 (bochaai.com)\n"
            f"- SHUYAN_API_KEY: 数眼搜索 (shuyanai.com)\n\n"
            f"支持图片搜索的引擎: serpapi, serper, tavily, brave, bocha\n"
            f"不支持图片搜索的引擎: zhipu, shuyan\n\n"
            f"支持时间范围筛选的引擎: serpapi, serper, brave, bocha, shuyan\n"
            f"不支持时间范围筛选的引擎: tavily, zhipu"
        )
    
    async def search_web(
        self,
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
        if not self.available_providers:
            return [], self.get_config_error()
        
        # 尝试每个可用的搜索引擎
        last_error = None
        for provider in self.available_providers:
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
        self,
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
        image_providers = self.get_image_providers()
        
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


# 全局搜索引擎管理器实例
search_manager = SearchEngineManager()


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
    results, error = await search_manager.search_web(query, count, time_range)
    
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
    results, error = await search_manager.search_images(query, count, time_range)
    
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
