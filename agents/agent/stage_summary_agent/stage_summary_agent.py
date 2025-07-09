"""
StageSummaryAgent 阶段总结智能体

负责对任务执行的不同阶段进行总结，提供进度汇报和成果展示。
当任务达到重要节点或用户需要了解进展时，由该智能体生成总结报告。

作者: Eric ZZ
版本: 1.0
"""

import json
import uuid
import datetime
import traceback
import time
from typing import List, Dict, Any, Optional, Generator

from agents.agent.agent_base import AgentBase
from agents.utils.logger import logger

class StageSummaryAgent(AgentBase):
    """
    阶段总结智能体
    
    专门负责生成任务执行的阶段性总结，包括进度汇报、成果展示和下一步规划。
    支持流式输出，实时返回总结结果。
    """

    # 总结提示模板常量
    SUMMARY_PROMPT_TEMPLATE = """# 任务执行总结生成指南

## 总任务描述
{task_description}

## 需要总结的任务列表
{tasks_to_summarize}

## 任务管理器状态
{task_manager_status}

## 执行过程
{execution_history}

## 生成的文件文档
{generated_documents}

## 总结要求
分析每个需要总结的任务的执行情况，为每个任务生成独立的执行总结。

## 输出格式
只输出以下格式的JSON，不要输出其他内容，不要输出```：

{{
  "task_summaries": [
    {{
      "task_id": "任务ID",
      "result_documents": ["文档路径1", "文档路径2"],
      "result_summary": "详细的任务执行结果总结报告"
    }},
    {{
      "task_id": "任务ID",
      "result_documents": ["文档路径1", "文档路径2"],
      "result_summary": "详细的任务执行结果总结报告"
    }}
  ]
}}

## 说明
1. task_summaries: 包含所有需要总结的任务的总结列表
2. 每个任务总结包含：
   - task_id: 必须与需要总结的任务列表中的task_id完全一致
   - result_documents: 执行过程中通过file_write工具生成的实际文档路径列表，从生成的文件文档中提取对应任务的文档
   - result_summary: 详细的任务执行结果（不要强调过程）总结报告，要求内容详实、结构清晰，不要仅仅是总结，要包含详细的数据结果，方便最后总结使用。
3. result_summary要求：
   - 内容详实：像写正式报告文档一样详细，内容越多越详细越好
   - 结构清晰：使用段落和要点来组织内容，便于阅读和理解
   - 数据具体：包含具体的数据、数字、比例等量化信息
   - 分析深入：不仅描述事实，还要提供分析和洞察
   - 语言专业：使用专业、准确的语言描述
4. 总结要客观准确，突出关键成果和重要发现
5. 每个任务的总结内容应该专门针对该任务，不要包含其他任务的信息
6. task_id必须与需要总结的任务列表中的task_id完全匹配
7. result_documents必须是从生成的文件文档中提取的实际文件路径
8. result_summary的重点是对子任务的详细回答和关键成果，为后续整体任务总结提供丰富的基础信息
"""

    # 系统提示模板常量
    SYSTEM_PREFIX_DEFAULT = """你是一个智能AI助手，专门负责生成任务执行的阶段性总结。你需要客观分析执行情况，总结成果，并为用户提供清晰的进度汇报。"""
    
    def __init__(self, model: Any, model_config: Dict[str, Any], system_prefix: str = ""):
        """
        初始化阶段总结智能体
        
        Args:
            model: 语言模型实例
            model_config: 模型配置参数
            system_prefix: 系统前缀提示
        """
        super().__init__(model, model_config, system_prefix)
        self.agent_description = "阶段总结智能体，专门负责生成任务执行的阶段性总结"
        logger.info("StageSummaryAgent 初始化完成")

    def run_stream(self, 
                   message_manager: Any,
                   task_manager: Optional[Any] = None,
                   tool_manager: Optional[Any] = None,
                   session_id: Optional[str] = None,
                   system_context: Optional[Dict[str, Any]] = None,
                   stage_info: Optional[Dict[str, Any]] = None) -> Generator[List[Dict[str, Any]], None, None]:
        """
        执行阶段总结，返回stage summary类型的消息块
        
        生成任务执行的阶段性总结，更新任务信息，并返回stage summary消息。
        
        Args:
            message_manager: 消息管理器（必需）
            task_manager: 任务管理器
            tool_manager: 可选的工具管理器
            session_id: 可选的会话标识符
            system_context: 系统上下文
            stage_info: 阶段信息，包含当前阶段的特定信息
            
        Yields:
            List[Dict[str, Any]]: stage summary类型的消息块
        """
        if not message_manager:
            raise ValueError("StageSummaryAgent: message_manager 是必需参数")
        
        # 从MessageManager获取优化后的消息
        optimized_messages = message_manager.filter_messages_for_agent(self.__class__.__name__)
        logger.info(f"StageSummaryAgent: 开始阶段总结，获取到 {len(optimized_messages)} 条优化消息")
        
        # 执行阶段总结，并返回消息块
        yield from self._execute_summary_stream_internal(optimized_messages, tool_manager, session_id, system_context, task_manager, stage_info)

    def _execute_summary_stream_internal(self, 
                                       messages: List[Dict[str, Any]],
                                       tool_manager: Optional[Any],
                                       session_id: str,
                                       system_context: Optional[Dict[str, Any]],
                                       task_manager: Optional[Any] = None,
                                       stage_info: Optional[Dict[str, Any]] = None) -> Generator[List[Dict[str, Any]], None, None]:
        """
        内部阶段总结流式执行方法
        
        Args:
            messages: 包含任务分析的对话历史记录
            tool_manager: 提供可用工具的工具管理器实例
            session_id: 会话ID
            system_context: 系统上下文
            task_manager: 任务管理器
            stage_info: 阶段信息
            
        Yields:
            List[Dict[str, Any]]: 流式输出的总结结果消息块
        """
        try:
            # 准备总结上下文
            summary_context = self._prepare_summary_context(
                messages=messages,
                task_manager=task_manager,
                session_id=session_id,
                system_context=system_context
            )
            
            # 确保task_manager在上下文中
            summary_context['task_manager'] = task_manager
            
            # 执行流式总结
            yield from self._execute_streaming_summary(summary_context)
            
        except Exception as e:
            logger.error(f"StageSummaryAgent: 总结过程中发生异常: {str(e)}")
            logger.error(f"异常详情: {traceback.format_exc()}")
            yield from self._handle_summary_error(e)

    def _prepare_summary_context(self, 
                               messages: List[Dict[str, Any]],
                               task_manager: Optional[Any],
                               session_id: str,
                               system_context: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """
        准备阶段总结所需的上下文信息
        
        Args:
            messages: 对话消息列表
            task_manager: 任务管理器
            session_id: 会话ID
            system_context: 系统上下文
            
        Returns:
            Dict[str, Any]: 包含总结所需信息的上下文字典
        """
        logger.debug("StageSummaryAgent: 准备阶段总结上下文")
        
        # 提取任务描述
        task_description_messages = self._extract_task_description_messages(messages)
        task_description = self.convert_messages_to_str(task_description_messages)
        logger.debug(f"StageSummaryAgent: 提取任务描述，长度: {len(task_description)}")
        
        # 获取任务管理器状态
        task_manager_status = task_manager.get_status_description() if task_manager else '无任务管理器'
        logger.debug(f"StageSummaryAgent: 任务管理器状态: {task_manager_status}")
        
        # 获取需要总结的子任务
        tasks_to_summarize = self._get_subtasks_to_summarize(task_manager)
        subtasks_to_summarize = self._format_tasks_for_prompt(tasks_to_summarize)
        logger.debug(f"StageSummaryAgent: 需要总结的子任务: {subtasks_to_summarize}")
        
        # 提取执行历史
        completed_actions_messages = self._extract_completed_actions_messages(messages)
        execution_history = self.convert_messages_to_str(completed_actions_messages)
        logger.debug(f"StageSummaryAgent: 提取执行历史，长度: {len(execution_history)}")
        
        # 提取生成的文件文档
        generated_documents = self._extract_generated_documents(messages)
        logger.debug(f"StageSummaryAgent: 提取生成文档，数量: {len(generated_documents)}")
        
        # 获取上下文信息
        current_time = system_context.get('current_datatime_str', datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')) if system_context else datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        # 将任务对象列表保存到上下文中，供后续更新使用
        summary_context = {
            'task_description': task_description,
            'task_manager_status': task_manager_status,
            'subtasks_to_summarize': subtasks_to_summarize,
            'execution_history': execution_history,
            'generated_documents': generated_documents,
            'current_time': current_time,
            'session_id': session_id,
            'system_context': system_context or {},
            'tasks_to_summarize': tasks_to_summarize  # 保存任务对象列表
        }
        
        return summary_context

    def _generate_summary_prompt(self, context: Dict[str, Any]) -> str:
        """
        生成阶段总结提示
        
        Args:
            context: 总结上下文
            
        Returns:
            str: 生成的提示文本
        """
        return self.SUMMARY_PROMPT_TEMPLATE.format(
            task_description=context.get('task_description', ''),
            tasks_to_summarize=context.get('subtasks_to_summarize', ''),
            task_manager_status=context.get('task_manager_status', ''),
            execution_history=context.get('execution_history', ''),
            generated_documents=context.get('generated_documents', '')
        )

    def _execute_streaming_summary(self, 
                                 summary_context: Dict[str, Any]) -> Generator[List[Dict[str, Any]], None, None]:
        """
        执行流式总结，为所有需要总结的任务生成总结
        
        Args:
            summary_context: 总结上下文
            
        Yields:
            List[Dict[str, Any]]: 流式输出的总结结果消息块
        """
        try:
            task_manager = summary_context.get('task_manager')
            tasks_to_summarize = summary_context.get('tasks_to_summarize', [])
            
            if not task_manager or not tasks_to_summarize:
                logger.info("StageSummaryAgent: 没有需要总结的任务")
                yield []
                return
            
            logger.info(f"StageSummaryAgent: 开始为 {len(tasks_to_summarize)} 个任务生成总结")
            
            # 生成总结提示
            summary_prompt = self._generate_summary_prompt(summary_context)
            
            # 调用LLM生成总结
            response = self.model.chat.completions.create(
                messages=[{"role": "user", "content": summary_prompt}],
                **self.model_config
            )
            
            # 获取响应内容
            summary_response = response.choices[0].message.content
            
            # 解析总结结果
            summary_result = self.convert_xml_to_json(summary_response)
            
            # 更新所有任务的执行总结
            self._update_all_tasks_execution_summary(summary_result, tasks_to_summarize, task_manager)
            
            logger.info(f"StageSummaryAgent: 所有任务总结生成完成")
            
            # 返回stage summary类型的消息
            stage_summary_message = {
                "id": str(uuid.uuid4()),
                "role": "assistant",
                "content": json.dumps(summary_result,ensure_ascii=False),
                "type": "stage_summary",
                "show_content":""
            }
            
            yield [stage_summary_message]
            
        except Exception as e:
            logger.error(f"StageSummaryAgent: 流式总结执行失败: {str(e)}")
            logger.error(f"异常详情: {traceback.format_exc()}")
            yield from self._handle_summary_error(e)

    def _update_task_execution_summary(self, summary_result: Dict[str, Any], summary_context: Dict[str, Any]) -> None:
        """
        更新任务执行总结，将总结作为任务的独立字段
        
        Args:
            summary_result: 总结结果
            summary_context: 总结上下文
        """
        logger.info(f"StageSummaryAgent: 更新任务执行总结: {summary_result}")
        try:
            # 从上下文中获取task_manager和需要更新的任务列表
            task_manager = summary_context.get('task_manager')
            tasks_to_summarize = summary_context.get('tasks_to_summarize', [])
            
            if not task_manager:
                logger.warning("StageSummaryAgent: 未找到task_manager，跳过任务更新")
                return
            
            if not tasks_to_summarize:
                logger.info("StageSummaryAgent: 没有需要总结的任务")
                return
            
            # 更新指定的需要总结的任务
            updated_count = 0
            for task in tasks_to_summarize:
                # 将总结作为任务的独立字段
                task_manager.update_task(
                    task.task_id, 
                    execution_summary=summary_result,
                    summary_generated_at=datetime.datetime.now().isoformat()
                )
                updated_count += 1
                
                logger.info(f"StageSummaryAgent: 已更新任务 {task.task_id} 的执行总结")
            
            logger.info(f"StageSummaryAgent: 共更新了 {updated_count} 个任务的执行总结")
                
        except Exception as e:
            logger.error(f"StageSummaryAgent: 更新任务执行总结失败: {str(e)}")

    def _handle_summary_error(self, error: Exception) -> Generator[List[Dict[str, Any]], None, None]:
        """
        处理阶段总结过程中的错误
        
        Args:
            error: 异常对象
            
        Yields:
            List[Dict[str, Any]]: 错误处理消息
        """
        error_message = {
            "id": str(uuid.uuid4()),
            "role": "assistant",
            "content": f"阶段总结过程中发生错误: {str(error)}",
            "timestamp": datetime.datetime.now().isoformat(),
            "metadata": {
                "agent": self.__class__.__name__,
                "type": "summary_error",
                "error": str(error)
            }
        }
        yield [error_message]

    def convert_xml_to_json(self, xml_content: str) -> Dict[str, Any]:
        """
        将LLM输出内容转换为JSON格式
        
        Args:
            xml_content: LLM输出的内容
            
        Returns:
            Dict[str, Any]: 解析后的JSON结果
        """
        result = {
            "task_summaries": []
        }
        
        try:
            # 尝试直接解析JSON
            import re
            
            # 查找JSON内容
            json_match = re.search(r'\{.*\}', xml_content, re.DOTALL)
            if json_match:
                json_str = json_match.group(0)
                parsed_data = json.loads(json_str)
                result.update(parsed_data)
            else:
                logger.warning("StageSummaryAgent: 未找到有效的JSON内容")
                result["task_summaries"] = []
            
            logger.debug("StageSummaryAgent: JSON解析完成")
            
        except Exception as e:
            logger.error(f"StageSummaryAgent: JSON解析失败: {str(e)}")
            result["task_summaries"] = []
        
        return result

    def _get_subtasks_to_summarize(self, task_manager: Optional[Any]) -> List[Any]:
        """
        获取需要总结的子任务信息
        
        Args:
            task_manager: 任务管理器
            
        Returns:
            List[Any]: 需要总结的子任务信息
        """
        if not task_manager:
            logger.warning("StageSummaryAgent: task_manager为空")
            return []
        
        try:
            # 获取所有已完成但缺少执行总结的任务
            completed_tasks = task_manager.get_tasks_by_status('completed')
            logger.info(f"StageSummaryAgent: 获取到 {len(completed_tasks)} 个已完成任务")
            
            tasks_to_summarize = []
            
            for task in completed_tasks:
                logger.debug(f"StageSummaryAgent: 检查任务 {task.task_id}: {task.description}")
                logger.debug(f"StageSummaryAgent: 任务 {task.task_id} 的属性: {dir(task)}")
                
                # 检查是否有执行总结
                has_execution_summary = hasattr(task, 'execution_summary')
                execution_summary_value = getattr(task, 'execution_summary', None)
                
                logger.debug(f"StageSummaryAgent: 任务 {task.task_id} has_execution_summary={has_execution_summary}, execution_summary_value={execution_summary_value}")
                
                # 检查execution_summary是否存在且result_summary不为空
                has_valid_summary = False
                if has_execution_summary and execution_summary_value:
                    if isinstance(execution_summary_value, dict):
                        result_documents = execution_summary_value.get('result_documents', [])
                        result_summary = execution_summary_value.get('result_summary', '')
                        
                        # 只要result_documents有文件路径或者result_summary有文字信息，满足其中一个就认为已有总结
                        has_documents = bool(result_documents and len(result_documents) > 0)
                        has_summary_text = bool(result_summary and result_summary.strip())
                        has_valid_summary = has_documents or has_summary_text
                        
                        logger.debug(f"StageSummaryAgent: 任务 {task.task_id} result_documents={result_documents}, result_summary='{result_summary}', has_documents={has_documents}, has_summary_text={has_summary_text}, has_valid_summary={has_valid_summary}")
                    else:
                        has_valid_summary = bool(execution_summary_value)
                
                if not has_valid_summary:
                    tasks_to_summarize.append(task)
                    logger.info(f"StageSummaryAgent: 任务 {task.task_id} 需要总结")
                else:
                    logger.info(f"StageSummaryAgent: 任务 {task.task_id} 已有总结，跳过")
            
            logger.info(f"StageSummaryAgent: 最终需要总结的任务数量: {len(tasks_to_summarize)}")
            
            if not tasks_to_summarize:
                return []
            
            return tasks_to_summarize
            
        except Exception as e:
            logger.error(f"StageSummaryAgent: 获取需要总结的子任务失败: {str(e)}")
            logger.error(f"异常详情: {traceback.format_exc()}")
            return []

    def _format_tasks_for_prompt(self, tasks: List[Any]) -> str:
        """
        格式化任务信息为适合提示的格式
        
        Args:
            tasks: 任务对象列表
            
        Returns:
            str: 格式化后的任务信息
        """
        task_info = []
        for task in tasks:
            info = f"- 任务ID: {task.task_id}, 描述: {task.description}"
            if hasattr(task, 'result') and task.result:
                info += f", 结果: {str(task.result)[:100]}..."
            task_info.append(info)
        
        return "\n".join(task_info)

    def run(self, 
            messages: List[Dict[str, Any]], 
            tool_manager: Optional[Any] = None,
            session_id: str = None,
            system_context: Optional[Dict[str, Any]] = None,
            stage_info: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """
        非流式运行方法（兼容性支持）
        
        Args:
            messages: 消息列表
            tool_manager: 工具管理器
            session_id: 会话ID
            system_context: 系统上下文
            stage_info: 阶段信息
            
        Returns:
            List[Dict[str, Any]]: 阶段总结结果消息列表
        """
        logger.warning("StageSummaryAgent: 使用非流式运行方法，建议使用run_stream")
        
        # 创建临时消息管理器
        class TempMessageManager:
            def __init__(self):
                self.messages = messages
            
            def filter_messages_for_agent(self, agent_name):
                return self.messages
            
            def add_messages(self, new_messages):
                self.messages.extend(new_messages)
        
        temp_manager = TempMessageManager()
        result_messages = []
        
        # 收集所有流式输出
        for chunk_batch in self.run_stream(
            message_manager=temp_manager,
            tool_manager=tool_manager,
            session_id=session_id,
            system_context=system_context,
            stage_info=stage_info
        ):
            result_messages.extend(chunk_batch)
        
        return result_messages

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

    def _extract_generated_documents(self, messages: List[Dict[str, Any]]) -> str:
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
                if message.get('type') == 'tool_call' and message.get('tool_name') == 'file_write':
                    # 提取工具调用的结果
                    tool_result = message.get('tool_result', {})
                    if isinstance(tool_result, dict) and tool_result.get('status') == 'success':
                        file_info = tool_result.get('file_info', {})
                        file_path = file_info.get('path', '')
                        if file_path:
                            generated_files.append({
                                'path': file_path,
                                'size_mb': file_info.get('size_mb', 0),
                                'timestamp': tool_result.get('operation', {}).get('timestamp', ''),
                                'content_length': tool_result.get('operation', {}).get('content_length', 0)
                            })
                
                # 检查消息内容中是否包含file_write工具调用的信息
                content = message.get('content', '')
                if isinstance(content, str) and 'file_write' in content:
                    # 尝试从内容中提取文件路径信息
                    import re
                    # 查找文件路径模式
                    file_paths = re.findall(r'文件路径[：:]\s*([^\s\n]+)', content)
                    for file_path in file_paths:
                        if file_path and file_path not in [f['path'] for f in generated_files]:
                            generated_files.append({
                                'path': file_path,
                                'size_mb': 0,
                                'timestamp': message.get('timestamp', ''),
                                'content_length': 0
                            })
            
            # 格式化输出
            if not generated_files:
                return "本次执行过程中没有生成任何文件文档。"
            
            formatted_docs = []
            for i, file_info in enumerate(generated_files, 1):
                doc_info = f"{i}. 文件路径: {file_info['path']}"
                if file_info['size_mb'] > 0:
                    doc_info += f", 大小: {file_info['size_mb']:.2f}MB"
                if file_info['content_length'] > 0:
                    doc_info += f", 内容长度: {file_info['content_length']}字符"
                if file_info['timestamp']:
                    doc_info += f", 生成时间: {file_info['timestamp']}"
                formatted_docs.append(doc_info)
            
            return f"本次执行过程中生成了 {len(generated_files)} 个文件文档：\n" + "\n".join(formatted_docs)
            
        except Exception as e:
            logger.error(f"StageSummaryAgent: 提取生成文档失败: {str(e)}")
            return "无法提取生成文档信息。" 