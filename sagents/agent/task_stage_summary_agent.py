import datetime
import json
import re
import traceback
import uuid
from typing import Any, Dict, Generator, List

from sagents.context.messages.message import MessageChunk, MessageRole, MessageType
from sagents.context.messages.message_manager import MessageManager
from sagents.context.session_context import SessionContext
from sagents.tool.tool_manager import ToolManager
from sagents.utils.logger import logger
from sagents.utils.prompt_manager import PromptManager

from .agent_base import AgentBase


class TaskStageSummaryAgent(AgentBase):
    def __init__(self, model: Any, model_config: Dict[str, Any], system_prefix: str = "", max_model_len: int = 64000):
        super().__init__(model, model_config, system_prefix, max_model_len)
        self.SYSTEM_PREFIX_FIXED = PromptManager().get_agent_prompt_auto("task_stage_summary_system_prefix")
        self.agent_name = "StageSummaryAgent"
        self.agent_description = "任务执行阶段性总结智能体，专门负责生成任务执行的阶段性总结"
        logger.info("StageSummaryAgent 初始化完成")

    async def run_stream(self, session_context: SessionContext, tool_manager: ToolManager = None, session_id: str = None) -> Generator[List[MessageChunk], None, None]:
        # 重新获取带有正确语言的prompt
        self.SYSTEM_PREFIX_FIXED = PromptManager().get_agent_prompt_auto("task_stage_summary_system_prefix", language=session_context.get_language())

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
            history_messages = message_manager.extract_all_context_messages(recent_turns=1, max_length=self.max_history_context_length)
            task_description_messages_str = MessageManager.convert_messages_to_str(history_messages)

        # 提取任务管理器状态
        task_manager_status = task_manager.get_status_description() if task_manager else '无任务管理器'

        # 提取未总结但已完成的任务
        unsummary_but_completed_tasks = task_manager.get_unsummary_but_completed_tasks()
        task_info = []
        for task_item in unsummary_but_completed_tasks:
            info = f"- 任务ID: {task_item.task_id}, 描述: {task_item.description}"
            task_info.append(info)
        tasks_to_summarize = "\n".join(task_info)

        # 提取执行历史
        execution_history_messages = message_manager.extract_after_last_stage_summary_messages()
        execution_history_messages_str = MessageManager.convert_messages_to_str(execution_history_messages)

        # 提取生成的文档
        generated_documents = self._extract_generated_documents(execution_history_messages)
        logger.info(f"执行历史最大的长度:{int((self.max_model_input_len-MessageManager.calculate_str_token_length(task_description_messages_str)-MessageManager.calculate_str_token_length(tasks_to_summarize)-MessageManager.calculate_str_token_length(task_manager_status)-MessageManager.calculate_str_token_length(generated_documents) )//2)}")
        execution_history_messages_str = execution_history_messages_str[-(int((self.max_model_input_len-MessageManager.calculate_str_token_length(task_description_messages_str)-MessageManager.calculate_str_token_length(tasks_to_summarize)-MessageManager.calculate_str_token_length(task_manager_status)-MessageManager.calculate_str_token_length(generated_documents))//2)):]

        task_stage_summary_template = PromptManager().get_agent_prompt_auto("task_stage_summary_template", language=session_context.get_language())
        prompt = task_stage_summary_template.format(
            task_description=task_description_messages_str,
            tasks_to_summarize=tasks_to_summarize,
            task_manager_status=task_manager_status,
            execution_history=execution_history_messages_str,
            generated_documents=generated_documents
        )

        llm_request_message = [
            self.prepare_unified_system_message(session_id=session_id),
            MessageChunk(
                role=MessageRole.USER.value,
                content=prompt,
                message_id=str(uuid.uuid4()),
                show_content=prompt,
                message_type=MessageType.STAGE_SUMMARY.value
            )
        ]
        all_content = ''
        async for llm_repsonse_chunk in self._call_llm_streaming(messages=llm_request_message,
                                                                 session_id=session_id,
                                                                 step_name="stage_summary"):
            if len(llm_repsonse_chunk.choices) == 0:
                continue
            if llm_repsonse_chunk.choices[0].delta.content:
                all_content += llm_repsonse_chunk.choices[0].delta.content

        summary_result = self.convert_xml_to_json(all_content)
        logger.info(f"StageSummaryAgent: 解析总结结果: {summary_result}")
        # 更新所有任务的执行总结
        self._update_all_tasks_execution_summary(summary_result, unsummary_but_completed_tasks, task_manager)

        logger.info(f"StageSummaryAgent: 所有任务总结生成完成")

        yield [MessageChunk(
            message_id=str(uuid.uuid4()),
            role=MessageRole.ASSISTANT.value,
            content="阶段性任务总结："+json.dumps(summary_result, ensure_ascii=False),
            message_type=MessageType.STAGE_SUMMARY.value,
            show_content=""
        )]

    def convert_xml_to_json(self, xml_content: str) -> Dict[str, Any]:
        result = {
            "task_summaries": []
        }
        try:
            # 查找JSON内容
            json_match = re.search(r'\{.*\}', xml_content, re.DOTALL)
            if json_match:
                json_str = json_match.group(0)
                parsed_data = json.loads(json_str)
                result.update(parsed_data)
            else:
                logger.warning("StageSummaryAgent: 未找到有效的JSON内容")
                result["task_summaries"] = []
        except Exception as e:
            logger.error(f"StageSummaryAgent: JSON解析失败: {str(e)}")
            result["task_summaries"] = []
        return result

    def _update_all_tasks_execution_summary(self, summary_result: Dict[str, Any], tasks_to_summarize: List[Any], task_manager: Any) -> None:
        """
        更新所有任务的执行总结

        Args:
            summary_result: 总结结果，包含task_summaries列表
            tasks_to_summarize: 需要总结的任务列表
            task_manager: 任务管理器
        """
        try:
            task_summaries = summary_result.get('task_summaries', [])
            logger.info(f"StageSummaryAgent: 开始更新 {len(tasks_to_summarize)} 个任务的执行总结")

            # 创建task_id到总结的映射
            summary_map = {}
            for task_summary in task_summaries:
                task_id = task_summary.get('task_id')
                if task_id:
                    summary_map[task_id] = task_summary

            updated_count = 0
            for task in tasks_to_summarize:
                task_id = task.task_id
                logger.info(f"StageSummaryAgent: 开始为任务 {task_id} 更新执行总结")

                # 查找对应的总结
                if task_id in summary_map:
                    task_summary = summary_map[task_id]
                    # 更新任务的执行总结
                    task_manager.update_task(
                        task_id,
                        execution_summary=task_summary,
                        summary_generated_at=datetime.datetime.now().isoformat()
                    )
                    updated_count += 1
                    logger.info(f"StageSummaryAgent: 已更新任务 {task_id} 的执行总结")
                    logger.debug(f"StageSummaryAgent: 任务 {task_id} 总结内容: {task_summary}")
                else:
                    logger.warning(f"StageSummaryAgent: 未找到任务 {task_id} 对应的总结")

            logger.info(f"StageSummaryAgent: 共更新了 {updated_count} 个任务的执行总结")

        except Exception as e:
            logger.error(f"StageSummaryAgent: 更新任务执行总结失败: {str(e)}")
            logger.error(f"异常详情: {traceback.format_exc()}")

    def _extract_generated_documents(self, messages: List[MessageChunk]) -> str:
        """
        从消息历史中提取file_write工具调用生成的文件路径

        Args:
            messages: 消息列表

        Returns:
            str: 格式化的生成文档信息
        """
        try:
            generated_files = []

            for message in messages:
                # 检查是否是工具调用消息
                if message.type == MessageType.TOOL_CALL.value:
                    for one_tool_call in message.tool_calls:
                        if one_tool_call['function']['name'] == 'file_write':
                            function_args = one_tool_call['function']['arguments']
                            if isinstance(function_args, str):
                                function_args = json.loads(function_args)
                            generated_files.append({
                                'path': function_args['file_path'],
                            })
            # 格式化输出
            if not generated_files:
                return "本次执行过程中没有生成任何文件文档。"

            formatted_docs = []
            for i, file_info in enumerate(generated_files, 1):
                doc_info = f"{i}. 文件路径: {file_info['path']}"
                formatted_docs.append(doc_info)
            return f"本次执行过程中生成了 {len(generated_files)} 个文件文档：\n" + "\n".join(formatted_docs)

        except Exception as e:
            logger.error(f"StageSummaryAgent: 提取生成文档失败: {str(e)}")
            return "无法提取生成文档信息。"
