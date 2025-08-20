"""
MessageManager 优化版消息管理器

专门管理非system消息，提供完整的消息管理功能：
- 增加message chunk
- 增加完整message
- 合并message (参考agent_base.py实现)
- 过滤和压缩消息
- 获取所有消息

注意：此类不处理system消息，所有system消息会被过滤掉

作者: Eric ZZ
版本: 2.0 (优化版)
"""

import json
import datetime
from math import log
import uuid
from typing import Dict, List, Optional, Any, Set, Union
from copy import deepcopy
import dataclasses
from sagents.utils.logger import logger
from .message import MessageRole, MessageType, MessageChunk

class MessageManager:
    """
    优化版消息管理器
    
    专门管理非system消息，提供完整的消息管理功能。
    不允许保存system消息，所有system消息会被自动过滤。
    """
    
    def __init__(self, session_id: Optional[str] = None, 
                 max_token_limit: int = 8000,
                 compression_threshold: float = 0.7):
        """
        初始化消息管理器
        
        Args:
            session_id: 会话ID
            max_token_limit: 最大token限制
            compression_threshold: 压缩阈值
        """
        self.session_id = session_id or f"session_{uuid.uuid4().hex[:8]}"
        self.max_token_limit = max_token_limit
        self.compression_threshold = compression_threshold
        
        # 消息存储（只存储非system消息）
        self.messages: List[MessageChunk] = []
        
        # 兼容性：保留pending_chunks属性（现在已不使用）
        self.pending_chunks = []

        
        # 统计信息
        self.stats = {
            'total_messages': 0,
            'total_chunks': 0,
            'merged_messages': 0,
            'filtered_messages': 0,
            'compressed_messages': 0,
            'system_messages_rejected': 0,
            'created_at': datetime.datetime.now().isoformat(),
            'last_updated': datetime.datetime.now().isoformat()
        }
        
        logger.info(f"MessageManager: 初始化完成，会话ID: {self.session_id}")

    def add_messages(self, messages: Union[MessageChunk, List[MessageChunk]], agent_name: Optional[str] = None) -> bool:
        """
        添加消息或消息列表
        
        Args:
            messages: 消息实例或消息列表
            agent_name: 智能体名称
        """
        if isinstance(messages, MessageChunk):
            messages = [messages]
        
        for message in messages:
            try:
                if message.role == MessageRole.SYSTEM.value:
                    self.stats['system_messages_rejected'] += 1
                    continue
            except:
                logger.error(f"MessageManager: 添加消息失败，消息内容: {message}")
                continue

            self.messages = MessageManager.merge_new_message_old_messages(message,self.messages)
        self.stats['total_messages'] = len(self.messages)
        self.stats['total_chunks'] += len(messages)
        self.stats['last_updated'] = datetime.datetime.now().isoformat()
        return True
    @staticmethod
    def merge_new_messages_to_old_messages(new_messages: List[ Union[MessageChunk, Dict]],old_messages: List[Union[MessageChunk, Dict]]) -> List[MessageChunk]:
        """
        合并新消息列表和旧消息列表
        
        Args:
            new_messages: 新消息列表
            old_messages: 旧消息列表
        """
        new_messages_chunks = [MessageChunk(**msg) if isinstance(msg, dict) else msg for msg in new_messages]
        old_messages_chunks = [MessageChunk(**msg) if isinstance(msg, dict) else msg for msg in old_messages]
        for new_message in new_messages_chunks:
            old_messages_chunks = MessageManager.merge_new_message_old_messages(new_message,old_messages_chunks)
        return old_messages_chunks
    @staticmethod
    def merge_new_message_old_messages(new_message:MessageChunk,old_messages:List[MessageChunk])->List[MessageChunk]:
        """
        合并新消息和旧消息
        
        Args:
            new_message: 新消息
            old_messages: 旧消息列表
        
        Returns:
            合并后的消息列表
        """
        old_messages = deepcopy(old_messages)
        new_message_id = new_message.message_id
        # 有new_message_id，查找是否已存在相同message_id的消息，如果old最后一个相同则认为找到，否则认为没有找到
        existing_message = old_messages[-1] if old_messages and old_messages[-1].message_id == new_message_id else None
        if existing_message:
            # 流式消息的特点是每次传递的都是新的增量内容
            if new_message.content is not None:
                existing_message.content = (existing_message.content or '') + new_message.content
            if new_message.show_content is not None:
                existing_message.show_content = (existing_message.show_content or '') + new_message.show_content                    
        else:                    
            old_messages.append(new_message)
            # logger.debug(f"MessageManager: 创建新消息 {new_message.message_id[:8]}... ")
        return old_messages
    
    @staticmethod
    def convert_messages_to_str(messages: List[MessageChunk]) -> str:
        """
        将消息列表转换为字符串格式
        
        Args:
            messages: 消息列表
            
        Returns:
            str: 格式化后的消息字符串
        """
        logger.info(f"AgentBase: 将 {len(messages)} 条消息转换为字符串")
        
        messages_str_list = []
        
        for msg in messages:
            if msg.role == 'user':
                messages_str_list.append(f"User: {msg.content}")
            elif msg.role == 'assistant':
                if msg.content is not None:
                    messages_str_list.append(f"Assistant: {msg.content}")
                elif msg.tool_calls is not None:
                    messages_str_list.append(f"Assistant: Tool calls: {msg.tool_calls}")
            elif msg.role == 'tool':
                messages_str_list.append(f"Tool: {msg.content}")
        
        result = "\n".join(messages_str_list) or "None"
        logger.info(f"AgentBase: 转换后字符串长度: {len(result)}")
        return result

    def filter_messages(self,context_length_limited:int=10000,
                    accept_message_type:List[MessageType]=[],
                    recent_turns:int=0)->List[MessageChunk]:
        """
        过滤消息，返回符合所有条件的消息列表,深拷贝
        
        Args:
            context_length_limited: 上下文长度限制，0表示不限制
            accept_message_type: 接受的消息类型集合，空表示接受所有类型
            recent_turns: 最近的对话轮数，0表示不限制

        Returns:
            过滤后的消息列表
        """
        
        filtered_messages = deepcopy(self.messages)
        # 过滤消息类型
        if accept_message_type:
            filtered_messages = [msg for msg in filtered_messages if msg.type in accept_message_type]
        # 过滤最近轮数
        if recent_turns > 0:
            filtered_messages = filtered_messages[-recent_turns:]
        # 过滤上下文长度
        if context_length_limited > 0:
            filtered_messages = filtered_messages[-context_length_limited:]
        return filtered_messages

    def extract_all_user_and_final_answer_messages(self) -> List[MessageChunk]:
        """
        提取所有用户消息和最终结果消息
        
        Returns:
            提取后的消息列表
        """
        # 提取逻辑是：
        #   1. 提取user 以及该user 后面所有的 assistant消息
        #   2. 查看assistant 的list，判断最后一个是不是final answer，如果是，就提取，否则，就提取最后一个 do_subtask_result消息
    
        user_and_final_answer_messages = []
        
        # 先分成 chat_list = [[user,assistant,assistan]]
        chat_list = []
        for msg in self.messages:
            if msg.role == MessageRole.USER.value:
                chat_list.append([msg])
            elif msg.role != MessageRole.USER.value:
                chat_list[-1].append(msg)
        
        # 遍历chat_list，判断最后一个assistant 是否是final answer，如果是，就提取，否则，就提取最后一个 do_subtask_result消息
        for chat in chat_list:
            user_and_final_answer_messages.append(chat[0])
            if len(chat)>1:
                if chat[-1].type == MessageType.FINAL_ANSWER.value:
                    user_and_final_answer_messages.append(chat[-1])
                else:
                    for msg in reversed(chat):
                        if msg.type == MessageType.DO_SUBTASK_RESULT.value:
                            user_and_final_answer_messages.append(msg)
                            break
                if user_and_final_answer_messages[-1].role == MessageRole.USER.value:
                    user_and_final_answer_messages.extend(chat[1:])
        
        # for msg in self.messages:
        #     if msg.role == MessageRole.USER.value:
        #         user_and_final_answer_messages.append(msg)
        #     elif msg.role == MessageRole.ASSISTANT.value and msg.type == MessageType.FINAL_ANSWER.value:
        #         user_and_final_answer_messages.append(msg)
        return user_and_final_answer_messages
    
    def extract_after_last_stage_summary_messages(self) -> List[MessageChunk]:
        
        messages_after_last_user = []
        for msg in self.messages:
            if msg.role == MessageRole.USER.value:
                messages_after_last_user = []
            else:
                messages_after_last_user.append(msg)
        message_after_last_stage_summary = []
        for msg in messages_after_last_user:
            if msg.role == MessageRole.ASSISTANT.value and msg.type == MessageType.STAGE_SUMMARY.value:
                message_after_last_stage_summary = []
            else:
                message_after_last_stage_summary.append(msg)
        return message_after_last_stage_summary

    def extract_after_last_observation_messages(self) -> List[MessageChunk]:
        
        messages_after_last_observation = []
        for msg in self.messages:
            if msg.role == MessageRole.ASSISTANT.value and msg.type == MessageType.OBSERVATION.value:
                messages_after_last_observation = []
            messages_after_last_observation.append(msg)
        return messages_after_last_observation

    def get_after_last_user_messages(self) -> List[MessageChunk]:
        messages_after_last_user = []
        for msg in self.messages:
            if msg.role == MessageRole.USER.value:
                messages_after_last_user = []
            messages_after_last_user.append(msg)
        return messages_after_last_user
    
    def get_all_execution_messages_after_last_user(self) -> List[MessageChunk]:
        messages_after_last_user = self.get_after_last_user_messages()
        messages_after_last_execution = []
        for msg in messages_after_last_user:
            if msg.type in [MessageType.EXECUTION.value,
                            MessageType.DO_SUBTASK.value,
                            MessageType.DO_SUBTASK_RESULT.value,
                            MessageType.TOOL_CALL.value,
                            MessageType.TOOL_CALL_RESULT.value,
                            MessageType.TOOL_RESPONSE ]:
                messages_after_last_execution.append(msg)
        return messages_after_last_execution

    def get_last_planning_message_dict(self) -> Optional[Dict[str, Any]]:
        for msg in reversed(self.messages):
            if msg.role == MessageRole.ASSISTANT.value and msg.type == MessageType.PLANNING.value:
                planning_content = msg.content.replace('Planning: ', '')
                cleaned_content = planning_content.strip('```json\\n').strip('```')
                planning_result = json.loads(cleaned_content)
                subtask_info = {
                    'description': planning_result['next_step']['description'],
                    'expected_output': planning_result['next_step']['expected_output'],
                    'required_tools': planning_result['next_step'].get('required_tools', [])
                }
                return subtask_info
        return None



    def get_latest_observation_message_dict(self) -> Optional[Dict[str, Any]]:
        
        for msg in reversed(self.messages):
            if msg.role == MessageRole.ASSISTANT.value and msg.type == MessageType.OBSERVATION.value:
                obs_content = msg.content.replace('Observation: ', '')
                try:
                    obs_result = json.loads(obs_content)
                except json.JSONDecodeError:
                    logger.error(f"MessageManager: 解析观测消息失败，消息内容: {obs_content}")
                    obs_result = {}
                return obs_result
        return None

    @staticmethod
    def convert_messages_to_dict_for_request(messages: List[MessageChunk]) -> List[Dict[str, Any]]:
        """
        将消息列表转换为字典列表
        
        注意：
        1. 此方法会过滤掉content为None的消息
        2. 此方法会过滤掉tool_call_id为None的消息
        3. 此方法会过滤掉tool_calls为None的消息
        
        Args:
            messages: 消息列表
        
        Returns:
            字典列表
        """
        new_messages = []
        for msg in messages:
            clean_msg = {
                'role': msg.role,
                'content': msg.content,
                'tool_call_id': msg.tool_call_id,
                'tool_calls': msg.tool_calls
            }
            
            # 去掉None值的键
            clean_msg = {k: v for k, v in clean_msg.items() if v is not None}
            new_messages.append(clean_msg)
        
        logger.debug(f"DirectExecutorAgent: 清理后消息数量: {len(new_messages)}")
        return new_messages