#!/usr/bin/env python3
"""
并发请求测试脚本
用于验证FastAPI服务器的并发处理能力
"""

import asyncio
import aiohttp
import time
import json
from typing import List

async def send_request(session: aiohttp.ClientSession, url: str, request_id: int) -> dict:
    """发送单个请求"""
    start_time = time.time()
    
    # 模拟一个简单的聊天请求
    payload = {
        "messages": [
            {
                "role": "user", 
                "content": f"请简单回答：什么是Python？(请求ID: {request_id})"
            }
        ],
        "session_id": f"test_session_{request_id}",
        "user_id": f"test_user_{request_id}"
    }
    
    try:
        async with session.post(url, json=payload) as response:
            if response.status == 200:
                # 对于流式响应，读取所有数据
                content = await response.text()
                end_time = time.time()
                return {
                    "request_id": request_id,
                    "status": "success",
                    "duration": end_time - start_time,
                    "response_length": len(content)
                }
            else:
                end_time = time.time()
                return {
                    "request_id": request_id,
                    "status": "error",
                    "duration": end_time - start_time,
                    "error": f"HTTP {response.status}"
                }
    except Exception as e:
        end_time = time.time()
        return {
            "request_id": request_id,
            "status": "error",
            "duration": end_time - start_time,
            "error": str(e)
        }

async def test_concurrent_requests(base_url: str = "http://localhost:8001", 
                                 num_requests: int = 5,
                                 endpoint: str = "/chat/stream"):
    """测试并发请求"""
    url = f"{base_url}{endpoint}"
    
    print(f"🚀 开始并发测试...")
    print(f"📍 目标URL: {url}")
    print(f"🔢 并发请求数: {num_requests}")
    print("-" * 50)
    
    start_time = time.time()
    
    # 创建HTTP会话
    async with aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(total=30)
    ) as session:
        # 创建并发任务
        tasks = [
            send_request(session, url, i+1) 
            for i in range(num_requests)
        ]
        
        # 等待所有请求完成
        results = await asyncio.gather(*tasks, return_exceptions=True)
    
    total_time = time.time() - start_time
    
    # 分析结果
    successful_requests = [r for r in results if isinstance(r, dict) and r.get("status") == "success"]
    failed_requests = [r for r in results if isinstance(r, dict) and r.get("status") == "error"]
    exceptions = [r for r in results if isinstance(r, Exception)]
    
    print("\n📊 测试结果:")
    print(f"⏱️  总耗时: {total_time:.2f}秒")
    print(f"✅ 成功请求: {len(successful_requests)}")
    print(f"❌ 失败请求: {len(failed_requests)}")
    print(f"💥 异常请求: {len(exceptions)}")
    
    if successful_requests:
        durations = [r["duration"] for r in successful_requests]
        avg_duration = sum(durations) / len(durations)
        max_duration = max(durations)
        min_duration = min(durations)
        
        print(f"\n⏱️  响应时间统计:")
        print(f"   平均: {avg_duration:.2f}秒")
        print(f"   最大: {max_duration:.2f}秒")
        print(f"   最小: {min_duration:.2f}秒")
        
        # 检查并发性能
        if max_duration < total_time * 0.8:
            print("🎉 并发性能良好！请求基本并行处理")
        else:
            print("⚠️  可能存在阻塞问题，请求似乎在串行处理")
    
    # 显示详细结果
    print(f"\n📋 详细结果:")
    for i, result in enumerate(results):
        if isinstance(result, dict):
            status_icon = "✅" if result["status"] == "success" else "❌"
            print(f"   {status_icon} 请求{result['request_id']}: {result['duration']:.2f}s")
            if result["status"] == "error":
                print(f"      错误: {result.get('error', 'Unknown')}")
        else:
            print(f"   💥 请求{i+1}: 异常 - {result}")

async def main():
    """主函数"""
    print("🔧 FastAPI并发性能测试工具")
    print("=" * 50)
    
    # 可以修改这些参数进行不同的测试
    await test_concurrent_requests(
        base_url="http://localhost:8001",
        num_requests=5,
        endpoint="/chat/stream"
    )
    
    print("\n💡 测试建议:")
    print("1. 如果请求基本并行处理，说明并发性能良好")
    print("2. 如果请求串行处理，可能存在阻塞问题")
    print("3. 可以增加请求数量测试更高并发场景")

if __name__ == "__main__":
    asyncio.run(main())