from sagents.utils.prompt_manager import PromptManager
from sagents.context.messages.message_manager import MessageManager
from .agent_base import AgentBase
from typing import Any, Dict, List, AsyncGenerator, Optional
from sagents.utils.logger import logger
from sagents.context.messages.message import MessageChunk, MessageRole,MessageType
from sagents.context.session_context import SessionContext
from sagents.tool.tool_manager import ToolManager
from sagents.context.tasks.task_manager import TaskManager
from sagents.context.tasks.task_base import TaskStatus
import json
import uuid

class TaskObservationAgent(AgentBase):
    def __init__(self, model: Any, model_config: Dict[str, Any], system_prefix: str = ""):
        super().__init__(model, model_config, system_prefix)
        self.agent_name = "ObservationAgent"
        self.agent_description = "观测智能体，专门负责基于当前状态生成下一步执行计划"
        logger.debug("TaskObservationAgent 初始化完成")

    async def run_stream(self, session_context: SessionContext, tool_manager: Optional[ToolManager] = None, session_id: Optional[str] = None) -> AsyncGenerator[List[MessageChunk], None]:
        # 重新获取系统前缀，使用正确的语言
        current_system_prefix = PromptManager().get_agent_prompt_auto('task_observation_system_prefix', language=session_context.get_language())

        message_manager = session_context.message_manager
        task_manager = session_context.task_manager

        if 'task_rewrite' in session_context.audit_status:
            task_description_messages_str = MessageManager.convert_messages_to_str([MessageChunk(
                role=MessageRole.USER.value,
                content = session_context.audit_status['task_rewrite'],
                message_type=MessageType.NORMAL.value
            )])
        else:
            history_messages = message_manager.extract_all_context_messages(recent_turns=3)
            # 根据 active_budget 压缩消息
            budget_info = message_manager.context_budget_manager.budget_info
            if budget_info:
                history_messages = MessageManager.compress_messages(history_messages, budget_info.get('active_budget', 8000))
            task_description_messages_str = MessageManager.convert_messages_to_str(history_messages)

        if task_manager:
            task_manager_status = task_manager.get_status_description(language=session_context.get_language())
        else:
            task_manager_status = PromptManager().get_prompt(
                'task_manager_none',
                agent='common',
                language=session_context.get_language(),
                default='无任务管理器'
            )

        recent_execution_results_messages = message_manager.extract_after_last_observation_messages()
        recent_execution_results_messages_str = MessageManager.convert_messages_to_str(recent_execution_results_messages)

        prompt = PromptManager().get_agent_prompt_auto('observation_template', language=session_context.get_language()).format(
            task_description=task_description_messages_str,
            task_manager_status=task_manager_status,
            execution_results=recent_execution_results_messages_str,
            agent_description=self.system_prefix
        )
        llm_request_message = [
            self.prepare_unified_system_message(session_id=session_id, language=session_context.get_language(), system_prefix_override=current_system_prefix),
            MessageChunk(
                role=MessageRole.USER.value,
                content=prompt,
                message_id=str(uuid.uuid4()),
                show_content=prompt,
                message_type=MessageType.OBSERVATION.value
            )
        ]
        message_id = str(uuid.uuid4())
        unknown_content = ''
        all_content = ''
        last_tag_type = None
        async for llm_repsonse_chunk in self._call_llm_streaming(messages=llm_request_message,
                                                                 session_id=session_id,
                                                                 step_name="observation"):
            if len(llm_repsonse_chunk.choices) == 0:
                continue
            if llm_repsonse_chunk.choices[0].delta.content:
                delta_content = llm_repsonse_chunk.choices[0].delta.content
                for delta_content_char in delta_content:
                    delta_content_all = unknown_content + delta_content_char
                    # 判断delta_content的类型
                    tag_type = self._judge_delta_content_type(delta_content_all, all_content, tag_type=['analysis','completed_task_ids','pending_task_ids','failed_task_ids'])
                    all_content += delta_content_char

                    if tag_type == 'unknown':
                        unknown_content = delta_content_all
                        continue
                    else:
                        unknown_content = ''
                        if tag_type in ['analysis']:
                            if tag_type != last_tag_type:
                                yield [MessageChunk(
                                    role=MessageRole.ASSISTANT.value,
                                    content='',
                                    message_id=message_id,
                                    show_content='\n\n',
                                    message_type=MessageType.OBSERVATION.value
                                )]

                            yield [MessageChunk(
                                role=MessageRole.ASSISTANT.value,
                                content='',
                                message_id=message_id,
                                show_content=delta_content_all,
                                message_type=MessageType.OBSERVATION.value
                            )]
                        last_tag_type = tag_type
        async for chunk in self._finalize_observation_result(
            session_context=session_context,
            all_content=all_content, 
            message_id=message_id,
            task_manager = task_manager
        ):
            yield chunk
    async def _finalize_observation_result(self,session_context:SessionContext,all_content:str,message_id:str,task_manager:TaskManager):
        """
        最终化观测结果
        """
        try:
            response_json = self.convert_xlm_to_json(all_content)
            logger.info(f"ObservationAgent: 观察分析结果: {response_json}")
            if "all_observations" not in session_context.audit_status:
                session_context.audit_status["all_observations"] = []
            session_context.audit_status["all_observations"].append(response_json)

            # 更新TaskManager中的任务状态
            if task_manager:
                self._update_task_manager_status(task_manager, response_json)

            # 创建最终结果消息（不需要usage信息，因为这是转换过程）
            result_message = MessageChunk(
                role=MessageRole.ASSISTANT.value,
                content=PromptManager().get_agent_prompt_auto('execution_evaluation_prompt', language=session_context.get_language()) + json.dumps(response_json, ensure_ascii=False),
                message_id=message_id,
                show_content='\n',
                message_type=MessageType.OBSERVATION.value
            )

            yield [result_message]

        except Exception as e:
            logger.error(f"ObservationAgent: 解析观察结果时发生错误: {str(e)}")
            logger.error(f"ObservationAgent: 原始XML内容: {all_content}")
            yield [MessageChunk(
                role=MessageRole.ASSISTANT.value,
                content=f"任务观测失败: {str(e)}",
                message_id=str(uuid.uuid4()),
                show_content=f"任务观测失败: {str(e)}",
                message_type=MessageType.OBSERVATION.value
            )]
    def convert_xlm_to_json(self, xlm_content: str) -> Dict[str, Any]:

        logger.debug("ObservationAgent: 转换XML内容为JSON格式")
        try:
            # 提取analysis
            analysis = xlm_content.split('<analysis>')[1].split('</analysis>')[0].strip()

            # 提取completed_task_ids
            completed_task_ids: List[str] = []
            if '<completed_task_ids>' in xlm_content and '</completed_task_ids>' in xlm_content:
                completed_task_ids_str = xlm_content.split('<completed_task_ids>')[1].split('</completed_task_ids>')[0].strip()
                try:
                    completed_task_ids = json.loads(completed_task_ids_str) if completed_task_ids_str else []
                except Exception:
                    completed_task_ids = []

            # 提取pending_task_ids
            pending_task_ids: List[str] = []
            if '<pending_task_ids>' in xlm_content and '</pending_task_ids>' in xlm_content:
                pending_task_ids_str = xlm_content.split('<pending_task_ids>')[1].split('</pending_task_ids>')[0].strip()
                try:
                    pending_task_ids = json.loads(pending_task_ids_str) if pending_task_ids_str else []
                except Exception:
                    pending_task_ids = []

            # 提取failed_task_ids
            failed_task_ids: List[str] = []
            if '<failed_task_ids>' in xlm_content and '</failed_task_ids>' in xlm_content:
                failed_task_ids_str = xlm_content.split('<failed_task_ids>')[1].split('</failed_task_ids>')[0].strip()
                try:
                    failed_task_ids = json.loads(failed_task_ids_str) if failed_task_ids_str else []
                except Exception:
                    failed_task_ids = []

            # 构建响应JSON - 只保留简化后的字段
            response_json = {
                "analysis": analysis,
                "completed_task_ids": completed_task_ids,
                "pending_task_ids": pending_task_ids,
                "failed_task_ids": failed_task_ids
            }

            logger.debug(f"ObservationAgent: XML转JSON完成: {response_json}")
            return response_json

        except Exception as e:
            logger.error(f"ObservationAgent: XML转JSON失败: {str(e)}")
            raise

    def _update_task_manager_status(self, task_manager: TaskManager, observation_result: Dict[str, Any]) -> None:
        try:
            # 获取任务状态信息
            completed_task_ids = observation_result['completed_task_ids'] if 'completed_task_ids' in observation_result else []
            failed_task_ids = observation_result['failed_task_ids'] if 'failed_task_ids' in observation_result else []
            logger.info(f"ObservationAgent: 观察分析结果中完成任务: {completed_task_ids}，失败任务: {failed_task_ids}")
            # 更新已完成的任务状态
            for task_id in completed_task_ids:
                try:
                    if hasattr(task_manager, 'update_task_status'):
                        task_manager.update_task_status(task_id, TaskStatus.COMPLETED)
                        logger.info(f"ObservationAgent: 已将任务 {task_id} 标记为完成")

                        # 尝试更新任务的执行结果
                        task = task_manager.get_task(task_id)
                        if task and hasattr(task_manager, 'complete_task'):
                            # 使用观察结果的分析作为任务结果
                            analysis = observation_result['analysis'] if 'analysis' in observation_result else ''
                            if analysis:
                                task_manager.complete_task(
                                    task_id=task_id,
                                    result=analysis,
                                    execution_details={
                                        'observation_analysis': analysis,
                                        'completion_detected_by': 'ObservationAgent'
                                    }
                                )
                                logger.info(f"ObservationAgent: 已更新任务 {task_id} 的执行结果")
                    else:
                        logger.warning("ObservationAgent: TaskManager没有update_task_status方法")
                except Exception as e:
                    logger.warning(f"ObservationAgent: 更新任务 {task_id} 状态为完成时出错: {str(e)}")

            # 更新失败的任务状态
            for task_id in failed_task_ids:
                try:
                    if hasattr(task_manager, 'update_task_status'):
                        task_manager.update_task_status(task_id, TaskStatus.FAILED)
                        logger.info(f"ObservationAgent: 已将任务 {task_id} 标记为失败")
                    else:
                        logger.warning("ObservationAgent: TaskManager没有update_task_status方法")
                except Exception as e:
                    logger.warning(f"ObservationAgent: 更新任务 {task_id} 状态为失败时出错: {str(e)}")

            logger.info(f"ObservationAgent: 任务状态更新完成，完成任务: {completed_task_ids}，失败任务: {failed_task_ids}")
        except Exception as e:
            logger.error(f"ObservationAgent: 更新TaskManager任务状态时发生错误: {str(e)}")
