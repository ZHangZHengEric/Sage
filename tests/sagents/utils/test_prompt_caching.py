"""prompt_caching.add_cache_control_to_messages 单元测试。

覆盖：
- 多段 system 时按 cache_segments 在 stable / semi_stable 末尾各打 1 个断点；
- 末尾滚动 user/assistant 消息再多 1 个断点；
- 总断点不超过 max_breakpoints；
- 老路径（cache_segments 缺省）保持单断点行为不破坏存量调用。
"""
from __future__ import annotations

import copy

from sagents.utils.prompt_caching import add_cache_control_to_messages


def _has_cc(msg):
    content = msg.get("content")
    if isinstance(content, list):
        return any(isinstance(b, dict) and "cache_control" in b for b in content)
    return False


def _count_cc(messages):
    return sum(1 for m in messages if _has_cc(m))


def _make_messages():
    return [
        {"role": "system", "content": "stable role definition " * 30},
        {"role": "system", "content": "skills + active skills " * 30},
        {"role": "system", "content": "system_context + workspace volatile " * 30},
        {"role": "user", "content": "first user " * 30},
        {"role": "assistant", "content": "assistant reply " * 30},
        {"role": "user", "content": "latest user message " * 30},
    ]


def test_multi_breakpoints_on_stable_and_semi_segments():
    messages = _make_messages()
    segments = ["stable", "semi_stable", "volatile", None, None, None]
    add_cache_control_to_messages(messages, cache_segments=segments)
    # 期望：stable + semi_stable + 末尾 user，共 3 个断点
    assert _has_cc(messages[0])
    assert _has_cc(messages[1])
    assert not _has_cc(messages[2])  # volatile 段不参与
    assert _has_cc(messages[-1])
    assert _count_cc(messages) == 3


def test_multi_breakpoints_respect_max():
    messages = _make_messages() + [
        {"role": "system", "content": "extra stable segment " * 30},
        {"role": "system", "content": "extra semi segment " * 30},
    ]
    segments = ["stable", "semi_stable", "volatile", None, None, None, "stable", "semi_stable"]
    add_cache_control_to_messages(messages, cache_segments=segments, max_breakpoints=3)
    # 上限 3：会落在前 3 个 stable/semi 上，末尾 user 此时已无名额
    assert _count_cc(messages) == 3


def test_multi_breakpoints_skip_volatile_only():
    """全部段都是 volatile 时退化为老的回退策略。"""
    messages = _make_messages()
    segments = [None, None, "volatile", None, None, None]
    add_cache_control_to_messages(messages, cache_segments=segments)
    # 没有 stable/semi 段 → 走单断点回退（最长 system）
    assert _count_cc(messages) == 1


def test_legacy_single_breakpoint_when_no_segments():
    """cache_segments=None 时维持老路径：最长 system 上单断点。"""
    messages = _make_messages()
    add_cache_control_to_messages(messages)
    assert _count_cc(messages) == 1
    # 三条 system 长度差不多，第一条最长不一定，至少应在 system 段中
    assert any(_has_cc(m) for m in messages[:3])


def test_legacy_user_breakpoint_when_no_long_system():
    messages = [
        {"role": "system", "content": "short"},
        {"role": "user", "content": "u" * 1500},
    ]
    add_cache_control_to_messages(messages)
    assert _has_cc(messages[1])
    assert not _has_cc(messages[0])


def test_idempotent_no_double_cache_control():
    """重复调用不应在已经有 cache_control 的 block 上重复写入。"""
    messages = _make_messages()
    segments = ["stable", "semi_stable", "volatile", None, None, None]
    add_cache_control_to_messages(messages, cache_segments=segments)
    snapshot = copy.deepcopy(messages)
    add_cache_control_to_messages(messages, cache_segments=segments)
    assert messages == snapshot
