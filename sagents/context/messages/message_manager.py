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

import datetime
import time
import re
import uuid
from typing import Dict, List, Optional, Any, Union, Sequence, cast
from copy import deepcopy
from sagents.utils.logger import logger
from sagents.context.messages.context_budget import ContextBudgetManager
from .message import MessageRole, MessageType, MessageChunk

class MessageManager:
    """
    优化版消息管理器
    
    专门管理非system消息，提供完整的消息管理功能。
    不允许保存system消息，所有system消息会被自动过滤。
    """
    
    def __init__(self, session_id: Optional[str] = None, 
                 max_token_limit: int = 8000,
                 compression_threshold: float = 0.7,
                 context_budget_config: Optional[Dict[str, Any]] = None):
        """
        初始化消息管理器
        
        Args:
            session_id: 会话ID
            max_token_limit: 最大token限制
            compression_threshold: 压缩阈值
            context_budget_config: 上下文预算管理器配置，包含以下键：
                - max_model_len: 模型最大token长度，默认 40000
                - history_ratio: 历史消息的比例（0-1之间），默认 0.2 (20%)
                - active_ratio: 活跃消息的比例（0-1之间），默认 0.3 (30%)
                - max_new_message_ratio: 新消息的比例（0-1之间），默认 0.5 (50%)
                - recent_turns: 限制最近的对话轮数，0表示不限制，默认 0
        """
        self.session_id = session_id or f"session_{uuid.uuid4().hex[:8]}"
        self.max_token_limit = max_token_limit
        self.compression_threshold = compression_threshold
        
        # 处理context_budget_config为None的情况
        if context_budget_config is None:
            context_budget_config = {}
        
        self.context_budget_manager = ContextBudgetManager(
            max_model_len=context_budget_config.get('max_model_len', 40000),
            history_ratio=context_budget_config.get('history_ratio', 0.2),     
            active_ratio=context_budget_config.get('active_ratio', 0.3),       
            max_new_message_ratio=context_budget_config.get('max_new_message_ratio', 0.5), 
            recent_turns=context_budget_config.get('recent_turns', 0)        
        )
        
        # 消息存储（只存储非system消息）
        self.messages: List[MessageChunk] = []
        
        # 兼容性：保留pending_chunks属性（现在已不使用）
        self.pending_chunks: List[Any] = []

        self.active_start_index: Optional[int] = None

        # 统计信息
        self.stats: Dict[str, Any] = {
            'total_messages': 0,
            'total_chunks': 0,
            'merged_messages': 0,
            'filtered_messages': 0,
            'compressed_messages': 0,
            'system_messages_rejected': 0,
            'created_at': datetime.datetime.now().isoformat(),
            'last_updated': datetime.datetime.now().isoformat()
        }
        
    
    def update_messages(self, messages: Union[MessageChunk, List[MessageChunk]]) -> None:
        """
        根据message 的id 来更新消息列表
        
        Args:
            messages: 消息列表
        """
        if isinstance(messages, MessageChunk):
            messages = [messages]
        for message in messages:
            for i, old_message in enumerate(self.messages):
                if old_message.message_id == message.message_id:
                    self.messages[i] = message
                    break

    def set_active_start_index(self, index: Optional[int]) -> None:
        """
        设置活跃消息的起始索引
        
        活跃消息指的是固定加入上下文的连续对话，从此索引开始的消息将被视为活跃消息。
        索引之前的消息将被视为历史消息，可用于相似度检索。
        
        Args:
            index: 活跃消息的起始索引，None表示所有消息都是活跃消息
        """  
        self.active_start_index = index
        logger.debug(f"MessageManager: 设置 active_start_index = {index}，"
                   f"历史消息: {index if index else 0}条，"
                   f"活跃消息: {len(self.messages) - (index if index else 0)}条")
    
    def _extract_current_query(self) -> str:
        """提取最新用户查询（私有辅助方法）
        
        Returns:
            最新用户消息的内容，如果没有则返回空字符串
        """
        for msg in reversed(self.messages):
            if msg.role == MessageRole.USER.value:
                return msg.get_content() or ""
        return ""
    
    def prepare_history_split(self, agent_config: Dict[str, Any]) -> Dict[str, Any]:
        """准备历史消息切分
        计算预算、切分消息、设置活跃消息起始索引，并提取最新用户查询
        """
        # 1. 计算预算
        budget_info = self.context_budget_manager.calculate_budget(agent_config)
        
        # 2. 切分消息
        split_result = self.context_budget_manager.split_messages(
            messages=self.messages,
            active_budget=budget_info['active_budget']
        )
        
        # 3. 设置活跃消息起始索引
        # self.set_active_start_index(len(split_result['history_messages']))
        split_index = len(split_result['history_messages'])
        
        # 查找最近两轮对话的起始索引 (User + AI + User + AI + User)
        # 即倒数第3个User消息的索引
        user_indices = [i for i, msg in enumerate(self.messages) if msg.role == MessageRole.USER.value]
        if len(user_indices) >= 3:
            two_rounds_index = user_indices[-3]
        elif len(user_indices) > 0:
            two_rounds_index = user_indices[0]
        else:
            two_rounds_index = 0
            
        # 取最小值，确保至少包含最近两轮对话
        final_index = min(split_index, two_rounds_index)
        self.set_active_start_index(final_index)
        
        # 4. 提取最新用户查询
        current_query = self._extract_current_query()
        
        return {
            'budget_info': budget_info,
            'split_result': split_result,
            'current_query': current_query
        }
    
    

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
                # 过滤system消息
                if message.role == MessageRole.SYSTEM.value:
                    self.stats['system_messages_rejected'] += 1
                    continue
                # 过滤 content 以及 tool_calls 都是空字符串或者None的消息
                if not message.content and not message.tool_calls:
                    self.stats['filtered_messages'] += 1
                    continue
            except Exception:
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
    def calculate_messages_token_length(messages: Sequence[Union[MessageChunk,Dict]]) -> int:
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
            token_length += MessageManager.calculate_str_token_length(message.get_content() or '')
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
        # 处理None或空字符串的情况
        if content is None:
            return 0
            
        token_length = 0.0
        for char in content:
            # 判断是否是中文字符 (CJK统一表意文字)
            if '\u4e00' <= char <= '\u9fff':
                token_length += 0.6
            elif char.isalpha():
                token_length += 0.25
            elif char.isdigit():
                token_length += 0.2
            else:
                token_length += 0.4
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
            if msg is None:
                continue
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

    def extract_all_context_messages(self, recent_turns: int = 0, last_turn_user_only: bool = True, allowed_message_types: Optional[List[str]] = None) -> List[MessageChunk]:
        """
        提取所有有意义的上下文消息，包括用户消息和助手消息，最后一个消息对话，可选是否只提取用户消息，如果只提取用户消息，即是本次请求的上下文，否则带上本次执行已有内容
        
        注意：消息的长度限制由 context_budget_manager 在 prepare_history_split() 中通过 active_start_index 控制
        
        Args:
            recent_turns: 最近的对话轮数，0表示不限制
            last_turn_user_only: 是否只提取最后一个对话轮的用户消息，默认是True
            allowed_message_types: 允许保留的消息类型列表，默认为 None (使用内置默认列表)

        Returns:
            提取后的消息列表
        """
        all_context_messages = []
        chat_list = []

        # 默认允许的消息类型
        if allowed_message_types is None:
            allowed_message_types = [
                MessageType.FINAL_ANSWER.value,
                MessageType.DO_SUBTASK_RESULT.value,
                MessageType.TOOL_CALL.value,
                MessageType.TASK_ANALYSIS.value,
                MessageType.TOOL_CALL_RESULT.value,
                MessageType.SKILL_OBSERVATION.value
            ]

        if self.active_start_index is not None:
            active_messages = self.messages[self.active_start_index:]
        else:
            active_messages = self.messages
            
        for msg in active_messages:
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
        # 合并消息（长度限制由 context_budget_manager 通过 active_start_index 控制）
        for chat in chat_list[::-1]:
            merged_messages = []
            merged_messages.append(chat[0])
            
            for msg in chat[1:]:
                if msg.type in allowed_message_types:
                    merged_messages.append(msg)
            
            all_context_messages.extend(merged_messages[::-1])
        
        result_messages = all_context_messages[::-1]
        # 打印提取结果的统计信息
        total_tokens = MessageManager.calculate_messages_token_length(result_messages)
        logger.info(f"MessageManager: 提取所有上下文消息完成，最近轮数：{recent_turns}，是否只提取最后一个对话轮的用户消息：{last_turn_user_only}，消息数量：{len(result_messages)}，总token长度：{total_tokens}")
        return result_messages
    
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
        messages_after_last_user: List[MessageChunk] = []
        for msg in self.messages:
            if msg.role == MessageRole.USER.value:
                messages_after_last_user = []
            else:
                messages_after_last_user.append(msg)
        message_after_last_stage_summary: List[MessageChunk] = []
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
        
        messages_after_last_observation: List[MessageChunk] = []
        for msg in self.messages:
            if msg.role == MessageRole.ASSISTANT.value and msg.type == MessageType.OBSERVATION.value:
                messages_after_last_observation = []
            messages_after_last_observation.append(msg)
        return messages_after_last_observation

    def get_after_last_user_messages(self) -> List[MessageChunk]:
        messages_after_last_user: List[MessageChunk] = []
        for msg in self.messages:
            if msg.role == MessageRole.USER.value:
                messages_after_last_user = []
            messages_after_last_user.append(msg)
        return messages_after_last_user

    def get_last_observation_message(self) -> Optional[MessageChunk]:
        for msg in self.messages[::-1]:
            if msg.role == MessageRole.ASSISTANT.value and msg.type == MessageType.OBSERVATION.value:
                return msg
        return None
    
    def get_last_user_message(self) -> Optional[MessageChunk]:
        for msg in self.messages[::-1]:
            if msg.role == MessageRole.USER.value and msg.type == MessageType.NORMAL.value:
                return msg
        return None

    def get_all_execution_messages_after_last_user(self,recent_turns:int=0,max_content_length:int=0) -> List[MessageChunk]:
        messages_after_last_user = self.get_after_last_user_messages()
        messages_after_last_execution: List[MessageChunk] = []
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
            new_messages_after_last_execution: List[MessageChunk] = []
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
    def _apply_compression_level(msg: MessageChunk, level: int) -> MessageChunk:
        """
        应用特定等级的压缩 (Level 1 / Level 2)
        
        Args:
            msg: 原始消息
            level: 压缩等级 (1: 轻度, 2: 强力)
            
        Returns:
            MessageChunk: 压缩后的消息副本
        """
        new_msg = deepcopy(msg)
        content = new_msg.content or ""
        
        if level == 1:
            # Level 1: Tool Output 截断 (100+100), Remove Thinking
            if new_msg.role == MessageRole.TOOL.value:
                if len(content) > 200:
                    new_msg.content = content[:100] + f"\n...[Tool output truncated, total {len(content)} chars]...\n" + content[-100:]
            elif new_msg.role == MessageRole.ASSISTANT.value:
                # 移除 <thinking>
                if "<thinking>" in content:
                    new_msg.content = re.sub(r'<thinking>.*?</thinking>', '', content, flags=re.DOTALL).strip()
                
        elif level == 2:
            # Level 2: 强力截断 (100 chars)
            if new_msg.role == MessageRole.TOOL.value:
                if len(content) > 100:
                    new_msg.content = content[:100] + f"...[Tool output omitted, length: {len(content)}]"
            elif new_msg.role == MessageRole.ASSISTANT.value:
                if len(content) > 100:
                    new_msg.content = content[:100] + "...[Content truncated]"
                    
        return new_msg

    @staticmethod
    def _group_messages_indices(messages: List[MessageChunk]) -> List[List[int]]:
        """
        将消息索引分组
        规则：User 消息标志着新组的开始
        Group Structure:
        - Group 0 (Maybe System/Orphan): [0, ..., k]
        - Group 1 (User+): [u1, ..., u2-1]
        """
        groups = []
        if not messages:
            return []
            
        current_group = []
        for i, msg in enumerate(messages):
            if msg.role == MessageRole.USER.value:
                if current_group:
                    groups.append(current_group)
                current_group = [i]
            else:
                current_group.append(i)
        
        if current_group:
            groups.append(current_group)
            
        return groups

    @staticmethod
    def compress_messages(messages: List[MessageChunk], budget_limit: int, time_limit_hours: float = 24.0) -> List[MessageChunk]:
        """
        根据预算限制压缩消息列表（分层压缩策略）。
        
        策略详情：
        Level 0 (保护区):
            - System Message: 永久保留，不做任何处理。
            - Last Group (最后一组): 包含最后一个 User 及其后续所有消息，永久保留。
            - User Message Content: User 消息的内容在 Level 1/2 阶段不被修改（受保护内容），但在 Level 3 阶段可以被整组丢弃。
            - Recent Messages (最近消息): 从后往前计算，累积 Token 占用不超过总预算 20% 的连续消息组，受到完全保护（不压缩、不丢弃）。
            
        Level 0.5 (老化策略):
            - 规则: 超过 time_limit_hours (默认24小时) 的非保护区消息。
            - 动作: 直接应用 Level 2 (强力压缩)，优先释放陈旧消息的空间。
            
        Level 1 (轻度压缩): 
            - Tool Output: 截断保留前 100 字符 + 后 100 字符，中间省略。
            - Assistant: 移除 <thinking>...</thinking> 思考过程，保留核心回复。
            
        Level 2 (强力压缩): 
            - 触发: Level 1 处理后仍超出 Budget。
            - Tool Output: 仅保留前 100 字符 + 占位符 "...[Tool output omitted...]"。
            - Assistant: 仅保留前 100 字符 + 占位符 "...[Content truncated]"。
            
        Level 3 (历史丢弃 - 基于组): 
            - 触发: Level 2 处理后仍超出 Budget。
            - 策略: 按组（User + 后续 Followers）从旧到新进行丢弃。
            - Step A (丢弃 Followers): 保留 Group Head (User)，丢弃该组内所有 Assistant/Tool 消息，插入一条 "...[Execution process omitted]..." 作为占位符。
            - Step B (丢弃 User): 如果 Step A 后仍超标，则丢弃该组的 User 消息（及占位符），整组消失。
            
        Args:
            messages: 原始消息列表。
            budget_limit: 预算限制 (Token 数)。
            time_limit_hours: 老化时间阈值 (小时)，默认 24.0。
            
        Returns:
            List[MessageChunk]: 压缩后的消息列表副本。
        """
        if not messages:
            return []
            
        # 复制消息列表 (浅拷贝列表，元素在修改时 deepcopy)
        working_messages = deepcopy(messages)
        
        # 辅助函数：计算当前 Token
        def current_usage():
            return MessageManager.calculate_messages_token_length(working_messages)
            
        if current_usage() <= budget_limit:
            return working_messages
            
        # --- 1. 分组与保护区识别 ---
        # 将消息按 User 分组，每组包含一个 User 和其后的 Followers (Assistant/Tool)
        groups = MessageManager._group_messages_indices(working_messages)
        
        protected_indices = set()
        protected_group_indices = set()
        
        # 1.1 System Group 保护 (如果第一组以 System 开头)
        if groups and working_messages[groups[0][0]].role == MessageRole.SYSTEM.value:
            protected_group_indices.add(0)
            # System 消息内容受保护
            for idx in groups[0]:
                if working_messages[idx].role == MessageRole.SYSTEM.value:
                    protected_indices.add(idx)
                    
        # 1.2 Last Group 保护 (最后一组始终保留，不参与丢弃)
        if groups:
            last_group_idx = len(groups) - 1
            protected_group_indices.add(last_group_idx)
            # 最后一个非 Tool 消息的内容受保护
            last_msg_idx = len(working_messages) - 1
            if working_messages[last_msg_idx].role != MessageRole.TOOL.value:
                protected_indices.add(last_msg_idx)
                
        # 1.3 User 消息内容保护 (在压缩阶段不截断 User 内容)
        for i, msg in enumerate(working_messages):
            if msg.role == MessageRole.USER.value:
                protected_indices.add(i)

        # 1.4 近期消息保护 (20% Budget)
        # 策略：从后往前遍历 Group，只要累积 Token < 20% Budget，则该 Group 及其消息均受保护
        # 这里的保护意味着：不被 Level 1/2 压缩，也不被 Level 3 丢弃
        recent_token_limit = budget_limit * 0.2
        current_accumulated_tokens = 0
        
        # 倒序遍历 Groups
        for gi in range(len(groups) - 1, -1, -1):
            group_indices = groups[gi]
            # 计算该组 Token
            group_msgs = [working_messages[k] for k in group_indices]
            group_token_count = MessageManager.calculate_messages_token_length(group_msgs)
            
            if current_accumulated_tokens + group_token_count <= recent_token_limit:
                # 标记为保护
                protected_group_indices.add(gi)
                for idx in group_indices:
                    protected_indices.add(idx)
                
                current_accumulated_tokens += group_token_count
            else:
                # 一旦超过，就不再继续向前保护了（保持最近的连续性）
                break

        # --- Level 0.5 & 1 & 2: 消息级压缩 ---
        now = time.time()
        aging_threshold = now - (time_limit_hours * 3600)
        aged_indices = set()
        
        def apply_levels(level_to_apply):
            # 遍历所有消息
            for i, msg in enumerate(working_messages):
                if i in protected_indices: continue
                
                # Level 0.5: 老化策略 (直接应用 Level 2)
                if level_to_apply == 0.5:
                    if msg.timestamp and msg.timestamp < aging_threshold:
                         working_messages[i] = MessageManager._apply_compression_level(msg, 2)
                         aged_indices.add(i)
                # Level 1: 轻度压缩
                elif level_to_apply == 1:
                    if i in aged_indices: continue
                    working_messages[i] = MessageManager._apply_compression_level(working_messages[i], 1)
                # Level 2: 强力压缩
                elif level_to_apply == 2:
                    if i in aged_indices: continue
                    working_messages[i] = MessageManager._apply_compression_level(working_messages[i], 2)
        
        # 应用 Level 0.5 (老化)
        apply_levels(0.5)
        if current_usage() <= budget_limit: return working_messages
        
        # 应用 Level 1 (轻度)
        apply_levels(1)
        if current_usage() <= budget_limit: return working_messages
        
        # 应用 Level 2 (强力)
        apply_levels(2)
        if current_usage() <= budget_limit: return working_messages

        # --- Level 3: 历史丢弃 (基于组) ---
        # 目标: 未在 protected_group_indices 中的组
        droppable_group_indices = [gi for gi in range(len(groups)) if gi not in protected_group_indices]
        
        for gi in droppable_group_indices:
            group_msgs_indices = groups[gi]
            
            # Step A: 丢弃 Followers (保留 User 头)
            followers = group_msgs_indices[1:]
            
            if followers:
                # Replace first follower with placeholder
                first_f = followers[0]
                working_messages[first_f] = MessageChunk(
                    role=MessageRole.ASSISTANT.value,
                    content="...[Execution process omitted]...",
                    type=MessageType.DO_SUBTASK_RESULT.value
                )
                # 清空其余 Followers
                for f_idx in followers[1:]:
                    working_messages[f_idx].content = None
                    working_messages[f_idx].tool_calls = None
                    
                if current_usage() <= budget_limit: break 
            
            # Step B: 丢弃 User 头 (整组消失)
            # 包括 Step A 可能产生的占位符
            head_idx = group_msgs_indices[0]
            working_messages[head_idx].content = None
            working_messages[head_idx].tool_calls = None
            
            # 如果 Step A 产生了占位符，也一并丢弃
            if followers:
                working_messages[followers[0]].content = None
                working_messages[followers[0]].tool_calls = None
                
            if current_usage() <= budget_limit: break

        # 清理已标记为删除的消息 (Content 为 None 的)
        final_messages = [
            m for m in working_messages 
            if m.content is not None or (m.tool_calls and len(m.tool_calls) > 0)
        ]
        
        return final_messages

    def compress_messages_if_needed(self, messages: List[MessageChunk]) -> List[MessageChunk]:
        """
        如果上下文空间不足，则执行压缩；否则返回原列表。
        
        触发条件：
        1. 剩余空间 < 20% * max_model_len
        2. 或 剩余空间 < max_new_tokens
        
        Args:
            messages: 原始消息列表
            
        Returns:
            List[MessageChunk]: 压缩后的消息列表或原列表
        """
        # 计算预算 (使用缓存的预算)
        budget_info = self.context_budget_manager.calculate_budget()
        max_new_tokens = budget_info.get('max_new_tokens', 20000)
        max_model_len = budget_info.get('max_model_len', 40000)

        # 计算当前消息长度
        current_tokens = MessageManager.calculate_messages_token_length(cast(List[Union[MessageChunk, Dict[str, Any]]], messages))
        
        # 阈值判断
        remaining_tokens = max_model_len - current_tokens
        
        # 条件：剩余 < 20% 总容量 OR 剩余 < max_new_tokens
        threshold_ratio = int(max_model_len * 0.2)
        
        if remaining_tokens < threshold_ratio or remaining_tokens < max_new_tokens:
            logger.info(f"MessageManager: 上下文空间不足 (剩余 {remaining_tokens}), 触发压缩...")
            
            # 执行压缩
            compressed_messages = MessageManager.compress_messages(
                messages, 
                int(max_new_tokens * 0.3)
            )
            
            # 记录压缩效果
            new_tokens = MessageManager.calculate_messages_token_length(cast(List[Union[MessageChunk, Dict[str, Any]]], compressed_messages))
            logger.info(f"MessageManager: 临时压缩完成，Token从 {current_tokens} 降至 {new_tokens}")
            return compressed_messages
            
        return messages

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
            # 去掉empty消息
            if msg.type == MessageType.EMPTY.value:
                logger.debug(f"DirectExecutorAgent: 过滤空消息: {msg}")
                continue
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