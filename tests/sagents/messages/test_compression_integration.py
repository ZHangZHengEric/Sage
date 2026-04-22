
import unittest
from unittest.mock import MagicMock, patch, AsyncMock
import os

from sagents.agent.task_decompose_agent import TaskDecomposeAgent
from sagents.agent.task_router_agent import TaskRouterAgent
from sagents.agent.common_agent import CommonAgent
from sagents.context.messages.message import MessageChunk
from sagents.context.messages.message_manager import MessageManager
from sagents.context.session_context import SessionContext

class TestCompressionIntegration(unittest.TestCase):
    def setUp(self):
        self.mock_model = MagicMock()
        self.mock_config = {}
        self.mock_session_context = MagicMock(spec=SessionContext)
        self.mock_message_manager = MagicMock(spec=MessageManager)
        self.mock_session_context.message_manager = self.mock_message_manager
        
        # Mock ToolManager
        self.mock_tool_manager = MagicMock()
        self.mock_tool_manager.get_openai_tools.return_value = {}
        self.mock_session_context.tool_manager = self.mock_tool_manager

        self.mock_session_context.get_language.return_value = 'zh'
        self.mock_session_context.audit_status = {}
        self.mock_session_context.task_manager = MagicMock()
        # 无全局 session 时避免 should_abort 提前返回；TaskRouter 需完整 agent_config
        self.mock_session_context.session_id = None
        self.mock_session_context.agent_config = {
            "agent_mode": "auto",
            "deep_thinking": False,
        }
        
        # Setup budget info
        self.mock_budget_manager = MagicMock()
        self.mock_budget_manager.budget_info = {'active_budget': 5000}
        self.mock_message_manager.context_budget_manager = self.mock_budget_manager
        
        # Setup extract_all_context_messages return value
        self.mock_messages = [MagicMock(), MagicMock(), MagicMock()]
        self.mock_message_manager.extract_all_context_messages.return_value = self.mock_messages
        
        # Mock compress_messages
        self.mock_compressed_messages = [MagicMock()]
        # We need to patch MessageManager.compress_messages because it's a static method called on the class
        self.compress_patcher = patch('sagents.context.messages.message_manager.MessageManager.compress_messages')
        self.mock_compress = self.compress_patcher.start()
        self.mock_compress.return_value = self.mock_compressed_messages
        
        # Mock convert methods to avoid errors
        self.convert_str_patcher = patch('sagents.context.messages.message_manager.MessageManager.convert_messages_to_str')
        self.mock_convert_str = self.convert_str_patcher.start()
        
        self.convert_dict_patcher = patch('sagents.context.messages.message_manager.MessageManager.convert_messages_to_dict_for_request')
        self.mock_convert_dict = self.convert_dict_patcher.start()

    def tearDown(self):
        self.compress_patcher.stop()
        self.convert_str_patcher.stop()
        self.convert_dict_patcher.stop()

    def test_task_decompose_agent_compression(self):
        agent = TaskDecomposeAgent(self.mock_model, self.mock_config)
        agent._should_abort_due_to_session = MagicMock(return_value=False)
        # Mock _call_llm_streaming to return empty async iterator
        async def mock_call_llm(*args, **kwargs):
            yield MagicMock(choices=[])
        agent._call_llm_streaming = mock_call_llm
        agent.prepare_unified_system_message = AsyncMock(
            return_value=MessageChunk(role="system", content="sys")
        )
        
        import asyncio
        async def run_test():
            async for _ in agent.run_stream(self.mock_session_context):
                pass
        asyncio.run(run_test())
        
        # Verify extract called
        self.mock_message_manager.extract_all_context_messages.assert_called()
        # Verify compress called with correct budget
        self.mock_compress.assert_called_with(self.mock_messages, 4000)

    def test_task_router_agent_compression(self):
        agent = TaskRouterAgent(self.mock_model, self.mock_config)
        agent._should_abort_due_to_session = MagicMock(return_value=False)
        async def mock_call_llm(*args, **kwargs):
            yield MagicMock(choices=[])
        agent._call_llm_streaming = mock_call_llm
        agent.prepare_unified_system_message = AsyncMock(
            return_value=MessageChunk(role="system", content="sys")
        )
        
        import asyncio
        async def run_test():
            async for _ in agent.run_stream(self.mock_session_context):
                pass
        asyncio.run(run_test())
        
        self.mock_compress.assert_called_with(self.mock_messages, 2000)

    def test_common_agent_does_not_compress_in_run_stream(self):
        """CommonAgent.run_stream 仅拉取历史，不调用 MessageManager.compress_messages。"""
        agent = CommonAgent(self.mock_model, self.mock_config)

        async def mock_call_llm(*args, **kwargs):
            yield MagicMock(choices=[])
        agent._call_llm_streaming = mock_call_llm

        agent._prepare_tools = MagicMock(return_value=[])
        agent.prepare_unified_system_message = AsyncMock(
            return_value=MessageChunk(role="system", content="sys")
        )
        agent._should_abort_due_to_session = MagicMock(return_value=False)

        import asyncio
        async def run_test():
            async for _ in agent.run_stream(self.mock_session_context):
                pass
        asyncio.run(run_test())

        self.mock_compress.assert_not_called()
        self.mock_message_manager.extract_all_context_messages.assert_called()

    def test_no_compression_when_no_budget_info(self):
        # Remove budget info
        self.mock_budget_manager.budget_info = None
        
        agent = TaskDecomposeAgent(self.mock_model, self.mock_config)
        agent._should_abort_due_to_session = MagicMock(return_value=False)
        async def mock_call_llm(*args, **kwargs):
            yield MagicMock(choices=[])
        agent._call_llm_streaming = mock_call_llm
        agent.prepare_unified_system_message = AsyncMock(
            return_value=MessageChunk(role="system", content="sys")
        )
        
        import asyncio
        async def run_test():
            async for _ in agent.run_stream(self.mock_session_context):
                pass
        asyncio.run(run_test())
        
        # Verify compress NOT called
        self.mock_compress.assert_not_called()

if __name__ == '__main__':
    unittest.main()
