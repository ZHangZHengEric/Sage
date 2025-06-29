"""
TaskSummaryAgent 重构版本

任务总结智能体，负责根据原始任务和执行历史生成清晰完整的回答。
改进了代码结构、错误处理、日志记录和可维护性。

作者: Eric ZZ
版本: 2.0 (重构版)
"""

import json
import uuid
import datetime
import traceback
from typing import List, Dict, Any, Optional, Generator

from agents.agent.agent_base import AgentBase
from agents.utils.logger import logger


class TaskSummaryAgent(AgentBase):
    """
    任务总结智能体
    
    负责根据原始任务和执行历史生成清晰完整的回答。
    支持流式输出，实时返回总结结果。
    """

    # 任务总结提示模板常量
    SUMMARY_PROMPT_TEMPLATE = """根据以下任务和TaskManager状态及执行结果，用自然语言提供清晰完整的回答。
可以使用markdown格式组织内容。

任务: 
{task_description}

TaskManager状态及执行结果:
{task_manager_status_and_results}

你的回答应该:
1. 直接回答原始任务。
2. 使用清晰详细的语言，但要保证回答的完整性和准确性，保留任务执行过程中的关键结果。
3. 如果任务执行过程中生成了文档，那么在回答中应该包含文档的地址引用，方便用户下载。
4. 对于生成的文档，不仅要提供文档地址，还要提供文档内的关键内容摘要。
5. 图表直接使用markdown进行显示。
6. 不是为了总结执行过程，而是以TaskManager中的任务执行结果为基础，生成一个针对用户任务的完美回答。
"""

    # 系统提示模板常量
    SYSTEM_PREFIX_DEFAULT = """你是一个任务总结者，你需要根据原始任务和执行历史，生成清晰完整的回答。"""
    
    def __init__(self, model: Any, model_config: Dict[str, Any], system_prefix: str = ""):
        """
        初始化任务总结智能体
        
        Args:
            model: 语言模型实例
            model_config: 模型配置参数
            system_prefix: 系统前缀提示
        """
        super().__init__(model, model_config, system_prefix)
        self.agent_description = "任务总结智能体，专门负责根据任务和执行历史生成完整回答"
        logger.info("TaskSummaryAgent 初始化完成")

    def run_stream(self, 
                   message_manager: Any,
                   task_manager: Optional[Any] = None,
                   tool_manager: Optional[Any] = None,
                   session_id: Optional[str] = None,
                   system_context: Optional[Dict[str, Any]] = None) -> Generator[List[Dict[str, Any]], None, None]:
        """
        流式执行任务总结
        
        Args:
            message_manager: 消息管理器（必需）
            task_manager: 任务管理器
            tool_manager: 可选的工具管理器
            session_id: 可选的会话标识符
            system_context: 运行时系统上下文字典
            
        Yields:
            List[Dict[str, Any]]: 流式输出的任务总结消息块
        """
        if not message_manager:
            raise ValueError("TaskSummaryAgent: message_manager 是必需参数")
        
        # 从MessageManager获取优化后的消息
        optimized_messages = message_manager.filter_messages_for_agent(self.__class__.__name__)
        logger.info(f"TaskSummaryAgent: 开始流式任务总结，获取到 {len(optimized_messages)} 条优化消息")
        
        # 使用基类方法收集和记录流式输出，并将结果添加到MessageManager
        for chunk_batch in self._collect_and_log_stream_output(
            self._execute_summary_stream_internal(optimized_messages, tool_manager, session_id, system_context, task_manager)
        ):
            # Agent自己负责将生成的消息添加到MessageManager
            message_manager.add_messages(chunk_batch, agent_name="TaskSummaryAgent")
            yield chunk_batch

    def _execute_summary_stream_internal(self, 
                                        messages: List[Dict[str, Any]], 
                                        tool_manager: Optional[Any],
                                        session_id: str,
                                        system_context: Optional[Dict[str, Any]],
                                        task_manager: Optional[Any] = None) -> Generator[List[Dict[str, Any]], None, None]:
        """
        内部任务总结流式执行方法
        
        Args:
            messages: 对话历史记录，包含整个任务流程
            tool_manager: 可选的工具管理器
            session_id: 会话ID
            system_context: 运行时系统上下文字典，用于自定义推理时的变化信息
            
        Yields:
            List[Dict[str, Any]]: 流式输出的任务总结消息块
        """
        try:
            # 准备总结上下文
            summary_context = self._prepare_summary_context(
                messages=messages,
                session_id=session_id,
                system_context=system_context,
                task_manager=task_manager
            )
            
            # 生成总结提示
            prompt = self._generate_summary_prompt(summary_context)
            
            # 执行流式任务总结
            yield from self._execute_streaming_summary(prompt, summary_context)
            
        except Exception as e:
            logger.error(f"TaskSummaryAgent: 任务总结过程中发生异常: {str(e)}")
            logger.error(f"异常详情: {traceback.format_exc()}")
            yield from self._handle_summary_error(e)

    def _prepare_summary_context(self, 
                                messages: List[Dict[str, Any]],
                                session_id: str,
                                system_context: Optional[Dict[str, Any]],
                                task_manager: Optional[Any] = None) -> Dict[str, Any]:
        """
        准备任务总结所需的上下文信息
        
        Args:
            messages: 对话消息列表
            session_id: 会话ID
            system_context: 运行时系统上下文字典，用于自定义推理时的变化信息
            task_manager: 任务管理器
            
        Returns:
            Dict[str, Any]: 包含总结所需信息的上下文字典
        """
        logger.debug("TaskSummaryAgent: 准备任务总结上下文")
        
        # 提取任务描述
        task_description = self._extract_task_description(messages)
        logger.debug(f"TaskSummaryAgent: 提取任务描述，长度: {len(task_description)}")
        
        # 获取TaskManager状态（包含执行结果）
        task_manager_status_and_results = self._extract_task_manager_status(task_manager)
        logger.debug(f"TaskSummaryAgent: 提取TaskManager状态及结果，长度: {len(task_manager_status_and_results)}")
        
        # 获取上下文信息
        current_time = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        file_workspace = '无'
        
        summary_context = {
            'task_description': task_description,
            'task_manager_status_and_results': task_manager_status_and_results,
            'current_time': current_time,
            'file_workspace': file_workspace,
            'session_id': session_id,
            'system_context': system_context,
            'task_manager': task_manager
        }
        
        logger.info("TaskSummaryAgent: 任务总结上下文准备完成")
        return summary_context

    def _generate_summary_prompt(self, context: Dict[str, Any]) -> str:
        """
        生成任务总结提示
        
        Args:
            context: 包含总结所需信息的上下文字典
            
        Returns:
            str: 格式化的总结提示
        """
        prompt = self.SUMMARY_PROMPT_TEMPLATE.format(
            task_description=context['task_description'],
            task_manager_status_and_results=context['task_manager_status_and_results']
        )
        
        logger.debug(f"TaskSummaryAgent: 生成总结提示，长度: {len(prompt)}")
        return prompt

    def _execute_streaming_summary(self, 
                                 prompt: str, 
                                 summary_context: Dict[str, Any]) -> Generator[List[Dict[str, Any]], None, None]:
        """
        执行流式任务总结
        
        Args:
            prompt: 总结提示
            summary_context: 总结上下文
            
        Yields:
            List[Dict[str, Any]]: 流式输出的消息块
        """
        logger.info("TaskSummaryAgent: 开始执行流式任务总结")
        
        # 准备系统消息
        system_message = self.prepare_unified_system_message(
            session_id=summary_context.get('session_id'),
            system_context=summary_context.get('system_context')
        )
        
        # 使用基类的流式处理和token跟踪，传递session_id参数
        yield from self._execute_streaming_with_token_tracking(
            prompt=prompt,
            step_name="task_summary",
            system_message=system_message,
            message_type='final_answer',
            session_id=summary_context.get('session_id')
        )

    def _handle_summary_error(self, error: Exception) -> Generator[List[Dict[str, Any]], None, None]:
        """
        处理总结过程中的错误
        
        Args:
            error: 发生的异常
            
        Yields:
            List[Dict[str, Any]]: 错误消息块
        """
        yield from self._handle_error_generic(
            error=error,
            error_context="任务总结",
            message_type='final_answer'
        )

    def _extract_task_description(self, messages: List[Dict[str, Any]]) -> str:
        """
        从消息中提取原始任务描述
        
        Args:
            messages: 消息列表
            
        Returns:
            str: 任务描述字符串
        """
        logger.debug(f"TaskSummaryAgent: 处理 {len(messages)} 条消息以提取任务描述")
        
        task_description_messages = self._extract_task_description_messages(messages)
        result = self.convert_messages_to_str(task_description_messages)
        
        logger.debug(f"TaskSummaryAgent: 生成任务描述，长度: {len(result)}")
        return result

    def _extract_completed_actions(self, messages: List[Dict[str, Any]]) -> str:
        """
        从消息中提取已完成的操作
        
        Args:
            messages: 消息列表
            
        Returns:
            str: 已完成操作的字符串
        """
        logger.debug(f"TaskSummaryAgent: 处理 {len(messages)} 条消息以提取完成操作")
        
        completed_actions_messages = self._extract_completed_actions_messages(messages)
        result = self.convert_messages_to_str(completed_actions_messages)
        
        logger.debug(f"TaskSummaryAgent: 生成完成操作，长度: {len(result)}")
        return result

    def _extract_task_manager_status(self, task_manager: Optional[Any]) -> str:
        """
        提取TaskManager状态，包括任务执行结果
        
        Args:
            task_manager: 任务管理器实例
            
        Returns:
            str: TaskManager状态的JSON字符串
        """
        if not task_manager:
            return "无TaskManager实例"
        
        try:
            # 获取所有任务的状态
            all_tasks = task_manager.get_all_tasks()
            if not all_tasks:
                return "无任务数据"
            
            # 格式化任务状态，包含执行结果
            status_info = {
                "total_tasks": len(all_tasks),
                "tasks": []
            }
            
            # get_all_tasks返回的是List[TaskBase]，直接遍历TaskBase对象
            for task in all_tasks:
                task_status = {
                    "task_id": task.task_id,
                    "status": task.status.value if hasattr(task.status, 'value') else str(task.status),
                    "description": task.description,
                    "result_documents": task.execution_summary.get("result_documents", []) if task.execution_summary else [],
                    "result_summary": task.execution_summary.get("result_summary", "") if task.execution_summary else "",
                    "execution_summary": task.execution_summary or {}
                }
                
                # 读取文档内容
                if task_status["result_documents"]:
                    task_status["document_contents"] = self._read_document_contents(task_status["result_documents"])
                
                status_info["tasks"].append(task_status)
            
            return json.dumps(status_info, ensure_ascii=False, indent=2)
            
        except Exception as e:
            logger.error(f"TaskSummaryAgent: 提取TaskManager状态时发生错误: {str(e)}")
            return f"提取TaskManager状态失败: {str(e)}"

    def _read_document_contents(self, documents: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        读取文档内容
        
        Args:
            documents: 文档信息列表
            
        Returns:
            List[Dict[str, Any]]: 包含文档内容的列表
        """
        import os
        
        document_contents = []
        
        for doc in documents:
            doc_path = doc.get("path", "")
            doc_type = doc.get("type", "")
            doc_name = doc.get("name", "")
            
            doc_content = {
                "path": doc_path,
                "type": doc_type,
                "name": doc_name,
                "content": ""
            }
            
            # 尝试读取文档内容
            if doc_path and os.path.exists(doc_path):
                try:
                    with open(doc_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                        doc_content["content"] = content
                        logger.debug(f"TaskSummaryAgent: 成功读取文档 {doc_path}")
                except Exception as e:
                    logger.warning(f"TaskSummaryAgent: 读取文档 {doc_path} 失败: {str(e)}")
                    doc_content["content"] = f"文档读取失败: {str(e)}"
            else:
                doc_content["content"] = "文档路径不存在"
            
            document_contents.append(doc_content)
        
        return document_contents

    def _extract_generated_documents(self, task_completion_results: str) -> List[Dict[str, Any]]:
        """
        从任务完成结果中提取生成的文档信息
        
        Args:
            task_completion_results: 任务完成结果的JSON字符串
            
        Returns:
            List[Dict[str, Any]]: 生成的文档信息列表
        """
        try:
            if not task_completion_results or task_completion_results == "无TaskManager实例" or task_completion_results == "无任务数据":
                return []
            
            results_data = json.loads(task_completion_results)
            generated_docs = []
            
            # 从已完成任务中提取文档
            for task in results_data.get("completed_tasks", []):
                task_id = task.get("task_id", "")
                result_docs = task.get("result_documents", [])
                result_summary = task.get("result_summary", "")
                
                for doc in result_docs:
                    doc_info = {
                        "task_id": task_id,
                        "document_path": doc.get("path", ""),
                        "document_type": doc.get("type", ""),
                        "document_name": doc.get("name", ""),
                        "task_summary": result_summary
                    }
                    generated_docs.append(doc_info)
            
            logger.debug(f"TaskSummaryAgent: 提取到 {len(generated_docs)} 个生成文档")
            return generated_docs
            
        except Exception as e:
            logger.error(f"TaskSummaryAgent: 提取生成文档时发生错误: {str(e)}")
            return []

    def run(self, 
            messages: List[Dict[str, Any]], 
            tool_manager: Optional[Any] = None,
            session_id: str = None,
            system_context: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """
        执行任务总结（非流式版本）
        
        Args:
            messages: 对话历史记录
            tool_manager: 可选的工具管理器
            session_id: 会话ID
            system_context: 运行时系统上下文字典，用于自定义推理时的变化信息
            
        Returns:
            List[Dict[str, Any]]: 任务总结结果消息列表
        """
        logger.info("TaskSummaryAgent: 执行非流式任务总结")
        
        # 调用父类的默认实现，将流式结果合并
        return super().run(
            messages=messages,
            tool_manager=tool_manager,
            session_id=session_id,
            system_context=system_context
        )
