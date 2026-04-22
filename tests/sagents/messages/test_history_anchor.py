#!/usr/bin/env python3
"""
Test history anchor / active_start_index 的新语义。

覆盖 2026-04-22 上下文收口改造后的关键不变量：
1. active_start_index 不再由 token budget 驱动
2. 仅由"最近一次 compress_conversation_history 工具调用"位置决定
3. extract_all_context_messages 不再按 active_start_index 硬截断
4. add_messages 自动刷新锚点
5. memory 工具历史边界以锚点划分
6. 旧 context_budget_config 配置项（recent_turns 等）向后兼容
"""

from datetime import datetime
from typing import Dict, List, Optional
from unittest.mock import MagicMock

from sagents.context.messages.message import MessageChunk, MessageRole, MessageType
from sagents.context.messages.message_manager import MessageManager


def _make(role: str, content: str = "",
          msg_type: Optional[str] = None,
          tool_calls: Optional[List[Dict]] = None,
          tool_call_id: Optional[str] = None) -> MessageChunk:
    if msg_type is None:
        if role == MessageRole.USER.value:
            msg_type = MessageType.USER_INPUT.value
        elif role == MessageRole.ASSISTANT.value:
            # 与既有测试一致：默认走 FINAL_ANSWER 才会被
            # extract_all_context_messages 的 allowed_message_types 接收
            msg_type = MessageType.FINAL_ANSWER.value
        elif role == MessageRole.TOOL.value:
            msg_type = MessageType.TOOL_CALL_RESULT.value
        else:
            msg_type = MessageType.FINAL_ANSWER.value
    return MessageChunk(
        role=role,
        content=content,
        type=msg_type,
        tool_calls=tool_calls,
        tool_call_id=tool_call_id,
        timestamp=datetime.now().timestamp(),
    )


def _compress_tc(idx: int = 1) -> List[Dict]:
    return [{
        "id": f"call_compress_{idx}",
        "type": "function",
        "function": {"name": "compress_conversation_history", "arguments": "{}"},
    }]


# ---------- compute_history_anchor_index ----------

class TestComputeHistoryAnchorIndex:
    def test_empty_messages_returns_none(self):
        mm = MessageManager()
        assert mm.compute_history_anchor_index() is None

    def test_no_compress_tool_returns_none(self):
        mm = MessageManager()
        mm.messages = [
            _make(MessageRole.USER.value, "u1"),
            _make(MessageRole.ASSISTANT.value, "a1"),
            _make(MessageRole.USER.value, "u2"),
        ]
        assert mm.compute_history_anchor_index() is None

    def test_single_compress_tool_returns_its_index(self):
        mm = MessageManager()
        mm.messages = [
            _make(MessageRole.USER.value, "u1"),
            _make(MessageRole.ASSISTANT.value, "",
                  msg_type=MessageType.TOOL_CALL.value,
                  tool_calls=_compress_tc(1)),  # idx=1
            _make(MessageRole.TOOL.value, "summary",
                  tool_call_id="call_compress_1"),
            _make(MessageRole.USER.value, "u2"),
        ]
        assert mm.compute_history_anchor_index() == 1

    def test_multiple_compress_tools_returns_latest(self):
        mm = MessageManager()
        mm.messages = [
            _make(MessageRole.USER.value, "u1"),
            _make(MessageRole.ASSISTANT.value, "",
                  msg_type=MessageType.TOOL_CALL.value,
                  tool_calls=_compress_tc(1)),  # idx=1
            _make(MessageRole.TOOL.value, "s1", tool_call_id="call_compress_1"),
            _make(MessageRole.USER.value, "u2"),
            _make(MessageRole.ASSISTANT.value, "",
                  msg_type=MessageType.TOOL_CALL.value,
                  tool_calls=_compress_tc(2)),  # idx=4 (latest)
            _make(MessageRole.TOOL.value, "s2", tool_call_id="call_compress_2"),
        ]
        assert mm.compute_history_anchor_index() == 4

    def test_anchor_at_index_zero(self):
        """边界：第一条就是压缩工具调用（不常见但允许）"""
        mm = MessageManager()
        mm.messages = [
            _make(MessageRole.ASSISTANT.value, "",
                  msg_type=MessageType.TOOL_CALL.value,
                  tool_calls=_compress_tc(1)),  # idx=0
            _make(MessageRole.TOOL.value, "s", tool_call_id="call_compress_1"),
        ]
        assert mm.compute_history_anchor_index() == 0

    def test_other_tool_calls_do_not_count(self):
        """其它工具调用（非 compress_conversation_history）不应被识别为锚点"""
        mm = MessageManager()
        mm.messages = [
            _make(MessageRole.USER.value, "u1"),
            _make(MessageRole.ASSISTANT.value, "",
                  msg_type=MessageType.TOOL_CALL.value,
                  tool_calls=[{
                      "id": "x",
                      "type": "function",
                      "function": {"name": "other_tool", "arguments": "{}"},
                  }]),
            _make(MessageRole.TOOL.value, "result", tool_call_id="x"),
        ]
        assert mm.compute_history_anchor_index() is None


# ---------- add_messages 自动刷新锚点 ----------

class TestAddMessagesRefreshesAnchor:
    def test_initial_state_is_none(self):
        mm = MessageManager()
        assert mm.active_start_index is None

    def test_adding_normal_messages_keeps_anchor_none(self):
        mm = MessageManager()
        mm.add_messages(_make(MessageRole.USER.value, "u1"))
        mm.add_messages(_make(MessageRole.ASSISTANT.value, "a1"))
        assert mm.active_start_index is None

    def test_adding_compress_tool_call_sets_anchor(self):
        mm = MessageManager()
        mm.add_messages(_make(MessageRole.USER.value, "u1"))
        mm.add_messages(_make(MessageRole.ASSISTANT.value, "a1"))
        # 第三条加入压缩工具调用
        mm.add_messages(_make(
            MessageRole.ASSISTANT.value, "",
            msg_type=MessageType.TOOL_CALL.value,
            tool_calls=_compress_tc(1),
        ))
        assert mm.active_start_index == 2

    def test_adding_more_after_compress_keeps_anchor(self):
        mm = MessageManager()
        mm.add_messages(_make(MessageRole.USER.value, "u1"))
        mm.add_messages(_make(
            MessageRole.ASSISTANT.value, "",
            msg_type=MessageType.TOOL_CALL.value,
            tool_calls=_compress_tc(1),
        ))
        mm.add_messages(_make(MessageRole.TOOL.value, "s",
                              tool_call_id="call_compress_1"))
        mm.add_messages(_make(MessageRole.USER.value, "u2"))
        # anchor 仍指向 idx=1（最近的压缩调用），不会跟着新消息漂移
        assert mm.active_start_index == 1

    def test_second_compress_call_advances_anchor(self):
        mm = MessageManager()
        mm.add_messages(_make(MessageRole.USER.value, "u1"))
        mm.add_messages(_make(
            MessageRole.ASSISTANT.value, "",
            msg_type=MessageType.TOOL_CALL.value,
            tool_calls=_compress_tc(1),
        ))
        mm.add_messages(_make(MessageRole.TOOL.value, "s1",
                              tool_call_id="call_compress_1"))
        assert mm.active_start_index == 1

        mm.add_messages(_make(MessageRole.USER.value, "u2"))
        mm.add_messages(_make(
            MessageRole.ASSISTANT.value, "",
            msg_type=MessageType.TOOL_CALL.value,
            tool_calls=_compress_tc(2),
        ))
        # anchor 推进到新的压缩调用位置
        assert mm.active_start_index == 4


# ---------- extract_all_context_messages 不再被 active_start_index 硬截断 ----------

class TestExtractIgnoresActiveStartIndex:
    def _build_session(self) -> MessageManager:
        mm = MessageManager()
        mm.messages = [
            _make(MessageRole.USER.value, "u1"),
            _make(MessageRole.ASSISTANT.value, "a1"),
            _make(MessageRole.USER.value, "u2"),
            _make(MessageRole.ASSISTANT.value, "a2"),
        ]
        return mm

    def test_manual_active_start_index_does_not_drop_messages(self):
        """手动把 active_start_index 设到 2，旧逻辑会丢前两条；
        新逻辑不再做此硬截断，所有消息都应进入结果。"""
        mm = self._build_session()
        mm.set_active_start_index(2)

        result = mm.extract_all_context_messages(
            recent_turns=0, last_turn_user_only=False
        )
        contents = [m.content for m in result]
        # 4 条全保留
        assert "u1" in contents
        assert "a1" in contents
        assert "u2" in contents
        assert "a2" in contents
        assert len(result) == 4

    def test_recent_turns_still_works(self):
        """recent_turns 仍然控制对话轮数（辅助 Agent 依赖）"""
        mm = self._build_session()
        # 只取最近 1 轮
        result = mm.extract_all_context_messages(
            recent_turns=1, last_turn_user_only=False
        )
        contents = [m.content for m in result]
        assert "u1" not in contents
        assert "u2" in contents
        assert "a2" in contents

    def test_compress_anchor_still_filters(self):
        """有压缩调用时仍然只保留 user + 最新压缩 + 之后"""
        mm = MessageManager()
        mm.messages = [
            _make(MessageRole.USER.value, "u1"),
            _make(MessageRole.ASSISTANT.value, "a1"),
            _make(MessageRole.USER.value, "u2"),
            _make(MessageRole.ASSISTANT.value, "",
                  msg_type=MessageType.TOOL_CALL.value,
                  tool_calls=_compress_tc(1)),
            _make(MessageRole.TOOL.value, "summary",
                  tool_call_id="call_compress_1"),
            _make(MessageRole.USER.value, "u3"),
        ]
        result = mm.extract_all_context_messages(
            recent_turns=0, last_turn_user_only=False
        )
        contents = [m.content for m in result]
        # u1/a1 应被压缩锚点逻辑过滤掉
        assert "u1" not in contents
        assert "a1" not in contents
        assert "u2" in contents
        assert "summary" in contents
        assert "u3" in contents


# ---------- prepare_history_split 新行为 ----------

class TestPrepareHistorySplit:
    def test_returns_budget_info_only(self):
        mm = MessageManager()
        mm.messages = [_make(MessageRole.USER.value, "u1")]
        result = mm.prepare_history_split({"agent_mode": "auto"})

        assert "budget_info" in result
        assert isinstance(result["budget_info"], dict)
        # 旧字段已不再返回
        assert "split_result" not in result
        assert "current_query" not in result

    def test_refreshes_anchor_when_compress_tool_present(self):
        mm = MessageManager()
        mm.messages = [
            _make(MessageRole.USER.value, "u1"),
            _make(MessageRole.ASSISTANT.value, "",
                  msg_type=MessageType.TOOL_CALL.value,
                  tool_calls=_compress_tc(1)),
        ]
        # 故意先设错的值
        mm.set_active_start_index(99)
        mm.prepare_history_split({})
        # 应被刷新到正确的锚点
        assert mm.active_start_index == 1

    def test_refreshes_anchor_to_none_when_no_compress(self):
        mm = MessageManager()
        mm.messages = [_make(MessageRole.USER.value, "u1")]
        mm.set_active_start_index(0)
        mm.prepare_history_split({})
        assert mm.active_start_index is None

    def test_budget_info_propagated_to_context_budget_manager(self):
        """辅助 Agent 通过 context_budget_manager.budget_info 读取，必须填充"""
        mm = MessageManager(context_budget_config={"max_model_len": 20000})
        mm.messages = [_make(MessageRole.USER.value, "u1")]
        mm.prepare_history_split({})
        assert mm.context_budget_manager.budget_info is not None
        assert "active_budget" in mm.context_budget_manager.budget_info
        assert "max_new_tokens" in mm.context_budget_manager.budget_info


# ---------- 向后兼容 ----------

class TestBackwardCompat:
    def test_legacy_recent_turns_in_config_does_not_crash(self):
        """examples/sage_*.py 仍会传 recent_turns，应被静默忽略"""
        mm = MessageManager(context_budget_config={
            "max_model_len": 20000,
            "recent_turns": 5,  # 已废弃的 key
            "history_ratio": 0.2,
            "active_ratio": 0.3,
            "max_new_message_ratio": 0.5,
        })
        assert mm is not None
        # 不再有 recent_turns 字段
        assert not hasattr(mm.context_budget_manager, "recent_turns")

    def test_legacy_dropped_history_bridge_budget_does_not_crash(self):
        """旧的桥接预算配置项也应被静默忽略"""
        mm = MessageManager(context_budget_config={
            "dropped_history_bridge_budget": 1000,
        })
        assert mm is not None
        assert not hasattr(mm, "dropped_history_bridge_budget")


# ---------- memory 工具历史边界 ----------

class TestMemoryToolHistoryBoundary:
    def _build_session_context(self, mm: MessageManager) -> MagicMock:
        ctx = MagicMock()
        ctx.message_manager = mm
        ctx.agent_config = {}
        return ctx

    def test_no_compress_anchor_returns_empty_history(self):
        from sagents.tool.impl.memory_tool import (
            MemoryTool,
            SessionHistoryRetriever,
        )

        mm = MessageManager()
        mm.messages = [
            _make(MessageRole.USER.value, "u1"),
            _make(MessageRole.ASSISTANT.value, "a1"),
            _make(MessageRole.USER.value, "u2"),
        ]
        ctx = self._build_session_context(mm)

        retriever = SessionHistoryRetriever(MemoryTool())
        # 清缓存
        SessionHistoryRetriever._history_cache.clear()
        history = retriever._get_history_messages("sess_no_anchor", ctx)
        assert history == []

    def test_with_anchor_returns_messages_before_anchor(self):
        from sagents.tool.impl.memory_tool import (
            MemoryTool,
            SessionHistoryRetriever,
        )

        mm = MessageManager()
        mm.messages = [
            _make(MessageRole.USER.value, "u1"),
            _make(MessageRole.ASSISTANT.value, "a1"),
            _make(MessageRole.USER.value, "u2"),
            _make(MessageRole.ASSISTANT.value, "",
                  msg_type=MessageType.TOOL_CALL.value,
                  tool_calls=_compress_tc(1)),  # anchor 在 idx=3
            _make(MessageRole.TOOL.value, "summary",
                  tool_call_id="call_compress_1"),
            _make(MessageRole.USER.value, "u3"),
        ]
        ctx = self._build_session_context(mm)

        retriever = SessionHistoryRetriever(MemoryTool())
        SessionHistoryRetriever._history_cache.clear()
        history = retriever._get_history_messages("sess_with_anchor", ctx)

        contents = [m.content for m in history]
        # 锚点之前的 3 条
        assert contents == ["u1", "a1", "u2"]

    def test_anchor_at_index_zero_returns_empty(self):
        """anchor=0 表示第一条就是压缩调用，前面没有可检索内容"""
        from sagents.tool.impl.memory_tool import (
            MemoryTool,
            SessionHistoryRetriever,
        )

        mm = MessageManager()
        mm.messages = [
            _make(MessageRole.ASSISTANT.value, "",
                  msg_type=MessageType.TOOL_CALL.value,
                  tool_calls=_compress_tc(1)),  # anchor=0
            _make(MessageRole.TOOL.value, "s", tool_call_id="call_compress_1"),
        ]
        ctx = self._build_session_context(mm)

        retriever = SessionHistoryRetriever(MemoryTool())
        SessionHistoryRetriever._history_cache.clear()
        history = retriever._get_history_messages("sess_zero_anchor", ctx)
        assert history == []
