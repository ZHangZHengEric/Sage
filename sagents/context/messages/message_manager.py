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
import traceback
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
    def calculate_messages_token_length(messages: List[Union[MessageChunk,Dict]]) -> int:
        """
        计算消息列表的token长度, 只计算content字段
        
        Args:
            messages: 消息列表
            
        Returns:
            int: 消息列表的token长度
        """
        token_length = 0
        for message in messages:
            if isinstance(message, dict):
                message = MessageChunk(**message)
            token_length += MessageManager.calculate_str_token_length(message.content or '')
        return token_length

    @staticmethod
    def calculate_str_token_length(content: str) -> int:
        """
        计算字符串的token长度, 只计算content字段。
        一个中文等于0.6 个token，
        一个英文等于0.25个token，
        一个数字等于0.2 token
        其他符号等于0.4 token
        
        Args:
            content: 字符串内容
            
        Returns:
            int: 字符串的token长度
        """
        token_length = 0
        for char in content:
            if char.isalpha():
                token_length += 0.25
            elif char.isdigit():
                token_length += 0.2
            else:
                token_length += 0.6
        return int(token_length)

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
                    messages_str_list.append(f"AI: {msg.content}")
                elif msg.tool_calls is not None:
                    messages_str_list.append(f"AI: Tool calls: {msg.tool_calls}")
            elif msg.role == 'tool':
                messages_str_list.append(f"Tool: {msg.content}")
        
        result = "\n".join(messages_str_list) or "None"
        logger.info(f"AgentBase: 转换后字符串长度: {MessageManager.calculate_str_token_length(result)}")
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
        chat_list = []
        for msg in self.messages:
            if msg.role == MessageRole.USER.value and msg.type == MessageType.NORMAL.value:
                chat_list.append([msg])
            elif msg.role != MessageRole.USER.value:
                chat_list[-1].append(msg)
        # 过滤最近轮数
        if recent_turns > 0:
            chat_list = chat_list[-recent_turns:]
        # 过滤消息类型
        if accept_message_type:
            chat_list = [chat for chat in chat_list if chat[0].type in accept_message_type]

        # 上下文长度 计算 每个 chatlist 的item 的长度。倒序计算，直到超过上下文长度限制。
        accept_chat_list = []
        for chat in chat_list[::-1]:
            context_length = sum([MessageManager.calculate_str_token_length(msg.content or '') for msg in chat])
            if context_length <= context_length_limited:
                accept_chat_list.append(chat)
                context_length_limited -= context_length
            else:
                break
        accept_chat_list = accept_chat_list[::-1]
        accept_messages = []
        for chat in accept_chat_list:
            accept_messages.extend(chat)
        
        filtered_messages = deepcopy(accept_messages)
        return filtered_messages

    def extract_all_context_messages(self,recent_turns:int=0,max_length = 20000,last_turn_user_only:bool=True) -> List[MessageChunk]:
        """
        提取所有有意义的上下文消息，包括用户消息和助手消息，最后一个消息对话，可选是否只提取用户消息，如果只提取用户消息，即是本次请求的上下文，否则带上本次执行已有内容
        
        Args:
            recent_turns: 最近的对话轮数，0表示不限制
            max_length: 提取的最大长度，0表示不限制
            last_turn_user_only: 是否只提取最后一个对话轮的用户消息，默认是True

        Returns:
            提取后的消息列表
        """
        logger.info(f"MessageManager: 提取所有上下文消息，最近轮数：{recent_turns}，最大长度：{max_length}，是否只提取最后一个对话轮的用户消息：{last_turn_user_only}")
        all_context_messages = []
        chat_list = []
        for msg in self.messages:
            if msg.role == MessageRole.USER.value and msg.type == MessageType.NORMAL.value:
                chat_list.append([msg])
            elif msg.role != MessageRole.USER.value:
                if len(chat_list) > 0:
                    chat_list[-1].append(msg)
                else:
                    chat_list.append([msg])
        if recent_turns > 0:
            chat_list = chat_list[-recent_turns:]

        # 最后一个对话，只提取用户消息
        if last_turn_user_only and len(chat_list) > 0:
            last_chat = chat_list[-1]
            all_context_messages.append(last_chat[0])
            chat_list = chat_list[:-1]
        # 合并消息
        merged_length = 0
        for chat in chat_list[::-1]:
            merged_messages = []

            merged_messages.append(chat[0])
            merged_length += MessageManager.calculate_str_token_length(chat[0].content or '')
            
            if merged_length > max_length:
                logger.info(f"MessageManager: 合并消息长度超过最大长度，当前长度：{merged_length}，最大长度：{max_length}")
                break
            for msg in chat[1:]:
                if msg.type in [MessageType.FINAL_ANSWER.value,
                                MessageType.DO_SUBTASK_RESULT.value,
                                MessageType.TOOL_CALL.value,
                                MessageType.TASK_ANALYSIS.value,
                                MessageType.TOOL_CALL_RESULT.value]:
                    merged_messages.append(msg)
                    merged_length += MessageManager.calculate_str_token_length(msg.content or '')
            if merged_length > max_length:
                logger.info(f"MessageManager: 合并消息长度超过最大长度，当前长度：{merged_length}，最大长度：{max_length}")
                break
            logger.info(f"MessageManager: 合并消息长度，当前长度：{merged_length}，最大长度：{max_length}")
            all_context_messages.extend(merged_messages[::-1])
        return all_context_messages[::-1]
    
    # def extract_all_user_and_final_answer_messages(self,recent_turns:int=0) -> List[MessageChunk]:
    #     """
    #     提取最近的用户消息和最终结果消息
        
    #     Args:
    #         recent_turns: 最近的对话轮数，0表示不限制
    #         max_length: 提取的最大长度，0表示不限制

    #     Returns:
    #         提取后的消息列表
    #     """
    #     # 提取逻辑是：
    #     #   1. 提取user 以及该user 后面所有的 assistant消息
    #     #   2. 查看assistant 的list，判断最后一个是不是final answer，如果是，就提取，否则，就提取最后一个 do_subtask_result消息
    
    #     user_and_final_answer_messages = []
        
    #     # 先分成 chat_list = [[user,assistant,assistan]]
    #     chat_list = []
    #     for msg in self.messages:
    #         if msg.role == MessageRole.USER.value and msg.type == MessageType.NORMAL.value:
    #             chat_list.append([msg])
    #         elif msg.role != MessageRole.USER.value:
    #             chat_list[-1].append(msg)
        
    #     # 遍历chat_list，判断最后一个assistant 是否是final answer，如果是，就提取，否则，就提取最后一个 do_subtask_result消息
    #     if recent_turns > 0:
    #         chat_list = chat_list[-recent_turns:]
        
    #     for chat in chat_list:
    #         user_and_final_answer_messages.append(chat[0])

    #         # 如果chat[1：]  有 FINAL_ANSWER，则只保留一个FINAL_ANSWER messages。
    #         # 否则，将所有的type 为 do_subtask_result tool_call tool_call_result 都加入进来
    #         if len(chat)>1:
    #             if chat[-1].type == MessageType.FINAL_ANSWER.value:
    #                 user_and_final_answer_messages.append(chat[-1])
    #             else:
    #                 for msg in chat[1:]:
    #                     if msg.type in [MessageType.DO_SUBTASK_RESULT.value,
    #                                     MessageType.TOOL_CALL.value,
    #                                     MessageType.TOOL_CALL_RESULT.value]:
    #                         user_and_final_answer_messages.append(msg)
    #     return user_and_final_answer_messages
    
    def extract_after_last_stage_summary_messages(self,max_length:int=0) -> List[MessageChunk]:
        """
        提取最后一个阶段的总结消息之后的所有消息
        
        Args:
            max_length: 提取的最大长度，0表示不限制

        Returns:
            提取后的消息列表
        """
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
        if max_length > 0:
            # 截取从后往前的 n 条消息，n条消息的content长度 < max_content_length ,但是n+1 消息，content长度 > max_content_length
            merged_length = 0
            new_message_after_last_stage_summary = []
            for msg in message_after_last_stage_summary[::-1]:
                merged_length += MessageManager.calculate_str_token_length(msg.content or '')
                if merged_length > max_length:
                    break
                new_message_after_last_stage_summary.append(msg)
            if len(new_message_after_last_stage_summary) > 0:
                if new_message_after_last_stage_summary[-1].type == MessageType.TOOL_CALL_RESULT.value:
                    new_message_after_last_stage_summary = new_message_after_last_stage_summary[:-1]
            message_after_last_stage_summary = new_message_after_last_stage_summary[::-1]
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

    def get_last_observation_message(self) -> MessageChunk:
        for msg in self.messages[::-1]:
            if msg.role == MessageRole.ASSISTANT.value and msg.type == MessageType.OBSERVATION.value:
                return msg
        return None
    
    def get_last_user_message(self) -> MessageChunk:
        for msg in self.messages[::-1]:
            if msg.role == MessageRole.USER.value and msg.type == MessageType.NORMAL.value:
                return msg
        return None

    def get_all_execution_messages_after_last_user(self,recent_turns:int=0,max_content_length:int=0) -> List[MessageChunk]:
        messages_after_last_user = self.get_after_last_user_messages()
        messages_after_last_execution = []
        for msg in messages_after_last_user:
            if msg.type in [MessageType.EXECUTION.value,
                            MessageType.DO_SUBTASK_RESULT.value,
                            MessageType.TOOL_CALL.value,
                            MessageType.TOOL_CALL_RESULT.value]:
                messages_after_last_execution.append(msg)
        if recent_turns > 0:
            messages_after_last_execution = messages_after_last_execution[-recent_turns:]
        
        if max_content_length >0 :
            # 截取从后往前的 n条消息，n条消息的content长度 < max_content_length ,但是n+1 消息，content长度 > max_content_length
            # 则只保留 n条消息
            new_messages_after_last_execution = []
            total_length = 0
            for msg in messages_after_last_execution[::-1]:
                if msg.content:
                    total_length += MessageManager.calculate_str_token_length(msg.content)
                if total_length > max_content_length:
                    break
                new_messages_after_last_execution.append(msg)
            
            messages_after_last_execution = new_messages_after_last_execution[::-1]

        # 第一条不能是role 为tool 的消息
        if messages_after_last_execution and messages_after_last_execution[0].role == MessageRole.TOOL.value:
            messages_after_last_execution = messages_after_last_execution[1:]

        return messages_after_last_execution

    def get_all_messages_content_length(self):
        total_length = 0
        for msg in self.messages:
            if msg.content:
                total_length += MessageManager.calculate_str_token_length(msg.content)
        return total_length

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