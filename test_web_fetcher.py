#!/usr/bin/env python3
"""测试 WebFetcherTool"""

import asyncio
import sys
sys.path.insert(0, '/Users/zhangzheng/zavixai/Sage')

from sagents.tool.impl.web_fetcher_tool import WebFetcherTool

async def test_web_fetcher():
    """测试网页抓取工具"""
    tool = WebFetcherTool()
    
    # 测试单个URL
    print("=" * 60)
    print("测试1: 抓取单个URL")
    print("=" * 60)
    
    result = await tool.fetch_webpages(
        urls="https://httpbin.org/html",
        max_length_per_url=2000,
        timeout=30
    )
    
    print(f"状态: {result['status']}")
    print(f"消息: {result['message']}")
    print(f"成功数: {result['success_count']}")
    print(f"失败数: {result['error_count']}")
    
    if result['results']:
        r = result['results'][0]
        print(f"\nURL: {r['url']}")
        print(f"状态: {r['status']}")
        if r['metadata']:
            print(f"元数据: {r['metadata']}")
        if r['content']:
            print(f"内容前200字符: {r['content'][:200]}...")
    
    # 测试多个URL
    print("\n" + "=" * 60)
    print("测试2: 抓取多个URL")
    print("=" * 60)
    
    result = await tool.fetch_webpages(
        urls=[
            "https://httpbin.org/html",
            "https://example.com"
        ],
        max_length_per_url=1500,
        timeout=30,
        include_metadata=True
    )
    
    print(f"状态: {result['status']}")
    print(f"消息: {result['message']}")
    print(f"总URL数: {result['total_urls']}")
    print(f"成功数: {result['success_count']}")
    print(f"失败数: {result['error_count']}")
    
    for r in result['results']:
        print(f"\n---")
        print(f"URL: {r['url']}")
        print(f"状态: {r['status']}")
        if r.get('error'):
            print(f"错误: {r['error']}")
        if r['metadata']:
            print(f"标题: {r['metadata'].get('title', 'N/A')}")
        if r['content']:
            content_preview = r['content'][:150].replace('\n', ' ')
            print(f"内容预览: {content_preview}...")

if __name__ == "__main__":
    asyncio.run(test_web_fetcher())
