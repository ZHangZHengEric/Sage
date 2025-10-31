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
from sagents.context.tasks.task_manager import TaskManager
from sagents.context.tasks.task_base import TaskBase, TaskStatus
import json
import uuid
from copy import deepcopy

class TaskCompletionJudgeAgent(AgentBase):
    def __init__(self, model: Any, model_config: Dict[str, Any], system_prefix: str = "", max_model_len: int = 64000):
        super().__init__(model, model_config, system_prefix, max_model_len)
        self.SYSTEM_PREFIX_FIXED = PromptManager().get_agent_prompt_auto('task_completion_judge_system_prefix')
        self.agent_name = "CompletionJudgeAgent"
        self.agent_description = "完成判断智能体，专门负责判断任务是否完成"
        logger.info("TaskCompletionJudgeAgent 初始化完成")

    async def run_stream(self, session_context: SessionContext, tool_manager: ToolManager = None, session_id: str = None) -> Generator[List[MessageChunk], None, None]:
        # 重新获取系统前缀，使用正确的语言
        self.SYSTEM_PREFIX_FIXED = PromptManager().get_agent_prompt_auto('task_completion_judge_system_prefix', language=session_context.get_language())
        
        message_manager = session_context.message_manager
        task_manager = session_context.task_manager

        if 'task_rewrite' in session_context.audit_status:
            task_description_messages_str = MessageManager.convert_messages_to_str([MessageChunk(
                role=MessageRole.USER.value,
                content = session_context.audit_status['task_rewrite'],
                message_type=MessageType.NORMAL.value
            )])
        else:
            history_messages = message_manager.extract_all_context_messages(recent_turns=3,max_length=self.max_history_context_length)
            task_description_messages_str = MessageManager.convert_messages_to_str(history_messages)

        task_manager_status = task_manager.get_status_description() if task_manager else '无任务管理器'

        # recent_execution_results_messages = message_manager.extract_after_last_observation_messages()
        # recent_execution_results_messages_str = MessageManager.convert_messages_to_str(recent_execution_results_messages)
        completed_actions_messages = message_manager.extract_after_last_stage_summary_messages(max_length=(self.max_model_input_len-MessageManager.calculate_str_token_length(task_description_messages_str) - MessageManager.calculate_str_token_length(task_manager_status))//2)
        completed_actions_messages_str = MessageManager.convert_messages_to_str(completed_actions_messages)

        prompt = PromptManager().get_agent_prompt_auto('task_completion_judge_template', language=session_context.get_language()).format(
            task_description=task_description_messages_str,
            task_manager_status=task_manager_status,
            execution_results=completed_actions_messages_str,
            agent_description=self.system_prefix
        )
        llm_request_message = [
            self.prepare_unified_system_message(session_id=session_id),
            MessageChunk(
                role=MessageRole.USER.value,
                content=prompt,
                message_id=str(uuid.uuid4()),
                show_content=prompt,
                message_type=MessageType.OBSERVATION.value
            )
        ]
        message_id = str(uuid.uuid4())
        all_content = ''
        for llm_repsonse_chunk in self._call_llm_streaming(messages=llm_request_message,
                                             session_id=session_id,
                                             step_name="task_completion_judge"):
            if len(llm_repsonse_chunk.choices) == 0:
                continue
            if llm_repsonse_chunk.choices[0].delta.content:
                delta_content = llm_repsonse_chunk.choices[0].delta.content
                all_content += delta_content
        for result in self._finalize_task_completion_judge_result(
            session_context=session_context,
            all_content=all_content, 
            message_id=message_id,
            task_manager = task_manager
        ):
            yield result
        
    def _finalize_task_completion_judge_result(self,session_context:SessionContext,all_content:str,message_id:str,task_manager:TaskManager):
        """
        最终化任务完成判断结果
        """
        try:
            response_json = json.loads(MessageChunk.extract_json_from_markdown(all_content))
            logger.info(f"TaskCompletionJudgeAgent: 任务完成判断结果: {response_json}")
            session_context.audit_status["completion_status"] = response_json["completion_status"]
            session_context.audit_status["finish_percent"] = response_json["finish_percent"]
            yield []
            
        except Exception as e:
            logger.error(f"TaskCompletionJudgeAgent: 解析任务完成判断结果时发生错误: {str(e)}")
            logger.error(f"TaskCompletionJudgeAgent: 原始XML内容: {all_content}")
            yield [MessageChunk(
                role=MessageRole.ASSISTANT.value,
                content=f"任务完成判断失败: {str(e)}",
                message_id=str(uuid.uuid4()),
                show_content=f"任务完成判断失败: {str(e)}",
                message_type=MessageType.OBSERVATION.value
            )]
    def convert_xlm_to_json(self, xlm_content: str) -> Dict[str, Any]:
        
        logger.debug("TaskCompletionJudgeAgent: 转换XML内容为JSON格式")
        try:
            # 提取analysis
            analysis = xlm_content.split('<completion_status>')[1].split('</completion_status>')[0].strip()
            finish_percent = xlm_content.split('<finish_percent>')[1].split('</finish_percent>')[0].strip()
            
            # 构建响应JSON - 只保留简化后的字段
            response_json = {
                "completion_status": analysis,
                "finish_percent": finish_percent    
            }            
            logger.debug(f"ObservationAgent: XML转JSON完成: {response_json}")
            return response_json
            
        except Exception as e:
            logger.error(f"ObservationAgent: XML转JSON失败: {str(e)}")
            raise