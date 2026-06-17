#!/usr/bin/env python3
"""
Test CompressHistoryTool
测试压缩历史消息工具的各项功能
"""

import asyncio
import json
import sys
from datetime import datetime
from typing import List, Dict, Optional

from sagents.context.messages.message import MessageChunk, MessageRole, MessageType
from sagents.tool.impl.compress_history_tool import CompressHistoryTool


class TestCompressHistoryTool:
    """Test CompressHistoryTool"""

    def setup_method(self):
        """Setup test instance"""
        self.tool = CompressHistoryTool()

    def create_message(
        self,
        role: str,
        content: str,
        msg_type: Optional[str] = None,
        tool_calls: List[Dict] = None,  # pyright: ignore[reportArgumentType]
        tool_call_id: str = None,  # pyright: ignore[reportArgumentType]
    ) -> MessageChunk:
        """Create test message"""
        if msg_type is None:
            if role == MessageRole.USER.value:
                msg_type = MessageType.USER_INPUT.value
            elif role == MessageRole.ASSISTANT.value:
                msg_type = MessageType.ASSISTANT_TEXT.value
            elif role == MessageRole.SYSTEM.value:
                msg_type = MessageType.SYSTEM.value
            elif role == MessageRole.TOOL.value:
                msg_type = MessageType.TOOL_CALL_RESULT.value
            else:
                msg_type = MessageType.ASSISTANT_TEXT.value
        return MessageChunk(
            role=role,
            content=content,
            type=msg_type,
            tool_calls=tool_calls,
            tool_call_id=tool_call_id,
            timestamp=datetime.now().timestamp(),
        )

    def test_calculate_tokens(self):
        """Test: _calculate_tokens method"""
        # Test empty content
        assert self.tool._calculate_tokens("") == 0
        assert self.tool._calculate_tokens(None) == 0

        # Test Chinese characters (0.6 tokens per char)
        chinese_text = "你好世界"  # 4 chars
        assert self.tool._calculate_tokens(chinese_text) == 2  # 4 * 0.6 = 2.4 -> 2

        # Test English letters (0.25 tokens per char)
        english_text = "Hello"  # 5 chars
        assert self.tool._calculate_tokens(english_text) == 1  # 5 * 0.25 = 1.25 -> 1

        # Test digits (0.2 tokens per char)
        digits = "12345"  # 5 chars
        assert self.tool._calculate_tokens(digits) == 1  # 5 * 0.2 = 1.0 -> 1

        # Test mixed content
        mixed = "Hello世界123"  # 5 + 2 + 3 = 10 chars
        # 5*0.25 + 2*0.6 + 3*0.2 = 1.25 + 1.2 + 0.6 = 3.05 -> 3
        assert self.tool._calculate_tokens(mixed) == 3

        print("OK: _calculate_tokens")

    def test_format_messages_for_compression(self):
        """Test: _format_messages_for_compression method"""
        messages = [
            self.create_message(MessageRole.USER.value, "User message"),
            self.create_message(MessageRole.ASSISTANT.value, "Assistant response"),
        ]

        result = self.tool._format_messages_for_compression(messages)

        assert "User message" in result
        assert "Assistant response" in result
        print("OK: _format_messages_for_compression")

    def test_compress_conversation_history_uses_caller_range_metadata(self):
        """Test: caller-selected range is recorded in structured output"""
        messages = [
            self.create_message(MessageRole.USER.value, "User message 1"),
            self.create_message(MessageRole.ASSISTANT.value, "Assistant response 1"),
        ]
        messages[0].message_id = "u1"
        messages[1].message_id = "a1"

        async def fake_call(messages_text, session_id):
            assert "User message 1" in messages_text
            assert session_id == "test_session"
            return "summary text"

        self.tool._call_llm_for_compression = fake_call
        result = asyncio.run(
            self.tool.compress_conversation_history(
                messages,
                "test_session",
                source_message_ids=["u1", "a1"],
                source_start_message_id="u1",
                source_end_message_id="a1",
            )
        )

        assert result["status"] == "success"
        payload = result["data"]
        assert payload["summary"] == "summary text"
        assert payload["source_message_ids"] == ["u1", "a1"]
        assert payload["source_range"] == {
            "start_message_id": "u1",
            "end_message_id": "a1",
        }
        assert '"summary": "summary text"' in result["message"]

    def test_compress_conversation_history_empty_messages(self):
        """Test: compress_conversation_history with empty messages"""
        result = asyncio.run(
            self.tool.compress_conversation_history([], "test_session")
        )

        assert result["status"] == "success"
        assert "没有消息需要压缩" in result["message"]
        print("OK: compress_conversation_history empty messages")

    def test_compress_conversation_history_compresses_caller_input(self):
        """Test: non-empty caller input is passed to the summarizer"""
        messages = [
            self.create_message(MessageRole.USER.value, "User"),
            self.create_message(MessageRole.ASSISTANT.value, "Assistant"),
        ]

        async def fake_call(messages_text, session_id):
            assert "User" in messages_text
            assert "Assistant" in messages_text
            return "short summary"

        self.tool._call_llm_for_compression = fake_call
        result = asyncio.run(
            self.tool.compress_conversation_history(messages, "test_session")
        )

        assert result["status"] == "success"
        assert result["data"]["summary"] == "short summary"
        assert len(result["data"]["source_message_ids"]) == 2
        print("OK: compress_conversation_history caller input")

    def test_compress_conversation_history_uses_structured_json_output(self):
        """Test: JSON compact output populates structured fields."""
        messages = [
            self.create_message(MessageRole.USER.value, "User"),
            self.create_message(MessageRole.ASSISTANT.value, "Assistant"),
        ]

        async def fake_call(messages_text, session_id):
            return json.dumps(
                {
                    "summary": "structured summary",
                    "decisions": ["use manifest"],
                    "open_tasks": ["run matrix tests"],
                    "files_touched": ["sagents/context/messages/message_manager.py"],
                    "commands_run": ["pytest"],
                    "important_errors": ["none"],
                    "user_requirements": ["do not fail on non-json"],
                },
                ensure_ascii=False,
            )

        self.tool._call_llm_for_compression = fake_call
        result = asyncio.run(
            self.tool.compress_conversation_history(messages, "test_session")
        )

        assert result["status"] == "success"
        assert result["data"]["summary"] == "structured summary"
        assert result["data"]["decisions"] == ["use manifest"]
        assert result["data"]["open_tasks"] == ["run matrix tests"]
        assert result["data"]["stats"]["summary_parse_status"] == "json"

    def test_compress_conversation_history_falls_back_when_output_is_not_json(self):
        """Test: non-JSON compact output is still a successful compression."""
        messages = [
            self.create_message(MessageRole.USER.value, "User"),
            self.create_message(MessageRole.ASSISTANT.value, "Assistant"),
        ]

        async def fake_call(messages_text, session_id):
            return "plain summary without json"

        self.tool._call_llm_for_compression = fake_call
        result = asyncio.run(
            self.tool.compress_conversation_history(messages, "test_session")
        )

        assert result["status"] == "success"
        assert result["data"]["summary"] == "plain summary without json"
        assert result["data"]["decisions"] == []
        assert result["data"]["stats"]["summary_parse_status"] == "fallback_text"

    def test_compression_levels_config(self):
        """Test: compression levels configuration"""
        assert "light" in self.tool.compression_levels
        assert "medium" in self.tool.compression_levels
        assert "heavy" in self.tool.compression_levels

        assert "tool_truncate" in self.tool.compression_levels["light"]
        assert "assistant_summary" in self.tool.compression_levels["light"]
        print("OK: compression_levels_config")


class TestCompressHistoryToolIntegration:
    """Integration tests for CompressHistoryTool (require mock session)"""

    def create_message(self, role: str, content: str) -> MessageChunk:
        """Create test message"""
        return MessageChunk(
            role=role, content=content, timestamp=datetime.now().timestamp()
        )

    def test_end_to_end_compression_flow(self):
        """Test: End-to-end compression flow with mock"""
        tool = CompressHistoryTool()

        # Create a realistic message sequence
        messages = [
            self.create_message(
                MessageRole.SYSTEM.value, "You are a helpful assistant."
            ),
            self.create_message(
                MessageRole.USER.value, "Hello, can you help me with Python?"
            ),
            self.create_message(
                MessageRole.ASSISTANT.value, "Sure! What do you need help with?"
            ),
            self.create_message(
                MessageRole.USER.value, "I want to learn about list comprehensions."
            ),
            self.create_message(
                MessageRole.ASSISTANT.value,
                "List comprehensions are a concise way to create lists...",
            ),
            self.create_message(MessageRole.USER.value, "Can you show me an example?"),
        ]

        formatted = tool._format_messages_for_compression(messages[1:5])
        assert "Hello, can you help me with Python?" in formatted
        assert "List comprehensions are a concise way" in formatted
        assert "Can you show me an example?" not in formatted

        print("OK: End-to-end compression flow")


def run_tests():
    """Run all tests"""
    test_class = TestCompressHistoryTool()
    integration_class = TestCompressHistoryToolIntegration()

    print("\n" + "=" * 60)
    print("Testing CompressHistoryTool")
    print("=" * 60 + "\n")

    tests = [
        # Unit tests
        ("test_calculate_tokens", test_class.test_calculate_tokens),
        (
            "test_format_messages_for_compression",
            test_class.test_format_messages_for_compression,
        ),
        (
            "test_compress_conversation_history_uses_caller_range_metadata",
            test_class.test_compress_conversation_history_uses_caller_range_metadata,
        ),
        (
            "test_compress_conversation_history_empty_messages",
            test_class.test_compress_conversation_history_empty_messages,
        ),
        (
            "test_compress_conversation_history_compresses_caller_input",
            test_class.test_compress_conversation_history_compresses_caller_input,
        ),
        ("test_compression_levels_config", test_class.test_compression_levels_config),
        # Integration tests
        (
            "test_end_to_end_compression_flow",
            integration_class.test_end_to_end_compression_flow,
        ),
    ]

    passed = 0
    failed = 0

    for test_name, test_func in tests:
        try:
            # Setup for each test
            if hasattr(test_class, "setup_method"):
                test_class.setup_method()
            test_func()
            passed += 1
        except AssertionError as e:
            print(f"FAILED: {test_name} - {e}")
            import traceback

            traceback.print_exc()
            failed += 1
        except Exception as e:
            print(f"ERROR: {test_name} - {e}")
            import traceback

            traceback.print_exc()
            failed += 1

    print("\n" + "=" * 60)
    print(f"Test Results: {passed} passed, {failed} failed")
    print("=" * 60 + "\n")

    return failed == 0


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
