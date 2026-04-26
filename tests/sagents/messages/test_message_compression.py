
import unittest
import time
from sagents.context.messages.message_manager import MessageManager
from sagents.context.messages.message import MessageChunk, MessageRole, MessageType

class TestMessageCompression(unittest.TestCase):
    def setUp(self):
        self.manager = MessageManager()
        self.long_content = "A" * 1000  # 1000 characters
        self.tool_output = "START" + "M" * 800 + "END" # 810 chars
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
            tool_call_id = "call_12345" # Dummy ID for tool messages

        msg = MessageChunk(
            role=role, content=content, type=self._message_type_for_role(role), tool_call_id=tool_call_id
        )
        if timestamp:
            msg.timestamp = timestamp
        return msg

    def print_messages(self, title, messages):
        print(f"\n{'='*20} {title} {'='*20}")
        print(f"Total Count: {len(messages)}")
        for i, msg in enumerate(messages):
            content_display = msg.content
            if content_display and len(content_display) > 100:
                content_display = content_display[:50] + "..." + content_display[-50:]
            print(f"[{i}] Role: {msg.role:<10} | Len: {len(msg.content) if msg.content else 0:<5} | Content: {content_display}")
        print("="*60)

    def test_level_1_compression(self):
        """测试 Level 1: Tool 截断和 Thinking 移除"""
        messages = [
            self.create_message(MessageRole.SYSTEM.value, "System Prompt"),
            self.create_message(MessageRole.USER.value, "User Request"),
            self.create_message(MessageRole.TOOL.value, self.tool_output),
            self.create_message(MessageRole.ASSISTANT.value, self.thinking_content),
            self.create_message(MessageRole.USER.value, "Next User Request") # Ensure Assistant is not the last message (which is protected)
        ]
        
        # 预算设为足够小以触发 Level 1，但不足以触发 Level 2
        # 原始 Token 约: Sys(2) + User(2) + Tool(800) + Asst(20) ~ 850
        # 设限制 200，迫使 Tool 截断 (变成200) 和 Thinking 移除
        budget = 200 
        
        compressed = self.manager.compress_messages(messages, budget_limit=budget)
        self.print_messages("Level 1 Compression Result", compressed)
        
        # 验证 Tool 截断
        self.assertIn("...[Tool output truncated", compressed[2].content)
        self.assertTrue(len(compressed[2].content) < 300) # 100+100+提示语
        
        # 验证 Thinking 移除
        self.assertNotIn("<thinking>", compressed[3].content)
        self.assertIn("The answer is 42", compressed[3].content)

    def test_level_2_aging(self):
        """测试 Level 0.5: 老化消息直接 Level 2"""
        old_time = time.time() - 25 * 3600 # 25 hours ago
        messages = [
            self.create_message(MessageRole.SYSTEM.value, "System Prompt"),
            self.create_message(MessageRole.USER.value, "Old User"),
            self.create_message(MessageRole.ASSISTANT.value, "Old Assistant Long Content " * 20, timestamp=old_time), # Should be heavily compressed
            self.create_message(MessageRole.USER.value, "New User"),
        ]
        
        # 预算很大，理论上不需要压缩，但因为老化策略，中间的 Assistant 应该被压缩
        budget = 100 
        
        compressed = self.manager.compress_messages(messages, budget_limit=budget)
        self.print_messages("Aging Strategy Result", compressed)
        
        # 验证老化压缩
        self.assertIn("...[Content truncated]", compressed[2].content)
        self.assertTrue(len(compressed[2].content) <= 200)

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
        
        compressed = self.manager.compress_messages(messages, budget_limit=budget)
        self.print_messages("Level 3 Drop Result", compressed)
        
        # System 应该在
        self.assertEqual(compressed[0].role, MessageRole.SYSTEM.value)
        
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
            self.create_message(MessageRole.ASSISTANT.value, "Asst 1 " * 50), # Compressible
            self.create_message(MessageRole.USER.value, "User 2 (Recent)"),
            self.create_message(MessageRole.TOOL.value, "Tool 2 (Recent but long) " * 20), # Should be protected if within 20%
        ]
        
        # 预算：假设总预算 2000。20% = 400。
        # User 2 + Tool 2 约 300 token < 400，应受保护。
        # Asst 1 应被压缩。
        budget = 2000
        
        # Mock calculation to ensure our test logic holds
        # 实际运行依赖 calculate_str_token_length
        
        compressed = self.manager.compress_messages(messages, budget_limit=1000) # Give tight budget to force compression on unprotected
        self.print_messages("Recent Protection Result", compressed)
        
        # Check Tool 2 is NOT compressed (Level 1 would truncate to 200 chars + omitted)
        tool_msg = compressed[-1]
        self.assertNotIn("truncated", tool_msg.content)
        self.assertNotIn("omitted", tool_msg.content)

    def test_recent_messages_count_protection(self):
        """测试 recent_messages_count 按条数强制保护末尾 N 条消息"""
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

        # 不保护（recent_messages_count=0）：最近的大 tool output 会被压缩
        compressed_no_protect = self.manager.compress_messages(messages, budget_limit=tiny_budget, recent_messages_count=0)
        self.print_messages("No recent protection", compressed_no_protect)
        # tool output 应该被截断
        self.assertIn("omitted", compressed_no_protect[-1].content)

        # 保护末尾 2 条（recent_messages_count=2）：User 2 和 Tool 不被压缩
        compressed_with_protect = self.manager.compress_messages(messages, budget_limit=tiny_budget, recent_messages_count=2)
        self.print_messages("With recent_messages_count=2", compressed_with_protect)

        # 验证最近的 tool output 不被截断
        last_tool_msg = compressed_with_protect[-1]
        self.assertNotIn("omitted", last_tool_msg.content)
        self.assertNotIn("truncated", last_tool_msg.content)
        self.assertEqual(last_tool_msg.content, very_long_tool_output)

        # 验证 User 2（倒数第 2 条）也被保护
        user2_msg = compressed_with_protect[-2]
        self.assertEqual(user2_msg.content, "User 2 (Recent)")

if __name__ == '__main__':
    unittest.main()
