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
from typing import List, Dict, Any, Optional


_MIN_SYSTEM_LEN = 500  # 约 125 tokens
_MIN_USER_LEN = 1000  # 约 250 tokens


def _content_length(msg: Dict[str, Any]) -> int:
    content = msg.get('content', '')
    if isinstance(content, str):
        return len(content)
    if isinstance(content, list):
        total = 0
        for block in content:
            if isinstance(block, dict):
                text = block.get('text', '')
                if isinstance(text, str):
                    total += len(text)
        return total
    return 0


def add_cache_control_to_messages(
    messages: List[Dict[str, Any]],
    cache_segments: Optional[List[Optional[str]]] = None,
    max_breakpoints: int = 4,
) -> None:
    """为消息添加 Anthropic/阿里云格式的 ``cache_control`` 断点。

    多断点策略（启用条件：``cache_segments`` 不为空且包含 ``stable`` / ``semi_stable``
    标记，对应 ``prepare_unified_system_messages`` 切出的多段 system）：

    1. 在每段稳定 system（``stable`` / ``semi_stable``）末尾各打 1 个断点；
    2. 在最近一条非 ``tool`` 的滚动消息（user/assistant）末尾再打 1 个断点；
    3. 总断点数不超过 ``max_breakpoints``（Anthropic 上限 = 4）。

    回退策略（``cache_segments`` 缺失时）：保持原"最长 system → 长 user → 最后非 tool"
    单断点行为，避免破坏老调用方。

    Args:
        messages: 消息列表（会被原地修改）
        cache_segments: 与 messages 等长的段标记列表，元素为 ``stable`` / ``semi_stable``
            / ``volatile`` / ``None``。``None`` 视为非分段 system 或普通消息。
        max_breakpoints: 最大断点数，默认 4。
    """
    if not messages:
        return

    placed = 0

    # === 多段 system 策略 ===
    if cache_segments and any(seg in {"stable", "semi_stable"} for seg in cache_segments):
        for i, msg in enumerate(messages):
            if placed >= max_breakpoints:
                return
            if msg.get('role') != 'system':
                continue
            seg = cache_segments[i] if i < len(cache_segments) else None
            if seg in {"stable", "semi_stable"} and _content_length(msg) > 0:
                _add_cache_control_to_message(msg)
                placed += 1

        # 末尾滚动断点：最近一条 user/assistant 非 tool 消息
        if placed < max_breakpoints:
            for j in range(len(messages) - 1, -1, -1):
                role = messages[j].get('role')
                if role in {'user', 'assistant'} and _content_length(messages[j]) > 0:
                    _add_cache_control_to_message(messages[j])
                    placed += 1
                    break
        return

    # === 单断点回退策略（保持向后兼容） ===
    system_msg_idx = -1
    system_msg_length = 0
    for i, msg in enumerate(messages):
        if msg.get('role') == 'system':
            length = _content_length(msg)
            if length > system_msg_length:
                system_msg_length = length
                system_msg_idx = i

    if system_msg_idx >= 0 and system_msg_length > _MIN_SYSTEM_LEN:
        _add_cache_control_to_message(messages[system_msg_idx])
        return

    for msg in messages:
        if msg.get('role') == 'user' and _content_length(msg) > _MIN_USER_LEN:
            _add_cache_control_to_message(msg)
            return

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
