from sagents.context.messages.message_manager import MessageManager
from .agent_base import AgentBase
from typing import Any, Dict, List, AsyncGenerator, Optional
from sagents.utils.logger import logger
from sagents.context.messages.message import MessageChunk, MessageRole, MessageType
from sagents.context.session_context import SessionContext
from sagents.tool.tool_manager import ToolManager

from sagents.utils.prompt_manager import PromptManager
import uuid


class TaskSummaryAgent(AgentBase):
    def __init__(self, model: Any, model_config: Dict[str, Any], system_prefix: str = ""):
        super().__init__(model, model_config, system_prefix)
        self.agent_name = "TaskSummaryAgent"
        self.agent_description = "任务总结智能体，专门负责生成任务执行的总结报告"
        logger.debug("TaskSummaryAgent 初始化完成")

    async def run_stream(self, session_context: SessionContext, tool_manager: Optional[ToolManager] = None, session_id: Optional[str] = None) -> AsyncGenerator[List[MessageChunk], None]:
        message_manager = session_context.message_manager
        task_manager = session_context.task_manager

        # 提取任务描述
        if 'task_rewrite' in session_context.audit_status:
            task_description_messages_str = MessageManager.convert_messages_to_str([MessageChunk(
                role=MessageRole.USER.value,
                content=session_context.audit_status['task_rewrite'],
                message_type=MessageType.NORMAL.value
            )])
        else:
            history_messages = message_manager.extract_all_context_messages(recent_turns=3)
            task_description_messages_str = MessageManager.convert_messages_to_str(history_messages)

        task_manager_status_and_results = await task_manager.get_all_tasks_summary()

        completed_actions_messages = message_manager.get_all_execution_messages_after_last_user(max_content_length=(self.max_model_input_len-MessageManager.calculate_str_token_length(task_description_messages_str)-MessageManager.calculate_str_token_length(task_manager_status_and_results)))
        completed_actions_messages.append(message_manager.get_last_observation_message())
        completed_actions_messages_str = MessageManager.convert_messages_to_str(completed_actions_messages)

        # 使用PromptManager获取模板，传入语言参数
        summary_template = PromptManager().get_agent_prompt_auto("task_summary_template", language=session_context.get_language())
        prompt = summary_template.format(
            task_description=task_description_messages_str,
            task_manager_status_and_results=task_manager_status_and_results,
            execution_results=completed_actions_messages_str,
        )
        llm_request_message = [
            self.prepare_unified_system_message(session_id=session_id, language=session_context.get_language()),
            MessageChunk(
                role=MessageRole.USER.value,
                content=prompt,
                message_id=str(uuid.uuid4()),
                show_content=prompt,
                message_type=MessageType.FINAL_ANSWER.value
            )
        ]

        message_id = str(uuid.uuid4())
        async for llm_repsonse_chunk in self._call_llm_streaming(messages=llm_request_message,
                                                                 session_id=session_id,
                                                                 step_name="final_answer"):
            if len(llm_repsonse_chunk.choices) == 0:
                continue
            if llm_repsonse_chunk.choices[0].delta.content:
                yield [MessageChunk(
                    role=MessageRole.ASSISTANT.value,
                    content=llm_repsonse_chunk.choices[0].delta.content,
                    message_id=message_id,
                    show_content=llm_repsonse_chunk.choices[0].delta.content,
                    message_type=MessageType.FINAL_ANSWER.value
                )]
