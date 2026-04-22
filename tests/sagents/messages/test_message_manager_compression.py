#!/usr/bin/env python3
"""
Test MessageManager's extract_all_context_messages function
Especially the compress_conversation_history tool call detection logic
"""

import os
from datetime import datetime
from typing import List, Dict, Any, Optional

from sagents.context.messages.message import MessageChunk, MessageRole, MessageType
from sagents.context.messages.message_manager import MessageManager


class TestExtractAllContextMessages:
    """Test extract_all_context_messages function"""

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

    def create_compress_tool_call(self, index: int = 1) -> Dict[str, Any]:
        """Create compress_conversation_history tool call"""
        return {
            "id": f"call_compress_{index}",
            "type": "function",
            "function": {
                "name": "compress_conversation_history",
                "arguments": "{}"
            }
        }

    def test_no_compression_tool(self):
        """Test: normal extraction when no compression tool"""
        mm = MessageManager(session_id="test_session_1")

        messages = [
            self.create_message(MessageRole.USER.value, "User message 1"),
            self.create_message(MessageRole.ASSISTANT.value, "Assistant response 1", msg_type=MessageType.FINAL_ANSWER.value),
            self.create_message(MessageRole.USER.value, "User message 2"),
            self.create_message(MessageRole.ASSISTANT.value, "Assistant response 2", msg_type=MessageType.FINAL_ANSWER.value),
        ]
        mm.messages = messages

        result = mm.extract_all_context_messages(recent_turns=0, last_turn_user_only=False)

        assert len(result) == 4
        assert result[0].role == MessageRole.USER.value
        print("OK: No compression tool - normal extraction")

    def test_single_compression_tool(self):
        """Test: extract from corresponding User when single compression tool exists"""
        mm = MessageManager(session_id="test_session_2")

        messages = [
            self.create_message(MessageRole.USER.value, "User message 1"),
            self.create_message(MessageRole.ASSISTANT.value, "Assistant response 1", msg_type=MessageType.FINAL_ANSWER.value),
            self.create_message(MessageRole.USER.value, "User message 2"),
            # Compression tool call (use TOOL_CALL type)
            self.create_message(
                MessageRole.ASSISTANT.value,
                "",
                msg_type=MessageType.TOOL_CALL.value,
                tool_calls=[self.create_compress_tool_call(1)]
            ),
            self.create_message(
                MessageRole.TOOL.value,
                '{"compressed": true}',
                tool_call_id="call_compress_1",
                msg_type=MessageType.TOOL_CALL_RESULT.value
            ),
            self.create_message(MessageRole.USER.value, "User message 3"),
            self.create_message(MessageRole.ASSISTANT.value, "Assistant response 3", msg_type=MessageType.FINAL_ANSWER.value),
        ]
        mm.messages = messages

        result = mm.extract_all_context_messages(recent_turns=0, last_turn_user_only=False)

        # Should start from "User message 2" (User corresponding to compression tool)
        # User-2, Assistant(with tool), Tool, User-3, Assistant-3
        assert len(result) == 5
        assert result[0].role == MessageRole.USER.value
        assert result[0].content == "User message 2"
        assert result[1].role == MessageRole.ASSISTANT.value
        assert result[1].tool_calls is not None
        print("OK: Single compression tool - extract from corresponding User")

    def test_multiple_compression_tools_same_user(self):
        """Test: keep User and last compression tool when multiple tools under same User"""
        mm = MessageManager(session_id="test_session_3")

        messages = [
            self.create_message(MessageRole.USER.value, "User message 1"),
            # First compression tool call
            self.create_message(
                MessageRole.ASSISTANT.value,
                "",
                msg_type=MessageType.TOOL_CALL.value,
                tool_calls=[self.create_compress_tool_call(1)]
            ),
            self.create_message(
                MessageRole.TOOL.value,
                '{"compressed": true}',
                tool_call_id="call_compress_1",
                msg_type=MessageType.TOOL_CALL_RESULT.value
            ),
            # Second compression tool call (under same User)
            self.create_message(
                MessageRole.ASSISTANT.value,
                "",
                msg_type=MessageType.TOOL_CALL.value,
                tool_calls=[self.create_compress_tool_call(2)]
            ),
            self.create_message(
                MessageRole.TOOL.value,
                '{"compressed": true}',
                tool_call_id="call_compress_2",
                msg_type=MessageType.TOOL_CALL_RESULT.value
            ),
            # Third compression tool call (under same User)
            self.create_message(
                MessageRole.ASSISTANT.value,
                "",
                msg_type=MessageType.TOOL_CALL.value,
                tool_calls=[self.create_compress_tool_call(3)]
            ),
            self.create_message(
                MessageRole.TOOL.value,
                '{"compressed": true}',
                tool_call_id="call_compress_3",
                msg_type=MessageType.TOOL_CALL_RESULT.value
            ),
            self.create_message(MessageRole.USER.value, "User message 2"),
            self.create_message(MessageRole.ASSISTANT.value, "Assistant response 2", msg_type=MessageType.FINAL_ANSWER.value),
        ]
        mm.messages = messages

        result = mm.extract_all_context_messages(recent_turns=0, last_turn_user_only=False)

        # Should start from "User message 1", keep User and last compression tool and after
        # User-1, Assistant-3(with tool), Tool-3, User-2, Assistant-2
        assert len(result) == 5
        assert result[0].role == MessageRole.USER.value
        assert result[0].content == "User message 1"
        # Check it's the 3rd compression tool (last one)
        assert result[1].tool_calls[0]["id"] == "call_compress_3"
        print("OK: Multiple compression tools - keep User and last tool")

    def test_compression_tool_with_other_tools(self):
        """Test: compression tool mixed with other tools"""
        mm = MessageManager(session_id="test_session_4")

        messages = [
            self.create_message(MessageRole.USER.value, "User message 1"),
            # Normal tool call
            self.create_message(
                MessageRole.ASSISTANT.value,
                "",
                msg_type=MessageType.TOOL_CALL.value,
                tool_calls=[{
                    "id": "call_other_1",
                    "type": "function",
                    "function": {"name": "other_tool", "arguments": "{}"}
                }]
            ),
            self.create_message(
                MessageRole.TOOL.value,
                "Other tool result",
                tool_call_id="call_other_1",
                msg_type=MessageType.TOOL_CALL_RESULT.value
            ),
            self.create_message(MessageRole.USER.value, "User message 2"),
            # Compression tool call
            self.create_message(
                MessageRole.ASSISTANT.value,
                "",
                msg_type=MessageType.TOOL_CALL.value,
                tool_calls=[self.create_compress_tool_call(1)]
            ),
            self.create_message(
                MessageRole.TOOL.value,
                '{"compressed": true}',
                tool_call_id="call_compress_1",
                msg_type=MessageType.TOOL_CALL_RESULT.value
            ),
            self.create_message(MessageRole.USER.value, "User message 3"),
        ]
        mm.messages = messages

        result = mm.extract_all_context_messages(recent_turns=0, last_turn_user_only=False)

        # Should start from "User message 2"
        assert result[0].role == MessageRole.USER.value
        assert result[0].content == "User message 2"
        print("OK: Compression tool mixed with other tools")

    def test_is_compress_history_tool_call(self):
        """Test: _is_compress_history_tool_call static method"""
        # Test: is compression tool call
        compress_msg = self.create_message(
            MessageRole.ASSISTANT.value,
            "",
            tool_calls=[self.create_compress_tool_call(1)]
        )
        assert MessageManager._is_compress_history_tool_call(compress_msg) is True

        # Test: not Assistant role
        user_msg = self.create_message(MessageRole.USER.value, "User message")
        assert MessageManager._is_compress_history_tool_call(user_msg) is False

        # Test: normal tool call
        other_tool_msg = self.create_message(
            MessageRole.ASSISTANT.value,
            "",
            tool_calls=[{
                "id": "call_other",
                "type": "function",
                "function": {"name": "other_tool", "arguments": "{}"}
            }]
        )
        assert MessageManager._is_compress_history_tool_call(other_tool_msg) is False

        # Test: no tool_calls
        no_tool_msg = self.create_message(MessageRole.ASSISTANT.value, "No tools")
        assert MessageManager._is_compress_history_tool_call(no_tool_msg) is False

        print("OK: _is_compress_history_tool_call static method")

    def test_last_turn_user_only_with_compression(self):
        """Test: last_turn_user_only=True with compression tool"""
        mm = MessageManager(session_id="test_session_6")

        messages = [
            self.create_message(MessageRole.USER.value, "User message 1"),
            self.create_message(
                MessageRole.ASSISTANT.value,
                "",
                msg_type=MessageType.TOOL_CALL.value,
                tool_calls=[self.create_compress_tool_call(1)]
            ),
            self.create_message(
                MessageRole.TOOL.value,
                '{"compressed": true}',
                tool_call_id="call_compress_1",
                msg_type=MessageType.TOOL_CALL_RESULT.value
            ),
            self.create_message(MessageRole.USER.value, "User message 2"),
            self.create_message(MessageRole.ASSISTANT.value, "Assistant response 2", msg_type=MessageType.FINAL_ANSWER.value),
        ]
        mm.messages = messages

        result = mm.extract_all_context_messages(recent_turns=0, last_turn_user_only=True)

        # Should start from User-1, but last round only keeps User
        # User-1, Assistant(with tool), Tool, User-2
        assert len(result) == 4
        assert result[-1].role == MessageRole.USER.value
        assert result[-1].content == "User message 2"
        print("OK: last_turn_user_only with compression tool")

    def test_extract_messages_for_inference_static(self):
        """Test: extract_messages_for_inference static method"""
        # Test: no compression tool
        messages = [
            self.create_message(MessageRole.USER.value, "User 1"),
            self.create_message(MessageRole.ASSISTANT.value, "Assistant 1", msg_type=MessageType.FINAL_ANSWER.value),
        ]
        result = MessageManager.extract_messages_for_inference(messages)
        assert len(result) == 2

        # Test: with compression tool
        messages = [
            self.create_message(MessageRole.USER.value, "User 1"),
            self.create_message(MessageRole.ASSISTANT.value, "Assistant 1", msg_type=MessageType.FINAL_ANSWER.value),
            self.create_message(MessageRole.USER.value, "User 2"),
            self.create_message(
                MessageRole.ASSISTANT.value,
                "",
                msg_type=MessageType.TOOL_CALL.value,
                tool_calls=[self.create_compress_tool_call(1)]
            ),
            self.create_message(MessageRole.USER.value, "User 3"),
        ]
        result = MessageManager.extract_messages_for_inference(messages)
        # Should keep User-2 + compression tool + User-3
        assert len(result) == 3
        assert result[0].content == "User 2"
        assert result[1].tool_calls is not None
        assert result[2].content == "User 3"

        print("OK: extract_messages_for_inference static method")


def run_tests():
    """Run all tests"""
    test_class = TestExtractAllContextMessages()

    print("\n" + "="*60)
    print("Testing extract_all_context_messages function")
    print("="*60 + "\n")

    try:
        test_class.test_no_compression_tool()
        test_class.test_single_compression_tool()
        test_class.test_multiple_compression_tools_same_user()
        test_class.test_compression_tool_with_other_tools()
        test_class.test_is_compress_history_tool_call()
        test_class.test_last_turn_user_only_with_compression()
        test_class.test_extract_messages_for_inference_static()

        print("\n" + "="*60)
        print("All tests passed!")
        print("="*60 + "\n")
        return True
    except AssertionError as e:
        print(f"\nTest failed: {e}")
        import traceback
        traceback.print_exc()
        return False
    except Exception as e:
        print(f"\nTest execution error: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
