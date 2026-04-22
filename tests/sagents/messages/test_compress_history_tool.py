#!/usr/bin/env python3
"""
Test CompressHistoryTool
测试压缩历史消息工具的各项功能
"""

import os
import asyncio
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
        tool_calls: List[Dict] = None,
        tool_call_id: str = None
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
            timestamp=datetime.now().timestamp()
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

    def test_determine_compression_range_single_user(self):
        """Test: _determine_compression_range with single user"""
        messages = [
            self.create_message(MessageRole.SYSTEM.value, "System prompt"),
            self.create_message(MessageRole.USER.value, "User message 1"),
            self.create_message(MessageRole.ASSISTANT.value, "Assistant response 1"),
            self.create_message(MessageRole.TOOL.value, "Tool result", tool_call_id="call_1"),
        ]

        result = self.tool._determine_compression_range(messages)

        # Should compress from after User to end (non-User messages after single User)
        assert result["system_end"] == 1
        assert result["to_compress_start"] == 2  # After User
        assert result["to_compress_end"] == 4    # To end
        assert result["reserved_rounds"] == 1
        print("OK: _determine_compression_range single user")

    def test_determine_compression_range_multiple_users(self):
        """Test: _determine_compression_range with multiple users"""
        messages = [
            self.create_message(MessageRole.SYSTEM.value, "System prompt"),
            self.create_message(MessageRole.USER.value, "User message 1"),
            self.create_message(MessageRole.ASSISTANT.value, "Assistant response 1"),
            self.create_message(MessageRole.USER.value, "User message 2"),
            self.create_message(MessageRole.ASSISTANT.value, "Assistant response 2"),
            self.create_message(MessageRole.USER.value, "User message 3"),
        ]

        result = self.tool._determine_compression_range(messages)

        # Should compress from after System to before last User
        assert result["system_end"] == 1
        assert result["to_compress_start"] == 1  # After System
        assert result["to_compress_end"] == 5    # Before last User (index 5)
        assert result["reserved_rounds"] == 3
        print("OK: _determine_compression_range multiple users")

    def test_determine_compression_range_no_user(self):
        """Test: _determine_compression_range with no user messages"""
        messages = [
            self.create_message(MessageRole.SYSTEM.value, "System prompt"),
            self.create_message(MessageRole.ASSISTANT.value, "Assistant only"),
        ]

        result = self.tool._determine_compression_range(messages)

        # No compression when no user
        assert result["to_compress_start"] == result["to_compress_end"]
        print("OK: _determine_compression_range no user")

    def test_determine_compression_range_only_system(self):
        """Test: _determine_compression_range with only system message"""
        messages = [
            self.create_message(MessageRole.SYSTEM.value, "System prompt"),
        ]

        result = self.tool._determine_compression_range(messages)

        # No compression when only system
        assert result["to_compress_start"] == 1
        assert result["to_compress_end"] == 1
        print("OK: _determine_compression_range only system")

    def test_compress_conversation_history_empty_messages(self):
        """Test: compress_conversation_history with empty messages"""
        result = asyncio.run(self.tool.compress_conversation_history([], "test_session"))

        assert result["status"] == "success"
        assert "没有消息需要压缩" in result["message"]
        print("OK: compress_conversation_history empty messages")

    def test_compress_conversation_history_no_compress_needed(self):
        """Test: compress_conversation_history when no compression needed"""
        messages = [
            self.create_message(MessageRole.SYSTEM.value, "System"),
            self.create_message(MessageRole.USER.value, "User"),
        ]

        result = asyncio.run(self.tool.compress_conversation_history(messages, "test_session"))

        assert result["status"] == "success"
        assert "无需压缩" in result["message"] or "没有消息需要压缩" in result["message"]
        print("OK: compress_conversation_history no compression needed")

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
            role=role,
            content=content,
            timestamp=datetime.now().timestamp()
        )

    def test_end_to_end_compression_flow(self):
        """Test: End-to-end compression flow with mock"""
        tool = CompressHistoryTool()

        # Create a realistic message sequence
        messages = [
            self.create_message(MessageRole.SYSTEM.value, "You are a helpful assistant."),
            self.create_message(MessageRole.USER.value, "Hello, can you help me with Python?"),
            self.create_message(MessageRole.ASSISTANT.value, "Sure! What do you need help with?"),
            self.create_message(MessageRole.USER.value, "I want to learn about list comprehensions."),
            self.create_message(MessageRole.ASSISTANT.value, "List comprehensions are a concise way to create lists..."),
            self.create_message(MessageRole.USER.value, "Can you show me an example?"),
        ]

        # Test compression range determination
        range_info = tool._determine_compression_range(messages)

        # Should compress messages before last User
        assert range_info["system_end"] == 1
        assert range_info["to_compress_start"] == 1
        assert range_info["to_compress_end"] == 5  # Before last User

        # Verify the messages to be compressed
        to_compress = messages[range_info["to_compress_start"]:range_info["to_compress_end"]]
        assert len(to_compress) == 4  # System not included, last User not included

        print("OK: End-to-end compression flow")


def run_tests():
    """Run all tests"""
    test_class = TestCompressHistoryTool()
    integration_class = TestCompressHistoryToolIntegration()

    print("\n" + "="*60)
    print("Testing CompressHistoryTool")
    print("="*60 + "\n")

    tests = [
        # Unit tests
        ("test_calculate_tokens", test_class.test_calculate_tokens),
        ("test_format_messages_for_compression", test_class.test_format_messages_for_compression),
        ("test_determine_compression_range_single_user", test_class.test_determine_compression_range_single_user),
        ("test_determine_compression_range_multiple_users", test_class.test_determine_compression_range_multiple_users),
        ("test_determine_compression_range_no_user", test_class.test_determine_compression_range_no_user),
        ("test_determine_compression_range_only_system", test_class.test_determine_compression_range_only_system),
        ("test_compress_conversation_history_empty_messages", test_class.test_compress_conversation_history_empty_messages),
        ("test_compress_conversation_history_no_compress_needed", test_class.test_compress_conversation_history_no_compress_needed),
        ("test_compression_levels_config", test_class.test_compression_levels_config),
        # Integration tests
        ("test_end_to_end_compression_flow", integration_class.test_end_to_end_compression_flow),
    ]

    passed = 0
    failed = 0

    for test_name, test_func in tests:
        try:
            # Setup for each test
            if hasattr(test_class, 'setup_method'):
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

    print("\n" + "="*60)
    print(f"Test Results: {passed} passed, {failed} failed")
    print("="*60 + "\n")

    return failed == 0


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
