"""
Shuyan (数眼) 搜索 Provider
API文档: https://api.shuyanai.com/v1/search
"""

from typing import List
import httpx
from .base import BaseSearchProvider, SearchResult, ImageResult


class ShuyanProvider(BaseSearchProvider):
    """数眼搜索 Provider"""
    
    name = "shuyan"
    env_key = "SHUYAN_API_KEY"
    supports_images = False
    supports_time_range = True  # 支持时间范围筛选
    
    # 时间范围映射
    TIME_RANGE_MAP = {
        "day": "day",
        "week": "week",
        "month": "month",
        "year": "year",
    }

    @classmethod
    def get_required_env_vars(cls) -> dict:
        """获取必需的环境变量说明"""
        return {
            cls.env_key: {
                "description": "数眼搜索 API Key",
                "required": True,
                "url": "https://shuyanai.com",
            },
        }

    @classmethod
    def get_config_example(cls) -> str:
        """获取配置示例"""
        return """# 数眼搜索
export SHUYAN_API_KEY=your_api_key_here"""

    async def search_web(self, query: str, count: int, time_range: str = "") -> List[SearchResult]:
        """使用数眼搜索网页"""
        endpoint = "https://api.shuyanai.com/v1/search"
        
        payload = {
            "q": query,
            "num": min(count, 10)  # 数眼默认最多10条
        }
        
        # 添加时间范围参数
        if time_range and time_range in self.TIME_RANGE_MAP:
            payload["range"] = self.TIME_RANGE_MAP[time_range]
        
        headers = {
            'Authorization': self.api_key,
            'Content-Type': 'application/json'
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                endpoint, headers=headers, json=payload, timeout=15.0
            )
            response.raise_for_status()
            result = response.json()
            
            # 检查响应码
            if result.get("code") != 0:
                error_msg = result.get("message", "未知错误")
                raise Exception(f"数眼搜索API错误: {error_msg}")
            
            data = result.get("data", {})
            items = data.get("webPages", [])
            
            results = []
            for item in items:
                results.append(SearchResult(
                    title=item.get("name", ""),
                    url=item.get("url", ""),
                    snippet=item.get("snippet", ""),
                    source=item.get("siteName", "")
                ))
            return results
    
    async def search_images(self, query: str, count: int, time_range: str = "") -> List[ImageResult]:
        """数眼暂不支持图片搜索"""
        return []
