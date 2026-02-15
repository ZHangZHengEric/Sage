from sagents.utils.prompt_manager import PromptManager
from sagents.context.messages.message_manager import MessageManager
from .agent_base import AgentBase
from typing import Any, Dict, List, Optional, AsyncGenerator
from sagents.utils.logger import logger
from sagents.context.messages.message import MessageChunk, MessageRole,MessageType
from sagents.context.session_context import SessionContext
from sagents.tool.tool_manager import ToolManager
import uuid

class TaskAnalysisAgent(AgentBase):
    def __init__(self, model: Any, model_config: Dict[str, Any], system_prefix: str = ""):
        super().__init__(model, model_config, system_prefix)
        self.agent_name = "TaskAnalysisAgent"
        self.agent_description = "任务分析智能体，专门负责分析任务并将其分解为组件"
        logger.debug("TaskAnalysisAgent 初始化完成")

    async def run_stream(self, session_context: SessionContext, tool_manager: Optional[ToolManager] = None, session_id: Optional[str] = None) -> AsyncGenerator[List[MessageChunk], None]:
        # 重新获取系统前缀，使用正确的语言，不能用init的，会有并发问题
        current_system_prefix = PromptManager().get_agent_prompt_auto('task_analysis_system_prefix', language=session_context.get_language())

        # 从会话管理中，获取消息管理实例
        message_manager = session_context.message_manager
        # 从消息管理实例中，获取满足context 长度限制的消息
        logger.info("TaskAnalysisAgent: 开始执行流式任务分析")
        # recent_message 中只保留 user 以及final answer

        recent_message = message_manager.extract_all_context_messages(
            recent_turns=5,
            allowed_message_types=[
                MessageType.FINAL_ANSWER.value,
                MessageType.DO_SUBTASK_RESULT.value,
                MessageType.TOOL_CALL.value,
                MessageType.TOOL_CALL_RESULT.value
            ]
        )
        # 根据 active_budget 压缩消息
        budget_info = message_manager.context_budget_manager.budget_info
        if budget_info:
            recent_message = MessageManager.compress_messages(recent_message, min(budget_info.get('active_budget', 8000), 4000))
        recent_message_str = MessageManager.convert_messages_to_str(recent_message)

        available_tools_name = tool_manager.list_all_tools_name() if tool_manager else []

        # 获取skills metadata
        skill_manager = session_context.skill_manager
        if skill_manager and skill_manager.list_skills():
            available_skills_name = skill_manager.get_skill_description_lines()
        else:
            available_skills_name = []

        available_tools_str = ", ".join(available_tools_name) if available_tools_name else "无可用工具"
        available_skills_str = ", ".join(available_skills_name) if available_skills_name else "无可用技能"
        logger.debug(f"TaskAnalysisAgent: 可用工具数量: {len(available_tools_name)}, 可用技能数量: {len(available_skills_name)}")

        prompt = PromptManager().get_agent_prompt_auto('analysis_template', language=session_context.get_language()).format(
            conversation=recent_message_str,
            available_tools=available_tools_str,
            available_skills=available_skills_str,
            agent_description = self.system_prefix
        )

        # 为整个分析流程生成统一的message_id
        message_id = str(uuid.uuid4())
        # 获取多语言支持的任务分析提示文本
        task_analysis_prompt = PromptManager().get_agent_prompt_auto('task_analysis_prompt', language=session_context.get_language())
        yield [MessageChunk(
            role=MessageRole.ASSISTANT.value,
            content=task_analysis_prompt,
            message_id=message_id,
            message_type=MessageType.TASK_ANALYSIS.value
        )]

        llm_request_message = [
            self.prepare_unified_system_message(
                session_id=session_id,
                language=session_context.get_language(),
                system_prefix_override=current_system_prefix,
                include_sections=['role_definition', 'system_context', 'workspace_files']
            ),
            MessageChunk(
                role=MessageRole.USER.value,
                content=prompt,
                message_id=str(uuid.uuid4()),
                message_type=MessageType.TASK_ANALYSIS.value
            )
        ]
        all_analysis_chunks_content=  ''
        async for llm_repsonse_chunk in self._call_llm_streaming(
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
                        message_type=MessageType.TASK_ANALYSIS.value
                    )]
            elif hasattr(llm_repsonse_chunk.choices[0].delta, 'reasoning_content') and llm_repsonse_chunk.choices[0].delta.reasoning_content is not None:
                yield [MessageChunk(
                        role=MessageRole.ASSISTANT.value,
                        content="",
                        message_id=message_id,
                        message_type=MessageType.TASK_ANALYSIS.value
                    )]
        session_context.audit_status['task_analysis'] = all_analysis_chunks_content
        logger.info(f"TaskAnalysisAgent: 任务分析完成，分析结果长度: {len(all_analysis_chunks_content)}")
