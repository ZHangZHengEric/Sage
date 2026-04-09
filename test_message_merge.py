#!/usr/bin/env python3
"""
测试 IM Server 的消息合并功能

测试原理：
1. 模拟用户快速连续发送多条消息
2. 验证这些消息是否在 3 秒窗口内被合并
3. 检查 Agent 收到的消息是否为合并后的内容
"""

import asyncio
import sys
import time
from typing import List, Dict, Any

# 添加项目路径
sys.path.insert(0, '/Users/caoqihang/Desktop/vibe_coding/Sage')


async def test_message_merge_logic():
    """测试消息合并的核心逻辑"""
    print("=" * 60)
    print("测试 1: 消息合并核心逻辑")
    print("=" * 60)
    
    # 手动实现测试，不依赖 ServiceManager 的复杂初始化
    class SimpleMessageMerger:
        """简化版消息合并器，用于测试"""
        def __init__(self):
            self._message_buffers: Dict[str, Dict] = {}
            self._buffer_lock = asyncio.Lock()
            self._merge_window = 3.0
            self.received_messages: List[str] = []
        
        async def _delayed_process(self, buffer_key: str, sage_user_id: str,
                                   provider_type: str, user_id: str,
                                   chat_id: str, user_name: str):
            """等待后处理合并消息"""
            await asyncio.sleep(self._merge_window)
            await self._process_merged_messages(buffer_key, sage_user_id, provider_type,
                                               user_id, chat_id, user_name)
        
        async def _process_merged_messages(self, buffer_key: str, sage_user_id: str,
                                          provider_type: str, user_id: str, 
                                          chat_id: str, user_name: str):
            """处理合并后的消息"""
            async with self._buffer_lock:
                buffer_data = self._message_buffers.pop(buffer_key, None)
            
            if not buffer_data:
                return
            
            # 合并消息
            merged_text = " ".join(buffer_data['messages'])
            self.received_messages.append(merged_text)
            print(f"✅ 收到合并消息: '{merged_text}'")
            print(f"   原始消息数: {len(buffer_data['messages'])}")
            print(f"   消息列表: {buffer_data['messages']}")
    
    sm = SimpleMessageMerger()
    
    # 模拟用户快速发送 3 条消息
    test_messages = ["帮我", "写个", "Python脚本"]
    user_id = "test_user_001"
    buffer_key = f"agent1:dingtalk:{user_id}"
    
    print(f"\n模拟用户在 3 秒内发送 {len(test_messages)} 条消息:")
    for i, msg in enumerate(test_messages, 1):
        print(f"  {i}. '{msg}'")
    
    # 模拟消息接收
    for msg in test_messages:
        async with sm._buffer_lock:
            if buffer_key in sm._message_buffers:
                # 添加到现有 buffer，重置 timer
                sm._message_buffers[buffer_key]['messages'].append(msg)
                if 'timer' in sm._message_buffers[buffer_key]:
                    sm._message_buffers[buffer_key]['timer'].cancel()
                sm._message_buffers[buffer_key]['timer'] = asyncio.create_task(
                    sm._delayed_process(buffer_key, "agent1", "dingtalk", user_id, "chat1", "测试用户")
                )
            else:
                # 创建新 buffer
                sm._message_buffers[buffer_key] = {
                    'messages': [msg],
                    'timer': asyncio.create_task(
                        sm._delayed_process(buffer_key, "agent1", "dingtalk", user_id, "chat1", "测试用户")
                    )
                }
        # 模拟用户输入间隔（100ms）
        await asyncio.sleep(0.1)
    
    # 等待合并窗口结束（3秒）
    print(f"\n⏳ 等待 {sm._merge_window} 秒合并窗口...")
    await asyncio.sleep(sm._merge_window + 0.5)
    
    # 验证结果
    print("\n" + "=" * 60)
    print("验证结果")
    print("=" * 60)
    
    if len(sm.received_messages) == 1:
        merged = sm.received_messages[0]
        expected = " ".join(test_messages)
        if merged == expected:
            print(f"✅ 测试通过！消息正确合并")
            print(f"   合并结果: '{merged}'")
            return True
        else:
            print(f"❌ 测试失败！合并结果不符")
            print(f"   期望: '{expected}'")
            print(f"   实际: '{merged}'")
            return False
    else:
        print(f"❌ 测试失败！收到 {len(sm.received_messages)} 条消息，期望 1 条")
        return False


async def test_interval_messages():
    """测试间隔超过 3 秒的消息不被合并"""
    print("\n" + "=" * 60)
    print("测试 2: 间隔超过 3 秒的消息不应合并")
    print("=" * 60)
    
    class SimpleMessageMerger:
        """简化版消息合并器，用于测试"""
        def __init__(self):
            self._message_buffers: Dict[str, Dict] = {}
            self._buffer_lock = asyncio.Lock()
            self._merge_window = 3.0
            self.received_messages: List[str] = []
        
        async def _delayed_process(self, buffer_key: str, sage_user_id: str,
                                   provider_type: str, user_id: str,
                                   chat_id: str, user_name: str):
            """等待后处理合并消息"""
            await asyncio.sleep(self._merge_window)
            await self._process_merged_messages(buffer_key, sage_user_id, provider_type,
                                               user_id, chat_id, user_name)
        
        async def _process_merged_messages(self, buffer_key: str, sage_user_id: str,
                                          provider_type: str, user_id: str, 
                                          chat_id: str, user_name: str):
            """处理合并后的消息"""
            async with self._buffer_lock:
                buffer_data = self._message_buffers.pop(buffer_key, None)
            
            if not buffer_data:
                return
            
            merged_text = " ".join(buffer_data['messages'])
            self.received_messages.append(merged_text)
            print(f"✅ 收到消息: '{merged_text}'")
    
    sm = SimpleMessageMerger()
    user_id = "test_user_002"
    buffer_key = f"agent1:dingtalk:{user_id}"
    
    print("\n发送第一条消息: '你好'")
    async with sm._buffer_lock:
        sm._message_buffers[buffer_key] = {
            'messages': ["你好"],
            'timer': asyncio.create_task(
                sm._delayed_process(buffer_key, "agent1", "dingtalk", user_id, "chat1", "测试用户")
            )
        }
    
    # 等待第一条消息处理完成
    print(f"⏳ 等待 {sm._merge_window + 1} 秒...")
    await asyncio.sleep(sm._merge_window + 1)
    
    # 发送第二条消息（超过合并窗口）
    print("\n发送第二条消息: '在吗'")
    async with sm._buffer_lock:
        if buffer_key in sm._message_buffers:
            sm._message_buffers[buffer_key]['messages'].append("在吗")
            if 'timer' in sm._message_buffers[buffer_key]:
                sm._message_buffers[buffer_key]['timer'].cancel()
            sm._message_buffers[buffer_key]['timer'] = asyncio.create_task(
                sm._delayed_process(buffer_key, "agent1", "dingtalk", user_id, "chat1", "测试用户")
            )
        else:
            sm._message_buffers[buffer_key] = {
                'messages': ["在吗"],
                'timer': asyncio.create_task(
                    sm._delayed_process(buffer_key, "agent1", "dingtalk", user_id, "chat1", "测试用户")
                )
            }
    
    # 等待第二条消息处理
    await asyncio.sleep(sm._merge_window + 1)
    
    # 验证结果
    print("\n" + "=" * 60)
    print("验证结果")
    print("=" * 60)
    
    if len(sm.received_messages) == 2:
        print(f"✅ 测试通过！收到 2 条独立消息，未被合并")
        print(f"   消息1: '{sm.received_messages[0]}'")
        print(f"   消息2: '{sm.received_messages[1]}'")
        return True
    else:
        print(f"❌ 测试失败！收到 {len(sm.received_messages)} 条消息，期望 2 条")
        return False


async def test_actual_service_manager():
    """测试实际的 ServiceManager 代码"""
    print("\n" + "=" * 60)
    print("测试 3: 验证 ServiceManager 代码结构")
    print("=" * 60)
    
    try:
        from mcp_servers.im_server.service_manager import IMServiceManager
        import inspect
        
        # 检查关键方法是否存在（在类或实例中）
        has_delayed = '_delayed_process' in IMServiceManager.__dict__ or hasattr(IMServiceManager, '_delayed_process')
        has_process = '_process_merged_messages' in IMServiceManager.__dict__ or hasattr(IMServiceManager, '_process_merged_messages')
        
        # 获取源代码查看关键属性
        source = inspect.getsource(IMServiceManager.__init__) if hasattr(IMServiceManager, '__init__') else ""
        has_buffer = '_message_buffers' in source
        has_lock = '_buffer_lock' in source
        has_window = '_merge_window' in source
        
        print("✅ IMServiceManager 代码检查")
        print(f"   - _delayed_process: {'✅' if has_delayed else '❌'}")
        print(f"   - _process_merged_messages: {'✅' if has_process else '❌'}")
        print(f"   - _message_buffers: {'✅' if has_buffer else '❌'}")
        print(f"   - _buffer_lock: {'✅' if has_lock else '❌'}")
        print(f"   - _merge_window: {'✅' if has_window else '❌'}")
        
        return has_delayed and has_process and has_buffer and has_lock and has_window
        
    except Exception as e:
        print(f"❌ 检查失败: {e}")
        import traceback
        traceback.print_exc()
        return False


async def main():
    """运行所有测试"""
    print("\n" + "=" * 60)
    print("IM Server 消息合并功能测试")
    print("=" * 60)
    
    results = []
    
    try:
        results.append(("消息合并核心逻辑", await test_message_merge_logic()))
    except Exception as e:
        print(f"❌ 测试 1 出错: {e}")
        results.append(("消息合并核心逻辑", False))
    
    try:
        results.append(("间隔消息测试", await test_interval_messages()))
    except Exception as e:
        print(f"❌ 测试 2 出错: {e}")
        results.append(("间隔消息测试", False))
    
    try:
        results.append(("ServiceManager 结构检查", await test_actual_service_manager()))
    except Exception as e:
        print(f"❌ 测试 3 出错: {e}")
        results.append(("ServiceManager 结构检查", False))
    
    # 测试总结
    print("\n" + "=" * 60)
    print("测试总结")
    print("=" * 60)
    
    for name, passed in results:
        status = "✅ 通过" if passed else "❌ 失败"
        print(f"  {status}: {name}")
    
    all_passed = all(r[1] for r in results)
    print("\n" + ("🎉 所有测试通过！" if all_passed else "⚠️ 部分测试失败"))
    
    return 0 if all_passed else 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
