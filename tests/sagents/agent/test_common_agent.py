import pytest
import os
import asyncio
from unittest.mock import MagicMock, patch, AsyncMock

from sagents.agent.common_agent import CommonAgent
from sagents.context.session_context import SessionContext
from sagents.tool.tool_manager import ToolManager
from sagents.context.messages.message import MessageChunk, MessageRole, MessageType

class TestCommonAgent:
    @pytest.fixture
    def mock_session_context(self, mock_tool_manager):
        context = MagicMock(spec=SessionContext)
        context.message_manager = MagicMock()
        context.message_manager.extract_all_context_messages.return_value = []
        context.get_language.return_value = "en"
        context.session_id = "test_session"
        context.tool_manager = mock_tool_manager
        return context

    @pytest.fixture
    def mock_tool_manager(self):
        manager = MagicMock(spec=ToolManager)
        manager.get_openai_tools.return_value = {
            "test_tool": {"type": "function", "function": {"name": "test_tool"}}
        }
        manager.list_all_tools_name.return_value = ["test_tool"]
        return manager

    @pytest.fixture
    def common_agent(self):
        return CommonAgent(
            model=MagicMock(),
            model_config={},
            tools_name=["test_tool"]
        )

    def test_init(self, common_agent):
        assert common_agent.tools_name == ["test_tool"]

    @pytest.mark.asyncio
    async def test_run_stream_basic(self, common_agent, mock_session_context, mock_tool_manager):
        # Mock _call_llm_streaming to return a generator
        # We need to mock the method on the instance
        
        mock_chunk = MagicMock()
        mock_chunk.choices = [MagicMock()]
        mock_chunk.choices[0].delta.content = "Hello"
        mock_chunk.choices[0].delta.tool_calls = None
        
        # prepare_unified_system_message 为 async
        common_agent.prepare_unified_system_message = AsyncMock(
            return_value=MessageChunk(role="system", content="sys")
        )

        # Async generator mock
        async def async_gen(*args, **kwargs):
            yield mock_chunk

        with patch.object(common_agent, '_should_abort_due_to_session', return_value=False), \
             patch.object(common_agent, '_call_llm_streaming', side_effect=async_gen):
            generator = common_agent.run_stream(
                session_context=mock_session_context,
            )

            messages = []
            async for chunk in generator:
                messages.extend(chunk)
            
            assert len(messages) > 0
            # Depending on logic, we might get multiple chunks.
            # The logic yields chunks for content.
            found_content = False
            for msg in messages:
                if msg.content == "Hello":
                    found_content = True
                    break
            assert found_content

    def test_create_tool_call_message(self, common_agent):
        tool_call = {
            "id": "call_123",
            "type": "function",
            "function": {
                "name": "test_tool",
                "arguments": '{"arg": "value"}'
            }
        }
        
        messages = common_agent._create_tool_call_message(tool_call)
        assert len(messages) == 1
        assert messages[0].role == MessageRole.ASSISTANT.value
        assert messages[0].message_type == MessageType.TOOL_CALL.value
        # assert "test_tool" in messages[0].show_content
        # assert "arg = value" in messages[0].show_content

    def test_process_tool_response_json(self, common_agent):
        tool_call_id = "123"
        tool_response = '{"content": {"result": "success"}}'
        
        result = common_agent.process_tool_response(tool_response, tool_call_id)
        assert len(result) == 1
        assert result[0].role == MessageRole.TOOL.value
        assert result[0].tool_call_id == tool_call_id
        # assert "```json" in result[0].show_content

    def test_process_tool_response_text(self, common_agent):
        tool_call_id = "123"
        tool_response = "Just text response"
        
        result = common_agent.process_tool_response(tool_response, tool_call_id)
        assert len(result) == 1
        assert result[0].content == tool_response
        # assert result[0].show_content == '\n' + tool_response + '\n'

    def test_build_system_segments_includes_active_goal_context(self, common_agent):
        mock_context = MagicMock()
        mock_context.system_context = {
            "active_goal": {
                "objective": "Ship the runtime goal contract",
                "status": "active",
            },
            "goal_continuation_policy": {
                "mode": "continue_active_goal",
                "objective": "Ship the runtime goal contract",
                "status": "active",
                "instruction": "Continue pursuing the active goal across turns until it is completed, cleared, or replaced.",
            },
            "goal_resume_hint": "Continue the active goal after resume.",
        }
        mock_context.sandbox = None
        mock_context.effective_skill_manager = None

        with patch.object(common_agent, "_get_live_session_context", return_value=mock_context):
            segments = asyncio.run(
                common_agent._build_system_segments(
                    session_id="test_session",
                    language="en",
                    include_sections=["system_context"],
                )
            )

        assert "<active_goal>" in segments["volatile"]
        assert "Ship the runtime goal contract" in segments["volatile"]
        assert "Continue pursuing it across the current session" in segments["volatile"]
        assert "\"resume_hint\": \"Continue the active goal after resume.\"" in segments["volatile"]
        assert "<goal_continuation_policy>" in segments["volatile"]
        assert "Continue pursuing the active goal and make its status explicit as the session progresses." in segments["volatile"]

    def test_build_system_segments_includes_goal_transition_guidance(self, common_agent):
        mock_context = MagicMock()
        mock_context.system_context = {
            "goal_transition": {
                "type": "cleared",
                "previous_objective": "Ship the runtime goal contract",
                "previous_status": "active",
            }
        }
        mock_context.sandbox = None
        mock_context.effective_skill_manager = None

        with patch.object(common_agent, "_get_live_session_context", return_value=mock_context):
            segments = asyncio.run(
                common_agent._build_system_segments(
                    session_id="test_session",
                    language="en",
                    include_sections=["system_context"],
                )
            )

        assert "<goal_transition>" in segments["volatile"]
        assert "Ship the runtime goal contract" in segments["volatile"]
        assert "Do not implicitly continue the old goal unless the user reintroduces it." in segments["volatile"]

    def test_build_system_segments_includes_resume_goal_continuation_guidance(self, common_agent):
        mock_context = MagicMock()
        mock_context.system_context = {
            "active_goal": {
                "objective": "Ship the runtime goal contract",
                "status": "active",
                "resume_hint": "Continue the active goal after resume. Previous pause reason: blocked",
            },
            "goal_continuation_policy": {
                "mode": "resume_active_goal",
                "objective": "Ship the runtime goal contract",
                "status": "active",
                "resume_hint": "Continue the active goal after resume. Previous pause reason: blocked",
                "instruction": "Continue the active goal from prior progress after resume. Do not restart from scratch.",
            },
        }
        mock_context.sandbox = None
        mock_context.effective_skill_manager = None

        with patch.object(common_agent, "_get_live_session_context", return_value=mock_context):
            segments = asyncio.run(
                common_agent._build_system_segments(
                    session_id="test_session",
                    language="en",
                    include_sections=["system_context"],
                )
            )

        assert "<goal_continuation_policy>" in segments["volatile"]
        assert "\"mode\": \"resume_active_goal\"" in segments["volatile"]
        assert "Build on prior progress and continue forward without restarting the plan from scratch." in segments["volatile"]
