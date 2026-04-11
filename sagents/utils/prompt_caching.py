"""
Prompt Caching 工具模块
提供通用的 prompt caching 支持，适配不同厂商的实现方式

阿里云百炼 Context Cache 策略：
- 隐式缓存：自动，命中时 20% 成本
- 显式缓存：需 cache_control 标记，命中时 10% 成本（最低）

最佳实践：
1. 在长系统提示词末尾添加 cache_control（首次请求创建缓存）
2. 后续请求保持相同前缀，自动命中缓存
3. 缓存有效期 5 分钟，命中后重置
"""
from typing import List, Dict, Any


def add_cache_control_to_messages(messages: List[Dict[str, Any]]) -> None:
    """
    为消息添加 Anthropic/阿里云格式的 cache_control 标记以支持 prompt caching

    策略：
    - 优先在长系统消息（system）末尾添加 cache_control
    - 如果没有系统消息，在长用户消息（user）末尾添加
    - 在最后一个 content block 上添加 cache_control

    支持情况：
    - Anthropic: 完全支持，需要显式标记
    - 阿里云: 支持显式缓存，需 cache_control 标记
    - OpenAI: 自动忽略此字段（使用自动缓存）
    - 其他厂商: 通常会忽略不认识的字段

    Args:
        messages: 消息列表（会被原地修改）
    """
    if not messages:
        return

    # 策略1：找到最长的 system 消息，在其末尾添加 cache_control
    system_msg_idx = -1
    system_msg_length = 0

    for i, msg in enumerate(messages):
        if msg.get('role') == 'system':
            content = msg.get('content', '')
            length = 0
            if isinstance(content, str):
                length = len(content)
            elif isinstance(content, list):
                for block in content:
                    if isinstance(block, dict):
                        text = block.get('text', '')
                        if isinstance(text, str):
                            length += len(text)

            if length > system_msg_length:
                system_msg_length = length
                system_msg_idx = i

    # 如果找到足够长的系统消息（> 500 字符，约 125 tokens），在其末尾添加 cache_control
    if system_msg_idx >= 0 and system_msg_length > 500:
        _add_cache_control_to_message(messages[system_msg_idx])
        return

    # 策略2：找到第一个足够长的 user 消息，在其末尾添加 cache_control
    for msg in messages:
        if msg.get('role') == 'user':
            content = msg.get('content', '')
            length = 0
            if isinstance(content, str):
                length = len(content)
            elif isinstance(content, list):
                for block in content:
                    if isinstance(block, dict):
                        text = block.get('text', '')
                        if isinstance(text, str):
                            length += len(text)

            # 如果用户消息足够长（> 1000 字符，约 250 tokens），添加 cache_control
            if length > 1000:
                _add_cache_control_to_message(msg)
                return

    # 策略3：如果没有找到合适的长消息，在最后一个非-tool 消息上添加
    for msg in reversed(messages):
        role = msg.get('role')
        if role in ['system', 'user', 'assistant']:
            _add_cache_control_to_message(msg)
            return


def _add_cache_control_to_message(msg: Dict[str, Any]) -> None:
    """
    在单个消息的最后一个 content block 上添加 cache_control

    Args:
        msg: 消息字典（会被原地修改）
    """
    content = msg.get('content')

    if isinstance(content, list) and len(content) > 0:
        # 如果 content 是列表（多模态格式），在最后一个 block 上添加 cache_control
        last_block = content[-1]
        if isinstance(last_block, dict):
            # 避免重复添加
            if 'cache_control' not in last_block:
                last_block['cache_control'] = {'type': 'ephemeral'}
    elif isinstance(content, str) and content:
        # 如果 content 是字符串，转换为列表格式并添加 cache_control
        msg['content'] = [
            {'type': 'text', 'text': content, 'cache_control': {'type': 'ephemeral'}}
        ]
    # 如果 content 为空或为其他类型，不添加 cache_control


def should_enable_caching(messages: List[Dict[str, Any]], min_tokens: int = 1024) -> bool:
    """
    判断是否满足启用 prompt caching 的条件

    Args:
        messages: 消息列表
        min_tokens: 最小 token 数（阿里云显式缓存默认 1024）

    Returns:
        bool: 是否满足条件
    """
    # 简单估算 token 数（实际应该使用 tokenizer）
    total_chars = 0
    for msg in messages:
        content = msg.get('content', '')
        if isinstance(content, str):
            total_chars += len(content)
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict):
                    text = block.get('text', '')
                    if isinstance(text, str):
                        total_chars += len(text)

    # 粗略估算：1 token ≈ 4 字符
    estimated_tokens = total_chars // 4
    return estimated_tokens >= min_tokens
