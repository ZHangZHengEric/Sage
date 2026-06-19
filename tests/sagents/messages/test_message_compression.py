import unittest
import time
import tempfile
from sagents.context.messages.message_manager import MessageManager
from sagents.context.messages.message import MessageChunk, MessageRole, MessageType


class TestMessageCompression(unittest.TestCase):
    def setUp(self):
        self.manager = MessageManager()
        self.long_content = "A" * 1000  # 1000 characters
        self.tool_output = "START" + "M" * 800 + "END"  # 810 chars
        self.thinking_content = "Here is the result: <thinking>Let me think about this step by step...</thinking> The answer is 42."

    def _message_type_for_role(self, role: str) -> str:
        if role == MessageRole.USER.value:
            return MessageType.USER_INPUT.value
        if role == MessageRole.ASSISTANT.value:
            return MessageType.ASSISTANT_TEXT.value
        if role == MessageRole.TOOL.value:
            return MessageType.TOOL_CALL_RESULT.value
        if role == MessageRole.SYSTEM.value:
            return MessageType.SYSTEM.value
        return MessageType.ASSISTANT_TEXT.value

    def create_message(self, role, content, timestamp=None):
        tool_call_id = None
        if role == MessageRole.TOOL.value:
            tool_call_id = "call_12345"  # Dummy ID for tool messages

        msg = MessageChunk(
            role=role,
            content=content,
            type=self._message_type_for_role(role),
            tool_call_id=tool_call_id,
        )
        if timestamp:
            msg.timestamp = timestamp
        return msg

    def create_assistant_tool_call(self, name: str, call_id: str):
        return MessageChunk(
            role=MessageRole.ASSISTANT.value,
            content="",
            type=MessageType.TOOL_CALL.value,
            tool_calls=[
                {
                    "id": call_id,
                    "type": "function",
                    "function": {"name": name, "arguments": "{}"},
                }
            ],
        )

    def create_tool_result(self, call_id: str, content: str):
        return MessageChunk(
            role=MessageRole.TOOL.value,
            content=content,
            type=MessageType.TOOL_CALL_RESULT.value,
            tool_call_id=call_id,
        )

    def print_messages(self, title, messages):
        print(f"\n{'=' * 20} {title} {'=' * 20}")
        print(f"Total Count: {len(messages)}")
        for i, msg in enumerate(messages):
            content_display = msg.content
            if content_display and len(content_display) > 100:
                content_display = content_display[:50] + "..." + content_display[-50:]
            print(
                f"[{i}] Role: {msg.role:<10} | Len: {len(msg.content) if msg.content else 0:<5} | Content: {content_display}"
            )
        print("=" * 60)

    def test_level_1_compression(self):
        """规则压缩将旧的大 tool result 可逆 offload 到 artifact"""
        messages = [
            self.create_message(MessageRole.SYSTEM.value, "System Prompt"),
            self.create_message(MessageRole.USER.value, "User Request"),
            self.create_message(MessageRole.TOOL.value, "T" * 20000),
            self.create_message(MessageRole.ASSISTANT.value, self.thinking_content),
            *[
                self.create_message(MessageRole.ASSISTANT.value, f"tail {idx}")
                for idx in range(20)
            ],
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            compressed = MessageManager.build_inference_view(
                messages,
                session_id="sess-test",
                max_model_len=2000,
                artifact_root=tmpdir,
                apply_rule_compression=True,
            )
        self.print_messages("Level 1 Compression Result", compressed)

        self.assertTrue(all(msg.role != MessageRole.SYSTEM.value for msg in compressed))
        self.assertIn("[Content moved to context artifact]", compressed[1].content)  # pyright: ignore[reportArgumentType]
        self.assertTrue(compressed[1].metadata["context_artifact_ref"])
        self.assertNotIn("token_estimate:", compressed[1].content)  # pyright: ignore[reportArgumentType]

        # 规则压缩不再做不可逆 thinking 删除。
        self.assertIn("<thinking>", compressed[2].content)  # pyright: ignore[reportArgumentType]
        self.assertIn("The answer is 42", compressed[2].content)  # pyright: ignore[reportArgumentType]

    def test_artifact_reference_is_stable_across_inference_views(self):
        """同一条历史 tool result 多次 offload 时，prompt reference 保持稳定。"""
        messages = [
            self.create_message(MessageRole.USER.value, "User Request"),
            self.create_message(MessageRole.TOOL.value, "T" * 20000),
            *[
                self.create_message(MessageRole.ASSISTANT.value, f"tail {idx}")
                for idx in range(20)
            ],
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            first = MessageManager.build_inference_view(
                messages,
                session_id="sess-stable-artifact",
                max_model_len=2000,
                artifact_root=tmpdir,
                apply_rule_compression=True,
            )
            second = MessageManager.build_inference_view(
                messages,
                session_id="sess-stable-artifact",
                max_model_len=2000,
                artifact_root=tmpdir,
                apply_rule_compression=True,
            )

        self.assertEqual(first[1].content, second[1].content)
        self.assertIn("[Content moved to context artifact]", first[1].content)  # pyright: ignore[reportArgumentType]
        self.assertNotIn("token_estimate:", first[1].content)  # pyright: ignore[reportArgumentType]

    def test_rule_compression_protects_last_todo_write_result(self):
        messages = [
            self.create_message(MessageRole.USER.value, "User Request"),
            self.create_assistant_tool_call("todo_write", "todo_old"),
            self.create_tool_result("todo_old", "OLD" * 7000),
            self.create_assistant_tool_call("todo_write", "todo_new"),
            self.create_tool_result("todo_new", "NEW" * 7000),
            *[
                self.create_message(MessageRole.ASSISTANT.value, f"tail {idx}")
                for idx in range(25)
            ],
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            compressed = MessageManager.build_inference_view(
                messages,
                session_id="sess-todo",
                max_model_len=2000,
                artifact_root=tmpdir,
                rule_protection_count=5,
                apply_rule_compression=True,
            )

        old_result = next(msg for msg in compressed if msg.tool_call_id == "todo_old")
        new_result = next(msg for msg in compressed if msg.tool_call_id == "todo_new")
        self.assertIn("[Content moved to context artifact]", old_result.content)  # pyright: ignore[reportArgumentType]
        self.assertNotIn("[Content moved to context artifact]", new_result.content)  # pyright: ignore[reportArgumentType]
        self.assertTrue(str(new_result.content).startswith("NEW"))

    def test_level_2_aging(self):
        """规则压缩不再因为 aging 做不可逆截断，只做 artifact offload"""
        old_time = time.time() - 25 * 3600  # 25 hours ago
        messages = [
            self.create_message(MessageRole.SYSTEM.value, "System Prompt"),
            self.create_message(MessageRole.USER.value, "Old User"),
            self.create_message(
                MessageRole.ASSISTANT.value,
                "Old Assistant Long Content " * 400,
                timestamp=old_time,
            ),
            self.create_message(MessageRole.USER.value, "New User"),
            *[
                self.create_message(MessageRole.ASSISTANT.value, f"tail {idx}")
                for idx in range(20)
            ],
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            compressed = MessageManager.build_inference_view(
                messages,
                session_id="sess-aging",
                max_model_len=2000,
                artifact_root=tmpdir,
                apply_rule_compression=True,
            )
        self.print_messages("Aging Strategy Result", compressed)

        self.assertTrue(all(msg.role != MessageRole.SYSTEM.value for msg in compressed))
        self.assertIn("[Content moved to context artifact]", compressed[1].content)  # pyright: ignore[reportArgumentType]
        self.assertNotIn("...[Content truncated]", compressed[1].content)  # pyright: ignore[reportArgumentType]

    def test_level_3_history_drop(self):
        """测试 Level 3: 历史分组丢弃"""
        # Group 1: User + Tool + Asst (Old)
        # Group 2: User + Tool + Asst (Recent)
        # Group 3: User (Current)
        messages = [
            self.create_message(MessageRole.SYSTEM.value, "System"),
            # Group 1
            self.create_message(MessageRole.USER.value, "User 1"),
            self.create_message(MessageRole.TOOL.value, "Tool 1 " * 100),
            self.create_message(MessageRole.ASSISTANT.value, "Asst 1 " * 100),
            # Group 2
            self.create_message(MessageRole.USER.value, "User 2"),
            self.create_message(MessageRole.TOOL.value, "Tool 2 " * 100),
            self.create_message(MessageRole.ASSISTANT.value, "Asst 2 " * 100),
            # Group 3 (Last)
            self.create_message(MessageRole.USER.value, "User 3 (Last)"),
        ]

        # 极小预算，迫使丢弃
        budget = 50

        compressed = MessageManager.build_token_budget_view(
            messages, budget_limit=budget
        )
        self.print_messages("Level 3 Drop Result", compressed)

        # System 不进入 prompt-local history view；每次 LLM 请求前由 AgentBase 单独构造。
        self.assertTrue(all(msg.role != MessageRole.SYSTEM.value for msg in compressed))

        # Group 1 应该完全消失 (Step B executed)
        # Group 2 应该部分消失 (Step A executed, User 2 保留但 Followers 变占位符)
        # 或者如果预算实在太小，Group 2 也可能消失。
        # 让我们看打印结果

        # Last Group (User 3) 应该在
        self.assertEqual(compressed[-1].role, MessageRole.USER.value)
        self.assertEqual(compressed[-1].content, "User 3 (Last)")

    def test_recent_protection(self):
        """测试最近 20% 预算保护"""
        # 构造一系列消息，最后一组很大，但不应被压缩
        messages = [
            self.create_message(MessageRole.SYSTEM.value, "System"),
            self.create_message(MessageRole.USER.value, "User 1"),
            self.create_message(
                MessageRole.ASSISTANT.value, "Asst 1 " * 50
            ),  # Compressible
            self.create_message(MessageRole.USER.value, "User 2 (Recent)"),
            self.create_message(
                MessageRole.TOOL.value, "Tool 2 (Recent but long) " * 20
            ),  # Should be protected if within 20%
        ]

        # 预算：假设总预算 2000。20% = 400。
        # User 2 + Tool 2 约 300 token < 400，应受保护。
        # Asst 1 应被压缩。

        # Mock calculation to ensure our test logic holds
        # 实际运行依赖 calculate_str_token_length

        compressed = MessageManager.build_token_budget_view(
            messages, budget_limit=1000
        )  # Give tight budget to force compression on unprotected
        self.print_messages("Recent Protection Result", compressed)

        # Check Tool 2 is NOT compressed (Level 1 would truncate to 200 chars + omitted)
        tool_msg = compressed[-1]
        self.assertNotIn("truncated", tool_msg.content)  # pyright: ignore[reportArgumentType]
        self.assertNotIn("omitted", tool_msg.content)  # pyright: ignore[reportArgumentType]

    def test_recent_messages_count_protection(self):
        """测试规则保护区按条数保护末尾 N 条消息"""
        # 构造场景：最近的 tool output 非常大，远超 token budget
        very_long_tool_output = "X" * 5000  # 很长的 tool 输出
        messages = [
            self.create_message(MessageRole.SYSTEM.value, "System"),
            # 旧消息组
            self.create_message(MessageRole.USER.value, "User 1 (Old)"),
            self.create_message(MessageRole.ASSISTANT.value, "Asst 1 " * 100),
            # 最近消息（末尾 2 条）
            self.create_message(MessageRole.USER.value, "User 2 (Recent)"),
            self.create_message(MessageRole.TOOL.value, very_long_tool_output),
        ]

        tiny_budget = 50

        with tempfile.TemporaryDirectory() as tmpdir:
            compressed_no_protect = MessageManager.build_inference_view(
                messages,
                session_id="sess-no-protect",
                max_model_len=tiny_budget,
                artifact_root=tmpdir,
                rule_protection_count=0,
                apply_rule_compression=True,
            )
        self.print_messages("No recent protection", compressed_no_protect)
        self.assertIn(
            "[Content moved to context artifact]", compressed_no_protect[-1].content
        )  # pyright: ignore[reportArgumentType]

        # 保护末尾 2 条（recent_messages_count=2）：User 2 和 Tool 不被压缩
        with tempfile.TemporaryDirectory() as tmpdir:
            compressed_with_protect = MessageManager.build_inference_view(
                messages,
                session_id="sess-protect",
                max_model_len=tiny_budget,
                artifact_root=tmpdir,
                rule_protection_count=2,
                apply_rule_compression=True,
            )
        self.print_messages("With recent_messages_count=2", compressed_with_protect)

        # 验证最近的 tool output 不被截断
        last_tool_msg = compressed_with_protect[-1]
        self.assertNotIn("omitted", last_tool_msg.content)  # pyright: ignore[reportArgumentType]
        self.assertNotIn("truncated", last_tool_msg.content)  # pyright: ignore[reportArgumentType]
        self.assertEqual(last_tool_msg.content, very_long_tool_output)

        # 验证 User 2（倒数第 2 条）也被保护
        user2_msg = compressed_with_protect[-2]
        self.assertEqual(user2_msg.content, "User 2 (Recent)")

    def test_token_budget_view_is_prompt_local_and_preserves_originals(self):
        messages = [
            self.create_message(MessageRole.USER.value, "U" * 5000),
            self.create_message(MessageRole.SYSTEM.value, "S" * 5000),
            self.create_message(MessageRole.ASSISTANT.value, "A" * 5000),
            self.create_message(MessageRole.TOOL.value, "T" * 5000),
        ]

        compressed = MessageManager.build_token_budget_view(messages, budget_limit=100)

        self.assertEqual(messages[0].content, "U" * 5000)
        self.assertEqual(messages[1].content, "S" * 5000)
        self.assertEqual(messages[2].content, "A" * 5000)
        self.assertEqual(messages[3].content, "T" * 5000)
        self.assertEqual(compressed[0].content, "U" * 5000)
        self.assertTrue(all(msg.role != MessageRole.SYSTEM.value for msg in compressed))
        self.assertIn("assistant content omitted", compressed[1].content)  # pyright: ignore[reportArgumentType]
        self.assertIn("tool output omitted", compressed[2].content)  # pyright: ignore[reportArgumentType]
        self.assertFalse(compressed[1].metadata.get("context_artifact_ref"))
        self.assertFalse(compressed[2].metadata.get("context_artifact_ref"))

    def test_token_budget_view_preserves_tool_call_arguments(self):
        tool_call = MessageChunk(
            role=MessageRole.ASSISTANT.value,
            content="",
            type=MessageType.TOOL_CALL.value,
            tool_calls=[
                {
                    "id": "call-1",
                    "type": "function",
                    "function": {
                        "name": "demo_tool",
                        "arguments": '{"payload": "' + "X" * 5000 + '"}',
                    },
                }
            ],
        )
        tool_result = MessageChunk(
            role=MessageRole.TOOL.value,
            content="T" * 5000,
            type=MessageType.TOOL_CALL_RESULT.value,
            tool_call_id="call-1",
        )

        compressed = MessageManager.build_token_budget_view(
            [tool_call, tool_result], budget_limit=100
        )

        self.assertEqual(
            compressed[0].tool_calls[0]["function"]["arguments"],
            '{"payload": "' + "X" * 5000 + '"}',
        )
        self.assertIn("tool output omitted", compressed[1].content)  # pyright: ignore[reportArgumentType]

    def test_token_budget_view_pair_safe_recent_protection(self):
        tool_call = MessageChunk(
            role=MessageRole.ASSISTANT.value,
            content="",
            type=MessageType.TOOL_CALL.value,
            tool_calls=[
                {
                    "id": "call-a",
                    "type": "function",
                    "function": {"name": "a", "arguments": "{}"},
                },
                {
                    "id": "call-b",
                    "type": "function",
                    "function": {"name": "b", "arguments": "{}"},
                },
            ],
        )
        result_a = MessageChunk(
            role=MessageRole.TOOL.value,
            content="A" * 5000,
            type=MessageType.TOOL_CALL_RESULT.value,
            tool_call_id="call-a",
        )
        result_b = MessageChunk(
            role=MessageRole.TOOL.value,
            content="B" * 5000,
            type=MessageType.TOOL_CALL_RESULT.value,
            tool_call_id="call-b",
        )

        compressed = MessageManager.build_token_budget_view(
            [tool_call, result_a, result_b],
            budget_limit=100,
            recent_messages_count=1,
        )

        self.assertEqual(compressed[1].content, "A" * 5000)
        self.assertEqual(compressed[2].content, "B" * 5000)

    def test_token_budget_view_keeps_visible_compression_pair_summary(self):
        raw = self.create_message(MessageRole.ASSISTANT.value, "raw")
        raw.message_id = "raw"
        tool_call = MessageChunk(
            role=MessageRole.ASSISTANT.value,
            content="",
            type=MessageType.TOOL_CALL.value,
            message_id="compress-call",
            tool_calls=[
                {
                    "id": "compress-1",
                    "type": "function",
                    "function": {
                        "name": "compress_conversation_history",
                        "arguments": "{}",
                    },
                }
            ],
            metadata={"tool_name": "compress_conversation_history"},
        )
        tool_result = MessageChunk(
            role=MessageRole.TOOL.value,
            content="summary " * 1000,
            type=MessageType.TOOL_CALL_RESULT.value,
            message_id="compress-result",
            tool_call_id="compress-1",
            metadata={
                "tool_name": "compress_conversation_history",
                "status": "success",
                "compression_anchor": True,
                "source_message_ids": ["raw"],
                "source_start_message_id": "raw",
                "source_end_message_id": "raw",
            },
        )

        compressed = MessageManager.build_token_budget_view(
            [raw, tool_call, tool_result], budget_limit=100
        )

        self.assertEqual(
            [msg.message_id for msg in compressed], ["compress-call", "compress-result"]
        )
        self.assertEqual(compressed[1].content, "summary " * 1000)


if __name__ == "__main__":
    unittest.main()
