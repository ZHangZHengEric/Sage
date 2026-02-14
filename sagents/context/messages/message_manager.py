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
        
        logger.info(f"MessageManager: 初始化完成，会话ID: {self.session_id}")
    
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
        logger.info(f"MessageManager: 设置 active_start_index = {index}，"
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
        logger.info(f"MessageManager: 提取所有上下文消息，最近轮数：{recent_turns}，是否只提取最后一个对话轮的用户消息：{last_turn_user_only}")
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
        logger.info(f"MessageManager: 提取完成，消息数量：{len(result_messages)}，总token长度：{total_tokens}")
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
    def compress_messages(messages: List[MessageChunk], budget_limit: int) -> List[MessageChunk]:
        """
        根据预算信息压缩消息列表 (Zone A/B/C 策略)
        
        策略：
        Zone A (Anchor): System Message 到 Last User Message -> 永久保留
        Zone C (Active): 最近的N条消息 -> 保留 max_new_tokens 的 20%
        Zone B (Middle): 中间过程消息 -> 压缩至 max_new_tokens 的 10%
        
        触发条件：通常在外部判断，但此方法会强制执行压缩以符合目标
        
        Args:
            messages: 原始消息列表
            budget_limit: 预算限制 (active_budget 或 max_new_tokens)
            
        Returns:
            List[MessageChunk]: 压缩后的消息列表副本
        """
        if not messages:
            return []
            
        # 使用传入的 limit 作为压缩基准
        active_budget = budget_limit
        
        # 调整预算分配比例，基于 active_budget
        zone_c_budget = int(active_budget * 0.7) # 最近消息保留 70%
        zone_b_budget = int(active_budget * 0.2) # 中间消息保留 20%
        
        # --- 1. 识别 Zone A (Anchor) ---
        # 规则：System Message 和 Last User Message 永久保留
        # 中间的消息进入候选区 (Zone B/C)
        zone_a: List[MessageChunk] = []
        remain_messages: List[MessageChunk] = []
        
        last_user_idx = -1
        for i in range(len(messages) - 1, -1, -1):
            if messages[i].role == MessageRole.USER.value:
                last_user_idx = i
                break
        
        if last_user_idx != -1:
            # 1. System Message (如果存在且在开头)
            start_idx = 0
            if messages and messages[0].role == MessageRole.SYSTEM.value:
                zone_a.append(messages[0])
                start_idx = 1
            
            # 2. 中间消息 (System之后，Last User之前)
            if last_user_idx > start_idx:
                remain_messages.extend(messages[start_idx:last_user_idx])
            
            # 3. Last User Message (加入 Zone A)
            zone_a.append(messages[last_user_idx])
            
            # 4. Last User 之后的消息 (加入 remain，作为 Zone C 的主要来源)
            remain_messages.extend(messages[last_user_idx + 1:])
            
        else:
            # 如果没找到 User Message，保留 System Message (如果有)
            if messages and messages[0].role == MessageRole.SYSTEM.value:
                zone_a = [messages[0]]
                remain_messages = list(messages[1:])
            else:
                zone_a = []
                remain_messages = list(messages)
        
        # 如果剩余消息很少，直接返回
        if not remain_messages:
            return list(messages) # Shallow copy
            
        # --- 2. 识别 Zone C (Active) ---
        # 从后往前扫描，直到 token 超过 zone_c_budget
        zone_c: List[MessageChunk] = []
        current_c_tokens = 0
        split_idx = len(remain_messages) # 默认全在 Zone C (如果没有 Zone B)
        
        for i in range(len(remain_messages) - 1, -1, -1):
            msg = remain_messages[i]
            msg_tokens = MessageManager.calculate_str_token_length(msg.content or '')
            if current_c_tokens + msg_tokens > zone_c_budget and zone_c:
                # 如果加上这条就超了，且 Zone C 已经有内容了，就停止
                # 保证至少有一条？
                break
            current_c_tokens += msg_tokens
            split_idx = i
            # 倒序添加，最后再反转
            zone_c.append(msg)
            
        zone_c.reverse() # 恢复顺序
        
        # --- 3. 识别 Zone B (Middle) ---
        zone_b_source = remain_messages[:split_idx]
        
        if not zone_b_source:
            # 没有中间层，不需要压缩
            return zone_a + zone_c
            
        # --- 4. 压缩 Zone B ---
        # 目标：zone_b_budget
        # 策略 1: 坍缩 Tool Output
        zone_b_compressed: List[MessageChunk] = []
        
        # 预计算 Zone B Token
        current_b_tokens = 0
        for msg in zone_b_source:
            current_b_tokens += MessageManager.calculate_str_token_length(msg.content or '')
            
        # 如果已经满足预算，直接返回
        if current_b_tokens <= zone_b_budget:
            return zone_a + zone_b_source + zone_c
            
        # 开始压缩：坍缩 Tool Output
        # 我们创建一个新的列表，包含修改后的消息
        # 必须使用 deepcopy 或创建新实例，以免修改原始引用
        
        for msg in zone_b_source:
            new_msg = deepcopy(msg)
            if new_msg.role == MessageRole.TOOL.value:
                 # 坍缩 Tool Output
                original_len = len(new_msg.content or '')
                if original_len > 100: # 只有长的才压缩
                    new_msg.content = f"[System: Tool output hidden to save context. Original length: {original_len} chars. Action was executed.]"
            zone_b_compressed.append(new_msg)
            
        # 重新计算 Token
        current_b_tokens = 0
        for msg in zone_b_compressed:
            current_b_tokens += MessageManager.calculate_str_token_length(msg.content or '')
            
        # 策略 2: 如果还不够，截断 Assistant Thought
        if current_b_tokens > zone_b_budget:
            for msg in zone_b_compressed:
                if msg.role == MessageRole.ASSISTANT.value and msg.content:
                    if len(msg.content) > 200:
                        msg.content = msg.content[:200] + "... [Thought truncated]"
            
            # 重新计算
            current_b_tokens = 0
            for msg in zone_b_compressed:
                current_b_tokens += MessageManager.calculate_str_token_length(msg.content or '')

        # 策略 3: 如果还不够，丢弃旧消息 (History Drop)
        # 从头开始丢弃，直到满足预算
        if current_b_tokens > zone_b_budget:
            final_zone_b: List[MessageChunk] = []
            dropped_count = 0
            
            # 逆向构建，优先保留 Zone B 后部的消息（靠近 Active Zone）
            temp_tokens = 0
            temp_list = []
            for msg in reversed(zone_b_compressed):
                msg_tokens = MessageManager.calculate_str_token_length(msg.content or '')
                if temp_tokens + msg_tokens > zone_b_budget:
                    dropped_count += 1
                    continue
                temp_tokens += msg_tokens
                temp_list.append(msg)
            
            final_zone_b = temp_list[::-1] # 反转回来
            
            if dropped_count > 0:
                # 插入占位符
                placeholder = MessageChunk(
                    role=MessageRole.SYSTEM.value,
                    content=f"[System: Previous {dropped_count} steps in the middle execution process have been omitted to save context window. Focus on the latest steps in Active Zone.]",
                    type=MessageType.NORMAL.value
                )
                final_zone_b.insert(0, placeholder)
            
            zone_b_compressed = final_zone_b

        return zone_a + zone_b_compressed + zone_c

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
                max_new_tokens
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
            if msg.message_type == MessageType.EMPTY.value:
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