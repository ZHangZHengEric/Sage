"""
AgentBase 重构版本

智能体基类，提供所有智能体的通用功能和接口。
改进了代码结构、错误处理、日志记录和可维护性。

作者: Multi-Agent Framework Team
日期: 2024
版本: 2.0 (重构版)
"""

from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional, Generator
import re,json
import uuid
from agents.utils.logger import logger
from agents.tool.tool_base import AgentToolSpec


class AgentBase(ABC):
    """
    智能体基类
    
    为所有智能体提供通用功能和接口，包括消息处理、工具转换、
    流式处理和内容解析等核心功能。
    """

    def __init__(self, model: Any, model_config: Dict[str, Any],system_prefix: str = ""):
        """
        初始化智能体基类
        
        Args:
            model: 可执行的语言模型实例
            model_config: 模型配置参数
            system_prefix: 系统前缀提示
        """
        self.model = model
        self.model_config = model_config
        self.system_prefix = system_prefix
        self.agent_description = f"{self.__class__.__name__} agent"
        logger.debug(f"AgentBase: 初始化 {self.__class__.__name__}，模型配置: {model_config}")
    
    @abstractmethod
    def run_stream(self, 
                   messages: List[Dict[str, Any]], 
                   tool_manager: Optional[Any] = None,
                   context: Optional[Dict[str, Any]] = None,
                   session_id: str = None) -> Generator[List[Dict[str, Any]], None, None]:
        """
        流式处理消息的抽象方法
        
        Args:
            messages: 对话消息列表
            tool_manager: 可选的工具管理器
            context: 可选的上下文字典
            session_id: 会话ID
            
        Yields:
            List[Dict[str, Any]]: 流式输出的消息块
        """
        pass

    def run(self, 
            messages: List[Dict[str, Any]], 
            tool_manager: Optional[Any] = None,
            context: Optional[Dict[str, Any]] = None,
            session_id: str = None) -> List[Dict[str, Any]]:
        """
        处理消息并可选择性使用工具
        
        默认实现通过调用run_stream并合并结果来实现。
        
        Args:
            messages: 对话消息列表
            tool_manager: 可选的工具管理器
            context: 可选的上下文字典
            session_id: 会话ID
            
        Returns:
            List[Dict[str, Any]]: 处理后的消息列表
        """
        logger.debug(f"AgentBase: {self.__class__.__name__} 开始非流式处理")
        
        result_iter = self.run_stream(
            messages=messages, 
            tool_manager=tool_manager, 
            context=context, 
            session_id=session_id
        )
        
        result = []
        for chunk in result_iter:
            result.extend(chunk)
        
        # 合并消息块
        result = self._merge_chunks(result)
        
        logger.debug(f"AgentBase: {self.__class__.__name__} 非流式处理完成，返回 {len(result)} 条消息")
        return result

    def to_tool(self) -> AgentToolSpec:
        """
        将智能体转换为工具格式
        
        Returns:
            AgentToolSpec: 包含智能体运行方法的工具规范
        """
        logger.debug(f"AgentBase: 将 {self.__class__.__name__} 转换为工具格式")
        
        tool_spec = AgentToolSpec(
            name=self.__class__.__name__,
            description=self.agent_description + '\n\n Agent类型的工具，可以自动读取历史对话，所需不需要运行的参数',
            func=self.run,
            parameters={},
            required=[]
        )
        
        return tool_spec
        

    def _extract_json_from_markdown(self, content: str) -> str:
        """
        从markdown代码块中提取JSON内容
        
        Args:
            content: 可能包含markdown代码块的内容
            
        Returns:
            str: 提取的JSON内容，如果没有找到代码块则返回原始内容
        """
        logger.debug("AgentBase: 尝试从内容中提取JSON")
        
        # 首先尝试直接解析
        try:
            json.loads(content)
            return content
        except json.JSONDecodeError:
            pass
        
        # 尝试从markdown代码块中提取
        code_block_pattern = r'```(?:json)?\n([\s\S]*?)\n```'
        match = re.search(code_block_pattern, content)
        
        if match:
            try:
                json.loads(match.group(1))
                logger.debug("AgentBase: 成功从markdown代码块中提取JSON")
                return match.group(1)
            except json.JSONDecodeError:
                logger.warning(f"AgentBase: {self.__class__.__name__} 解析markdown代码块中的JSON失败")
                pass
        
        logger.debug("AgentBase: 未找到有效JSON，返回原始内容")
        return content

    def _extract_completed_actions_messages(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        从消息中提取已完成的操作
        
        Args:
            messages: 消息列表
            
        Returns:
            List[Dict[str, Any]]: 已完成操作的消息列表
        """
        logger.debug(f"AgentBase: {self.__class__.__name__} 从 {len(messages)} 条消息中提取已完成操作")
        
        completed_actions_messages = []
        
        # 从最后一条用户消息开始提取
        for index, msg in enumerate(reversed(messages)):
            if msg['role'] == 'user':
                completed_actions_messages.extend(messages[len(messages) - index:])
                break
        
        # 移除任务分解类型的消息
        completed_actions_messages = [
            msg for msg in completed_actions_messages 
            if msg.get('type') != 'task_decomposition'
        ]

        logger.debug(f"AgentBase: {self.__class__.__name__} 提取了 {len(completed_actions_messages)} 条已完成操作消息")
        return completed_actions_messages

    def _extract_task_description_messages(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        从消息中提取任务描述
        
        Args:
            messages: 消息列表
            
        Returns:
            List[Dict[str, Any]]: 任务描述相关的消息列表
        """
        logger.debug(f"AgentBase: {self.__class__.__name__} 从 {len(messages)} 条消息中提取任务描述")
        
        task_description_messages = []
        
        # 提取到最后一条用户消息为止
        for index, msg in enumerate(reversed(messages)):
            if msg['role'] == 'user':
                task_description_messages.extend(messages[:len(messages) - index])
                break
        
        # 只保留正常类型和最终答案类型的消息
        task_description_messages = [
            msg for msg in task_description_messages 
            if msg.get('type') in ['normal', 'final_answer']
        ]

        logger.debug(f"AgentBase: {self.__class__.__name__} 提取了 {len(task_description_messages)} 条任务描述消息")
        return task_description_messages

    def clean_messages(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        清理消息，只保留OpenAI需要的字段
        
        Args:
            messages: 原始消息列表
            
        Returns:
            List[Dict[str, Any]]: 清理后的消息列表
        """
        logger.debug(f"AgentBase: 清理 {len(messages)} 条消息")
        
        clean_messages = []
        
        for msg in messages:
            if 'tool_calls' in msg and msg['tool_calls'] is not None:
                clean_messages.append({
                    'role': msg['role'],
                    'tool_calls': msg['tool_calls']
                })
            elif 'content' in msg:
                if 'tool_call_id' in msg:
                    clean_messages.append({
                        'role': msg['role'],
                        'content': msg['content'],
                        'tool_call_id': msg['tool_call_id']
                    })
                else:
                    clean_messages.append({
                        'role': msg['role'],
                        'content': msg['content']
                    })
        
        logger.debug(f"AgentBase: 清理后保留 {len(clean_messages)} 条消息")
        return clean_messages

    def _merge_messages(self, 
                       all_messages: List[Dict[str, Any]], 
                       new_messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        通过message_id将新消息合并到现有消息中
        
        Args:
            all_messages: 当前完整的消息列表
            new_messages: 要合并的新消息
            
        Returns:
            List[Dict[str, Any]]: 合并后的消息列表
        """
        merged = []
        message_map = {}
        
        # 首先添加所有现有消息
        for msg in all_messages:
            msg_copy = msg.copy()
            merged.append(msg_copy)
            message_map[msg_copy['message_id']] = msg_copy
        
        # 然后合并新消息
        for msg in new_messages:
            msg_copy = msg.copy()
            if 'message_id' not in msg_copy:
                logger.warning("AgentBase: 发现缺少message_id的消息")
                continue
                
            msg_id = msg_copy['message_id']
            
            if msg_id in message_map:
                # 更新现有消息内容
                existing = message_map[msg_id]
                if 'content' in existing:
                    existing['content'] += msg_copy.get('content', '')
                if 'show_content' in existing:                
                    existing['show_content'] += msg_copy.get('show_content', '')
            else:
                # 添加新消息
                merged.append(msg_copy)
                message_map[msg_id] = msg_copy
        
        return merged

    def _merge_chunks(self, chunks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        合并消息块，将具有相同message_id的块合并
        
        Args:
            chunks: 消息块列表
            
        Returns:
            List[Dict[str, Any]]: 合并后的消息列表
        """
        if not chunks:
            return []
        
        merged_map = {}
        result = []
        
        for chunk in chunks:
            message_id = chunk.get('message_id')
            if not message_id:
                result.append(chunk)
                continue
                
            if message_id in merged_map:
                # 合并内容
                existing = merged_map[message_id]
                if 'content' in chunk:
                    existing['content'] = existing.get('content', '') + chunk['content']
                if 'show_content' in chunk:
                    existing['show_content'] = existing.get('show_content', '') + chunk['show_content']
            else:
                merged_map[message_id] = chunk.copy()
                result.append(merged_map[message_id])
        
        return result

    def convert_messages_to_str(self, messages: List[Dict[str, Any]]) -> str:
        """
        将消息列表转换为字符串格式
        
        Args:
            messages: 消息列表
            
        Returns:
            str: 格式化后的消息字符串
        """
        logger.debug(f"AgentBase: 将 {len(messages)} 条消息转换为字符串")
        
        messages_str_list = []
        
        for msg in messages:
            if msg['role'] == 'user':
                messages_str_list.append(f"User: {msg['content']}")
            elif msg['role'] == 'assistant':
                if 'content' in msg:
                    messages_str_list.append(f"Assistant: {msg['content']}")
                elif 'tool_calls' in msg:
                    messages_str_list.append(f"Assistant: Tool calls: {msg['tool_calls']}")
            elif msg['role'] == 'tool':
                messages_str_list.append(f"Tool: {msg['content']}")
        
        result = "\n".join(messages_str_list) or "None"
        logger.debug(f"AgentBase: 转换后字符串长度: {len(result)}")
        return result
    
    def _judge_delta_content_type(self, 
                                 delta_content: str, 
                                 all_tokens_str: str, 
                                 tag_type: List[str] = None) -> str:
        """
        判断增量内容的类型
        
        Args:
            delta_content: 增量内容
            all_tokens_str: 所有token字符串
            tag_type: 标签类型列表
            
        Returns:
            str: 内容类型
        """
        if tag_type is None:
            tag_type = []
            
        start_tag = [f"<{tag}>" for tag in tag_type]
        end_tag = [f"</{tag}>" for tag in tag_type]
        
        # 构造结束标签的所有可能前缀
        end_tag_process_list = []
        for tag in end_tag:
            for i in range(len(tag)):
                end_tag_process_list.append(tag[:i + 1])    
        
        last_tag = None
        last_tag_index = None
        
        all_tokens_str = (all_tokens_str + delta_content).strip()
        
        # 查找最后出现的标签
        for tag in start_tag + end_tag:
            index = all_tokens_str.rfind(tag)
            if index != -1:
                if last_tag_index is None or index > last_tag_index:
                    last_tag = tag
                    last_tag_index = index
        
        if last_tag is None:
            return "tag"
            
        if last_tag in start_tag:
            if last_tag_index + len(last_tag) == len(all_tokens_str):
                return 'tag'    
            for end_tag_process in end_tag_process_list:
                if all_tokens_str.endswith(end_tag_process):
                    return 'unknown'
            else:
                return last_tag.replace('<', '').replace('>', '')
        elif last_tag in end_tag:
            return 'tag'
