import traceback
from sagents.utils.prompt_manager import PromptManager
from sagents.context.messages.message_manager import MessageManager
from .agent_base import AgentBase
from typing import Any, Dict, List, Optional, Generator
from sagents.utils.logger import logger
from sagents.context.messages.message import MessageChunk, MessageRole,MessageType
from sagents.context.session_context import SessionContext
from sagents.tool.tool_manager import ToolManager
from sagents.tool.tool_base import AgentToolSpec
import json
import uuid
from copy import deepcopy

class TaskAnalysisAgent(AgentBase):
    def __init__(self, model: Any, model_config: Dict[str, Any], system_prefix: str = ""):
        super().__init__(model, model_config, system_prefix)
        self.SYSTEM_PREFIX_FIXED = PromptManager().task_analysis_system_prefix
        self.agent_name = "TaskAnalysisAgent"
        self.agent_description = "任务分析智能体，专门负责分析任务并将其分解为组件"
        logger.info("TaskAnalysisAgent 初始化完成")

    def run_stream(self, session_context: SessionContext, tool_manager: Optional[ToolManager] = None, session_id: str = None) -> Generator[List[MessageChunk], None, None]:
        # 从会话管理中，获取消息管理实例
        message_manager = session_context.message_manager
        # 从消息管理实例中，获取满足context 长度限制的消息
        logger.info("TaskAnalysisAgent: 开始执行流式任务分析")
        # recent_message 中只保留 user 以及final answer
        if 'task_rewrite' in session_context.audit_status:
            recent_message_str = MessageManager.convert_messages_to_str([MessageChunk(
                role=MessageRole.USER.value,
                content = session_context.audit_status['task_rewrite'],
                message_type=MessageType.NORMAL.value
            )])
        else:
            recent_message = message_manager.extract_all_context_messages(recent_turns=3,max_length=self.max_history_context_length)
            recent_message_str = MessageManager.convert_messages_to_str(recent_message)
        
        available_tools_name = tool_manager.list_all_tools_name() if tool_manager else []
        available_tools_str = ", ".join(available_tools_name) if available_tools_name else "无可用工具"
        logger.debug(f"TaskAnalysisAgent: 可用工具数量: {len(available_tools_name)}")

        
        prompt = PromptManager().get('analysis_template').format(
            conversation=recent_message_str,
            available_tools=available_tools_str,
        )

        # 为整个分析流程生成统一的message_id
        message_id = str(uuid.uuid4())
        yield [MessageChunk(
            role=MessageRole.ASSISTANT.value,
            content="任务分析：",
            message_id=message_id,
            show_content="",
            message_type=MessageType.TASK_ANALYSIS.value
        )]

        llm_request_message = [
            self.prepare_unified_system_message(session_id=session_id),
            MessageChunk(
                role=MessageRole.USER.value,
                content=prompt,
                message_id=str(uuid.uuid4()),
                show_content=prompt,
                message_type=MessageType.TASK_ANALYSIS.value
            )
        ]
        all_analysis_chunks_content=  ''
        for llm_repsonse_chunk in self._call_llm_streaming(
            messages=llm_request_message,
            session_id=session_id,
            step_name="task_analysis",
        ):
            if len(llm_repsonse_chunk.choices) == 0:
                continue
            if llm_repsonse_chunk.choices[0].delta.content:
                if len(llm_repsonse_chunk.choices[0].delta.content) > 0:
                    all_analysis_chunks_content += llm_repsonse_chunk.choices[0].delta.content
                    yield [MessageChunk(
                        role=MessageRole.ASSISTANT.value,
                        content=llm_repsonse_chunk.choices[0].delta.content,
                        message_id=message_id,
                        show_content=llm_repsonse_chunk.choices[0].delta.content,
                        message_type=MessageType.TASK_ANALYSIS.value
                    )]
            elif hasattr(llm_repsonse_chunk.choices[0].delta, 'reasoning_content') and llm_repsonse_chunk.choices[0].delta.reasoning_content is not None:
                yield [MessageChunk(
                        role=MessageRole.ASSISTANT.value,
                        content="",
                        message_id=message_id,
                        show_content="",
                        message_type=MessageType.TASK_ANALYSIS.value
                    )]
        session_context.audit_status['task_analysis'] = all_analysis_chunks_content