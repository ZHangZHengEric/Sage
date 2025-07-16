"""
InquiryAgent 用户询问智能体

专门负责处理用户的询问和交互，提供准确的回答和建议。
当需要向用户询问更多信息时，由该智能体负责生成合适的问题。

作者: Eric ZZ
版本: 1.0
"""

import json
import uuid
import datetime
import traceback
import time
from typing import List, Dict, Any, Optional, Generator

from sagents.agent.agent_base import AgentBase
from sagents.utils.logger import logger


class InquiryAgent(AgentBase):
    """
    用户询问智能体
    
    专门负责处理用户询问，生成用户友好的问题和回答。
    支持流式输出，实时返回询问结果。
    """

    # 询问提示模板常量
    INQUIRY_PROMPT_TEMPLATE = """# 用户询问处理指南

## 当前任务
{task_description}

## 任务执行状态
{task_status}

## 执行历史
{execution_history}

## 处理要求
1. 分析当前任务的执行状态和用户需求
2. 根据执行历史，理解用户的真实意图
3. 如果需要用户提供更多信息：
   - 生成清晰、具体的问题
   - 问题应该帮助推进任务完成
   - 避免重复询问已知信息
4. 如果用户提出了问题：
   - 基于执行历史提供准确回答
   - 解释当前的执行状态和进展
   - 提供有用的建议和后续步骤
5. 保持友好、专业的交流风格

## 特殊规则
1. 优先使用已有信息，减少用户负担
2. 问题要具体明确，避免模糊表达
3. 回答要基于实际执行结果，不要编造信息
4. 如果任务已完成，提供总结和成果展示

## 输出格式
只输出以下格式的XML，不要输出其他内容，不要输出```

<inquiry_type>
询问类型：question（向用户提问）、answer（回答用户问题）、clarification（澄清说明）、summary（总结说明）
</inquiry_type>
<user_friendly_message>
面向用户的友好消息，可以是问题、回答或说明
</user_friendly_message>
<suggested_actions>
建议的后续操作，格式为字符串数组：["操作1", "操作2"]，如果没有建议则为空数组[]
</suggested_actions>
<context_info>
相关的上下文信息，帮助用户理解当前状态
</context_info>
<urgency_level>
紧急程度：low（低）、medium（中）、high（高）
</urgency_level>
"""

    # 系统提示模板常量
    SYSTEM_PREFIX_DEFAULT = """你是一个智能AI助手，专门负责与用户进行友好的交流和询问。你需要理解用户需求，提供有用的回答，并在必要时向用户询问更多信息。"""
    
    def __init__(self, model: Any, model_config: Dict[str, Any], system_prefix: str = ""):
        """
        初始化用户询问智能体
        
        Args:
            model: 语言模型实例
            model_config: 模型配置参数
            system_prefix: 系统前缀提示
        """
        super().__init__(model, model_config, system_prefix)
        self.agent_description = "用户询问智能体，专门负责处理用户询问和交互"
        logger.info("InquiryAgent 初始化完成")

    def run_stream(self, 
                   message_manager: Any,
                   task_manager: Optional[Any] = None,
                   tool_manager: Optional[Any] = None,
                   session_id: Optional[str] = None,
                   system_context: Optional[Dict[str, Any]] = None,
                   user_query: Optional[str] = None) -> Generator[List[Dict[str, Any]], None, None]:
        """
        流式执行用户询问处理
        
        处理用户询问或生成向用户的问题，实时返回处理结果。
        
        Args:
            message_manager: 消息管理器（必需）
            task_manager: 任务管理器
            tool_manager: 可选的工具管理器
            session_id: 可选的会话标识符
            system_context: 系统上下文
            user_query: 用户的具体询问
            
        Yields:
            List[Dict[str, Any]]: 流式输出的询问处理消息块
        """
        if not message_manager:
            raise ValueError("InquiryAgent: message_manager 是必需参数")
        
        # 从MessageManager获取优化后的消息
        optimized_messages = message_manager.filter_messages_for_agent(self.__class__.__name__)
        logger.info(f"InquiryAgent: 开始流式询问处理，获取到 {len(optimized_messages)} 条优化消息")
        
        # 使用基类方法收集和记录流式输出，并将结果添加到MessageManager
        for chunk_batch in self._collect_and_log_stream_output(
            self._execute_inquiry_stream_internal(optimized_messages, tool_manager, session_id, system_context, task_manager, user_query)
        ):
            # Agent自己负责将生成的消息添加到MessageManager
            message_manager.add_messages(chunk_batch, agent_name="InquiryAgent")
            yield chunk_batch

    def _execute_inquiry_stream_internal(self, 
                                       messages: List[Dict[str, Any]],
                                       tool_manager: Optional[Any],
                                       session_id: str,
                                       system_context: Optional[Dict[str, Any]],
                                       task_manager: Optional[Any] = None,
                                       user_query: Optional[str] = None) -> Generator[List[Dict[str, Any]], None, None]:
        """
        内部询问流式执行方法
        
        Args:
            messages: 对话历史记录
            tool_manager: 可选的工具管理器
            session_id: 可选的会话标识符
            system_context: 系统上下文
            task_manager: 任务管理器
            user_query: 用户询问
            
        Yields:
            List[Dict[str, Any]]: 流式输出的询问处理消息块
        """
        try:
            # 准备询问处理上下文
            inquiry_context = self._prepare_inquiry_context(
                messages=messages,
                session_id=session_id,
                system_context=system_context,
                task_manager=task_manager,
                user_query=user_query
            )
            
            logger.info("InquiryAgent: 询问处理上下文准备完成")
            
            # 执行流式询问处理
            yield from self._execute_streaming_inquiry(inquiry_context)
            
        except Exception as e:
            logger.error(f"InquiryAgent: 询问处理过程中发生异常: {str(e)}")
            logger.error(f"异常详情: {traceback.format_exc()}")
            yield from self._handle_inquiry_error(e)

    def _prepare_inquiry_context(self, 
                               messages: List[Dict[str, Any]],
                               session_id: str,
                               system_context: Optional[Dict[str, Any]],
                               task_manager: Optional[Any] = None,
                               user_query: Optional[str] = None) -> Dict[str, Any]:
        """
        准备询问处理所需的上下文信息
        
        Args:
            messages: 对话消息列表
            session_id: 会话ID
            system_context: 系统上下文
            task_manager: 任务管理器
            user_query: 用户询问
            
        Returns:
            Dict[str, Any]: 包含询问处理所需信息的上下文字典
        """
        logger.debug("InquiryAgent: 准备询问处理上下文")
        
        # 提取任务描述
        task_description = self._extract_task_description_to_str(messages)
        
        # 提取执行历史
        execution_history = self._extract_execution_history_to_str(messages)
        
        # 提取任务状态
        task_status = self._extract_task_status(task_manager)
        
        inquiry_context = {
            'task_description': task_description,
            'execution_history': execution_history,
            'task_status': task_status,
            'session_id': session_id,
            'system_context': system_context,
            'user_query': user_query or ""
        }
        
        logger.info("InquiryAgent: 询问处理上下文准备完成")
        return inquiry_context

    def _generate_inquiry_prompt(self, context: Dict[str, Any]) -> str:
        """
        生成询问处理提示
        
        Args:
            context: 询问处理上下文信息
            
        Returns:
            str: 格式化后的询问处理提示
        """
        logger.debug("InquiryAgent: 生成询问处理提示")
        
        prompt = self.INQUIRY_PROMPT_TEMPLATE.format(
            task_description=context['task_description'],
            task_status=context['task_status'],
            execution_history=context['execution_history']
        )
        
        # 如果有用户询问，添加到提示中
        if context.get('user_query'):
            prompt += f"\n\n## 用户询问\n{context['user_query']}\n\n请基于以上信息回答用户的问题。"
        else:
            prompt += "\n\n## 任务\n基于当前状态，判断是否需要向用户询问更多信息，如果需要，生成合适的问题。"
        
        logger.debug("InquiryAgent: 询问处理提示生成完成")
        return prompt

    def _execute_streaming_inquiry(self, 
                                 inquiry_context: Dict[str, Any]) -> Generator[List[Dict[str, Any]], None, None]:
        """
        执行流式询问处理
        
        Args:
            inquiry_context: 询问处理上下文
            
        Yields:
            List[Dict[str, Any]]: 流式输出的消息块
        """
        logger.info("InquiryAgent: 开始执行流式询问处理")
        
        # 准备系统消息
        system_message = self.prepare_unified_system_message(
            session_id=inquiry_context.get('session_id'),
            system_context=inquiry_context.get('system_context')
        )
        
        # 生成询问处理提示
        inquiry_prompt = self._generate_inquiry_prompt(inquiry_context)
        
        # 准备消息列表
        messages = [
            {"role": "system", "content": system_message},
            {"role": "user", "content": inquiry_prompt}
        ]
        
        # 生成消息ID
        message_id = str(uuid.uuid4())
        all_content = ""
        
        logger.info("InquiryAgent: 开始调用LLM进行询问处理")
        
        # 流式调用LLM
        for chunk in self.model.stream(messages, **self.model_config):
            content = self.extract_content_from_chunk(chunk)
            if content:
                all_content += content
                
                # 生成流式消息块
                chunk_message = {
                    "id": message_id,
                    "role": "assistant",
                    "content": content,
                    "timestamp": datetime.datetime.now().isoformat(),
                    "metadata": {
                        "agent": self.__class__.__name__,
                        "type": "inquiry_stream",
                        "session_id": inquiry_context.get('session_id')
                    }
                }
                
                yield [chunk_message]
        
        # 处理完整结果
        yield from self._finalize_inquiry_result(all_content, message_id, inquiry_context)

    def _finalize_inquiry_result(self, 
                               all_content: str, 
                               message_id: str,
                               inquiry_context: Dict[str, Any]) -> Generator[List[Dict[str, Any]], None, None]:
        """
        处理询问处理的最终结果
        
        Args:
            all_content: 完整的LLM输出内容
            message_id: 消息ID
            inquiry_context: 询问处理上下文
            
        Yields:
            List[Dict[str, Any]]: 最终处理结果消息
        """
        try:
            logger.info("InquiryAgent: 开始处理询问处理最终结果")
            
            # 解析XML输出
            inquiry_result = self.convert_xml_to_json(all_content)
            
            # 生成最终消息
            final_message = {
                "id": message_id,
                "role": "assistant", 
                "content": all_content,
                "timestamp": datetime.datetime.now().isoformat(),
                "metadata": {
                    "agent": self.__class__.__name__,
                    "type": "inquiry_result",
                    "session_id": inquiry_context.get('session_id'),
                    "inquiry_result": inquiry_result
                }
            }
            
            logger.info(f"InquiryAgent: 询问处理完成，类型: {inquiry_result.get('inquiry_type', 'unknown')}")
            yield [final_message]
            
        except Exception as e:
            logger.error(f"InquiryAgent: 处理询问结果时发生异常: {str(e)}")
            error_message = {
                "id": message_id,
                "role": "assistant",
                "content": f"询问处理过程中发生错误: {str(e)}",
                "timestamp": datetime.datetime.now().isoformat(),
                "metadata": {
                    "agent": self.__class__.__name__,
                    "type": "inquiry_error",
                    "session_id": inquiry_context.get('session_id')
                }
            }
            yield [error_message]

    def _handle_inquiry_error(self, error: Exception) -> Generator[List[Dict[str, Any]], None, None]:
        """
        处理询问过程中的错误
        
        Args:
            error: 异常对象
            
        Yields:
            List[Dict[str, Any]]: 错误处理消息
        """
        error_message = {
            "id": str(uuid.uuid4()),
            "role": "assistant",
            "content": f"询问处理过程中发生错误: {str(error)}",
            "timestamp": datetime.datetime.now().isoformat(),
            "metadata": {
                "agent": self.__class__.__name__,
                "type": "inquiry_error",
                "error": str(error)
            }
        }
        yield [error_message]

    def convert_xml_to_json(self, xml_content: str) -> Dict[str, Any]:
        """
        将XML格式的询问结果转换为JSON格式
        
        Args:
            xml_content: XML格式的内容
            
        Returns:
            Dict[str, Any]: 解析后的JSON结果
        """
        result = {
            "inquiry_type": "answer",
            "user_friendly_message": "",
            "suggested_actions": [],
            "context_info": "",
            "urgency_level": "low"
        }
        
        try:
            # 解析XML标签
            import re
            
            # 提取各个字段
            patterns = {
                "inquiry_type": r"<inquiry_type>(.*?)</inquiry_type>",
                "user_friendly_message": r"<user_friendly_message>(.*?)</user_friendly_message>",
                "suggested_actions": r"<suggested_actions>(.*?)</suggested_actions>",
                "context_info": r"<context_info>(.*?)</context_info>",
                "urgency_level": r"<urgency_level>(.*?)</urgency_level>"
            }
            
            for field, pattern in patterns.items():
                match = re.search(pattern, xml_content, re.DOTALL)
                if match:
                    value = match.group(1).strip()
                    if field == "suggested_actions":
                        # 解析数组格式
                        try:
                            result[field] = json.loads(value) if value else []
                        except:
                            result[field] = []
                    else:
                        result[field] = value
            
            logger.debug("InquiryAgent: XML转JSON完成")
            
        except Exception as e:
            logger.error(f"InquiryAgent: XML转JSON失败: {str(e)}")
            result["user_friendly_message"] = "处理询问时发生错误，请重试。"
        
        return result

    def _extract_task_description_to_str(self, messages: List[Dict[str, Any]]) -> str:
        """
        从消息中提取任务描述
        
        Args:
            messages: 消息列表
            
        Returns:
            str: 任务描述字符串
        """
        for message in messages:
            if message.get('role') == 'user':
                content = message.get('content', '')
                if len(content) > 20:  # 假设有意义的任务描述至少20字符
                    return content[:500]  # 限制长度
        
        return "未找到明确的任务描述"

    def _extract_execution_history_to_str(self, messages: List[Dict[str, Any]]) -> str:
        """
        从消息中提取执行历史
        
        Args:
            messages: 消息列表
            
        Returns:
            str: 执行历史字符串
        """
        history_parts = []
        
        for message in messages[-10:]:  # 只看最近10条消息
            role = message.get('role', '')
            content = message.get('content', '')
            agent = message.get('metadata', {}).get('agent', '')
            
            if role == 'assistant' and agent:
                summary = content[:200] + "..." if len(content) > 200 else content
                history_parts.append(f"[{agent}]: {summary}")
        
        return "\n".join(history_parts) if history_parts else "暂无执行历史"

    def _extract_task_status(self, task_manager: Optional[Any]) -> str:
        """
        提取任务状态信息
        
        Args:
            task_manager: 任务管理器
            
        Returns:
            str: 任务状态描述
        """
        if not task_manager:
            return "无任务管理器信息"
        
        try:
            if hasattr(task_manager, 'get_compact_status_description'):
                return task_manager.get_compact_status_description()
            elif hasattr(task_manager, 'get_status'):
                status = task_manager.get_status()
                return f"任务状态: {status}"
            else:
                return "任务管理器状态未知"
        except Exception as e:
            logger.error(f"InquiryAgent: 提取任务状态失败: {str(e)}")
            return "任务状态提取失败"

    def run(self, 
            messages: List[Dict[str, Any]], 
            tool_manager: Optional[Any] = None,
            session_id: str = None,
            system_context: Optional[Dict[str, Any]] = None,
            user_query: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        非流式运行方法（兼容性支持）
        
        Args:
            messages: 消息列表
            tool_manager: 工具管理器
            session_id: 会话ID
            system_context: 系统上下文
            user_query: 用户询问
            
        Returns:
            List[Dict[str, Any]]: 询问处理结果消息列表
        """
        logger.warning("InquiryAgent: 使用非流式运行方法，建议使用run_stream")
        
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
            user_query=user_query
        ):
            result_messages.extend(chunk_batch)
        
        return result_messages 