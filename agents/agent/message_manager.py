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
import uuid
from typing import Dict, List, Optional, Any, Set, Union
from enum import Enum
from copy import deepcopy
from agents.utils.logger import logger


class MessageRole(Enum):
    """消息角色枚举"""
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"  # 仅用于识别，不会被存储
    TOOL = "tool"


class MessageType(Enum):
    """消息类型枚举"""
    NORMAL = "normal"
    TASK_ANALYSIS = "task_analysis"
    TASK_DECOMPOSITION = "task_decomposition"
    PLANNING = "planning"
    EXECUTION = "execution"
    OBSERVATION = "observation"
    SUMMARY = "summary"
    FINAL_ANSWER = "final_answer"
    TOOL_CALL = "tool_call"
    TOOL_RESPONSE = "tool_response"
    ERROR = "error"
    CHUNK = "chunk"  # 新增：用于标识消息块


class MessageManager:
    """
    优化版消息管理器
    
    专门管理非system消息，提供完整的消息管理功能。
    不允许保存system消息，所有system消息会被自动过滤。
    """
    
    def __init__(self, session_id: Optional[str] = None, 
                 max_token_limit: int = 8000,
                 compression_threshold: float = 0.7,
                 auto_merge_chunks: bool = True):
        """
        初始化消息管理器
        
        Args:
            session_id: 会话ID
            max_token_limit: 最大token限制
            compression_threshold: 压缩阈值
            auto_merge_chunks: 是否自动合并消息块
        """
        self.session_id = session_id or f"session_{uuid.uuid4().hex[:8]}"
        self.max_token_limit = max_token_limit
        self.compression_threshold = compression_threshold
        self.auto_merge_chunks = auto_merge_chunks
        
        # 消息存储（只存储非system消息）
        self.messages: List[Dict[str, Any]] = []
        
        # 兼容性：保留pending_chunks属性（现在已不使用）
        self.pending_chunks = {}
        
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
    
    def add_messages(self, messages: Union[Dict[str, Any], List[Dict[str, Any]]], agent_name: Optional[str] = None) -> bool:
        """
        添加消息（支持单个消息或消息列表，直接合并chunk到existing message）
        
        Args:
            messages: 消息数据（单个消息字典或消息列表）
            agent_name: 添加消息的agent名称，用于追踪消息来源
            
        Returns:
            bool: 是否添加成功
        """
        # 统一处理为列表
        if isinstance(messages, dict):
            messages = [messages]
        
        success_count = 0
        
        for message in messages:
            # 过滤system消息
            if self._is_system_message(message):
                self.stats['system_messages_rejected'] += 1
                logger.debug(f"MessageManager: 拒绝system消息")
                continue
            
            # 获取或生成message_id
            message_id = message.get('message_id')
            
            if message_id:
                # 有message_id，查找是否已存在相同message_id的消息
                existing_message = None
                for i, existing_msg in enumerate(self.messages):
                    if existing_msg.get('message_id') == message_id:
                        existing_message = existing_msg
                        break
                
                if existing_message:
                    # 找到现有消息，合并内容
                    if 'content' in message:
                        existing_message['content'] = existing_message.get('content', '') + message['content']
                    if 'show_content' in message:
                        existing_message['show_content'] = existing_message.get('show_content', '') + message['show_content']
                    
                    # 更新其他字段（除了content、message_id）
                    for key, value in message.items():
                        if key not in ['content', 'show_content', 'message_id']:
                            existing_message[key] = value
                    
                    # 如果提供了agent_name，更新或添加agent信息
                    if agent_name:
                        existing_message['agent_name'] = agent_name
                    
                    existing_message['updated_at'] = datetime.datetime.now().isoformat()
                    # logger.debug(f"MessageManager: 合并chunk到现有消息 {message_id[:8]}... (Agent: {agent_name})")
                    
                else:
                    # 没有找到现有消息，创建新消息
                    msg_data = deepcopy(message)
                    msg_data['timestamp'] = msg_data.get('timestamp') or datetime.datetime.now().isoformat()
                    msg_data['is_chunk'] = False
                    
                    # 如果提供了agent_name，添加到消息中
                    if agent_name:
                        msg_data['agent_name'] = agent_name
                    
                    self.messages.append(msg_data)
                    self.stats['total_messages'] += 1
                    logger.debug(f"MessageManager: 创建新消息 {message_id[:8]}... (Agent: {agent_name})")
                
                self.stats['total_chunks'] += 1
                
            else:
                # 没有message_id，作为完整独立消息处理
                msg_data = deepcopy(message)
                msg_data['message_id'] = str(uuid.uuid4())
                msg_data['timestamp'] = msg_data.get('timestamp') or datetime.datetime.now().isoformat()
                msg_data['is_chunk'] = False
                
                # 如果提供了agent_name，添加到消息中
                if agent_name:
                    msg_data['agent_name'] = agent_name
                
                self.messages.append(msg_data)
                self.stats['total_messages'] += 1
                
                logger.debug(f"MessageManager: 添加独立消息，ID: {msg_data['message_id'][:8]}... (Agent: {agent_name})")
            
            success_count += 1
            self.stats['last_updated'] = datetime.datetime.now().isoformat()
        
        return success_count > 0
    
    def merge(self, chunks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        合并流式消息块，将具有相同message_id的块合并 (参考agent_base.py实现)
        
        Args:
            chunks: 流式消息块列表
            
        Returns:
            List[Dict[str, Any]]: 合并后的消息列表
        """
        if not chunks:
            return []
        
        merged_map = {}
        result = []
        
        for chunk in chunks:
            # 过滤system消息
            if self._is_system_message(chunk):
                self.stats['system_messages_rejected'] += 1
                continue
                
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
                # 更新其他字段
                for key, value in chunk.items():
                    if key not in ['content', 'show_content', 'message_id', 'chunk_id']:
                        existing[key] = value
            else:
                chunk_copy = chunk.copy()
                chunk_copy['is_chunk'] = False  # 标记为已合并
                merged_map[message_id] = chunk_copy
                result.append(merged_map[message_id])
        
        logger.debug(f"MessageManager: 合并流式chunks完成，从 {len(chunks)} 合并为 {len(result)}")
        return result
    
    def merge_message_chunks(self, message_id: str) -> Optional[Dict[str, Any]]:
        """
        查找指定消息ID的消息（兼容旧API）
        
        Args:
            message_id: 消息ID
            
        Returns:
            Optional[Dict[str, Any]]: 找到的消息，未找到时返回None
        """
        return self.get_message_by_id(message_id)

    def merge_all_pending_chunks(self) -> List[Dict[str, Any]]:
        """
        获取所有消息（兼容旧API，现在不需要合并）
        
        Returns:
            List[Dict[str, Any]]: 所有消息列表
        """
        logger.info(f"MessageManager: 返回所有消息，共 {len(self.messages)} 个消息")
        return deepcopy(self.messages)
    
    def get_all_messages(self, include_pending_chunks: bool = False) -> List[Dict[str, Any]]:
        """
        获取所有消息
        
        Args:
            include_pending_chunks: 是否包含待合并的chunks（向后兼容参数，现在无效）
            
        Returns:
            List[Dict[str, Any]]: 所有消息列表
        """
        result = deepcopy(self.messages)
        
        # 按时间戳排序
        result.sort(key=lambda x: x.get('timestamp', ''))
        
        return result
    
    def filter_messages_for_agent(self, agent_name: str) -> List[Dict[str, Any]]:
        """
        为特定Agent过滤和优化消息
        
        Args:
            agent_name: Agent名称
            
        Returns:
            List[Dict[str, Any]]: 优化后的消息列表
        """
        logger.debug(f"MessageManager: 为 {agent_name} 过滤消息，当前消息数量: {len(self.messages)}")
        
        # 根据Agent类型采用不同的过滤策略
        if agent_name == "TaskDecomposeAgent":
            return self._filter_for_task_decompose_agent()
        elif agent_name == "PlanningAgent":
            return self._filter_for_planning_agent()
        elif agent_name == "ExecutorAgent":
            return self._filter_for_executor_agent()
        elif agent_name == "ObservationAgent":
            return self._filter_for_observation_agent()
        elif agent_name == "TaskSummaryAgent":
            return self._filter_for_task_summary_agent()
        elif agent_name == "TaskAnalysisAgent":
            return self._filter_for_task_analysis_agent()
        else:
            # 默认策略
            return self._filter_default_strategy()
    
    def _filter_for_task_decompose_agent(self) -> List[Dict[str, Any]]:
        """TaskDecomposeAgent的消息过滤策略"""
        # 临时取消过滤，返回所有消息用于调试
        logger.debug(f"MessageManager: TaskDecomposeAgent临时取消过滤，返回所有 {len(self.messages)} 条消息")
        return self.messages.copy()
    
    def _filter_for_planning_agent(self) -> List[Dict[str, Any]]:
        """PlanningAgent的消息过滤策略"""
        # 临时取消过滤，返回所有消息用于调试
        logger.debug(f"MessageManager: PlanningAgent临时取消过滤，返回所有 {len(self.messages)} 条消息")
        return self.messages.copy()
    
    def _filter_for_executor_agent(self) -> List[Dict[str, Any]]:
        """ExecutorAgent的消息过滤策略"""
        # 临时取消过滤，返回所有消息用于调试
        logger.debug(f"MessageManager: ExecutorAgent临时取消过滤，返回所有 {len(self.messages)} 条消息")
        return self.messages.copy()
    
    def _filter_for_observation_agent(self) -> List[Dict[str, Any]]:
        """ObservationAgent的消息过滤策略"""
        # 临时取消过滤，返回所有消息用于调试
        logger.debug(f"MessageManager: ObservationAgent临时取消过滤，返回所有 {len(self.messages)} 条消息")
        return self.messages.copy()
    
    def _filter_for_task_summary_agent(self) -> List[Dict[str, Any]]:
        """TaskSummaryAgent的消息过滤策"""
        # 临时取消过滤，返回所有消息用于调试
        logger.debug(f"MessageManager: TaskSummaryAgent临时取消过滤，返回所有 {len(self.messages)} 条消息")
        return self.messages.copy()
    
    def _filter_for_task_analysis_agent(self) -> List[Dict[str, Any]]:
        """TaskAnalysisAgent的消息过滤策略
只保留message 中的user 以及 type 为 final_answer 的消息
        """
        filtered_messages = []
        for msg in self.messages:
            if msg.get('role') == 'user' or msg.get('type') == 'final_answer':
                filtered_messages.append(msg)
        logger.info(f"MessageManager: TaskAnalysisAgent过滤完成，保留 {len(filtered_messages)} 条消息")
        return filtered_messages
    
    def _filter_default_strategy(self) -> List[Dict[str, Any]]:
        """默认消息过滤策略"""
        return self.compress_messages(preserve_latest=10)

    def filter_messages(self, 
                       role_filter: Optional[List[str]] = None,
                       type_filter: Optional[List[str]] = None,
                       time_range: Optional[tuple] = None,
                       content_filter: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        过滤消息
        
        Args:
            role_filter: 角色过滤器
            type_filter: 类型过滤器
            time_range: 时间范围过滤器 (start_time, end_time)
            content_filter: 内容关键词过滤器
            
        Returns:
            List[Dict[str, Any]]: 过滤后的消息列表
        """
        filtered_messages = []
        
        for msg in self.messages:
            # 角色过滤
            if role_filter and msg.get('role') not in role_filter:
                continue
            
            # 类型过滤
            if type_filter and msg.get('type') not in type_filter:
                continue
            
            # 时间过滤
            if time_range:
                msg_time = msg.get('timestamp', '')
                if msg_time < time_range[0] or msg_time > time_range[1]:
                    continue
            
            # 内容过滤
            if content_filter:
                content = msg.get('content', '')
                if content_filter.lower() not in content.lower():
                    continue
            
            filtered_messages.append(msg)
        
        filtered_count = len(self.messages) - len(filtered_messages)
        self.stats['filtered_messages'] += filtered_count
        logger.debug(f"MessageManager: 过滤完成，从 {len(self.messages)} 减少到 {len(filtered_messages)}")
        
        return filtered_messages
    
    def compress_messages(self, 
                         target_count: Optional[int] = None,
                         preserve_latest: int = 5,
                         preserve_important: bool = True) -> List[Dict[str, Any]]:
        """
        压缩消息
        
        Args:
            target_count: 目标消息数量
            preserve_latest: 保留最新消息数量
            preserve_important: 是否保留重要消息
            
        Returns:
            List[Dict[str, Any]]: 压缩后的消息列表
        """
        if not target_count:
            target_count = max(10, int(len(self.messages) * self.compression_threshold))
        
        if len(self.messages) <= target_count:
            return self.messages.copy()
        
        important_messages = []
        regular_messages = []
        
        # 分类消息
        for msg in self.messages:
            if preserve_important and self._is_important_message(msg):
                important_messages.append(msg)
            else:
                regular_messages.append(msg)
        
        # 保留最新的消息
        latest_messages = self.messages[-preserve_latest:] if preserve_latest > 0 else []
        
        # 计算可用空间
        reserved_count = len(important_messages) + len(latest_messages)
        available_count = max(0, target_count - reserved_count)
        
        # 从普通消息中选择
        selected_regular = []
        if available_count > 0 and regular_messages:
            # 均匀采样
            step = max(1, len(regular_messages) // available_count)
            selected_regular = regular_messages[::step][:available_count]
        
        # 合并并去重
        compressed = important_messages + selected_regular + latest_messages
        seen_ids = set()
        final_compressed = []
        
        for msg in compressed:
            msg_id = msg.get('message_id')
            if msg_id not in seen_ids:
                seen_ids.add(msg_id)
                final_compressed.append(msg)
        
        # 按时间戳排序
        final_compressed.sort(key=lambda x: x.get('timestamp', ''))
        
        compressed_count = len(self.messages) - len(final_compressed)
        self.stats['compressed_messages'] += compressed_count
        logger.info(f"MessageManager: 压缩完成，从 {len(self.messages)} 压缩到 {len(final_compressed)}")
        
        return final_compressed
    
    def apply_token_limit(self, messages: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
        """
        应用token限制
        
        Args:
            messages: 要处理的消息列表，None时使用self.messages
            
        Returns:
            List[Dict[str, Any]]: 符合token限制的消息列表
        """
        if messages is None:
            messages = self.messages
        
        # 简单的token估算（中文字符约等于1个token）
        total_tokens = 0
        result = []
        
        # 从最新消息开始逆向添加
        for msg in reversed(messages):
            content = str(msg.get('content', ''))
            msg_tokens = len(content)
            
            if total_tokens + msg_tokens <= self.max_token_limit:
                result.insert(0, msg)
                total_tokens += msg_tokens
            else:
                # 如果是重要消息，尝试截断内容
                if self._is_important_message(msg):
                    remaining_tokens = self.max_token_limit - total_tokens
                    if remaining_tokens > 50:  # 至少保留50个token
                        truncated_msg = deepcopy(msg)
                        truncated_msg['content'] = content[:remaining_tokens] + "..."
                        result.insert(0, truncated_msg)
                        break
                else:
                    break
        
        logger.debug(f"MessageManager: Token限制应用完成，保留 {len(result)} 个消息，总计约 {total_tokens} tokens")
        
        return result
    
    def clear_messages(self, keep_latest: int = 0) -> int:
        """
        清空消息
        
        Args:
            keep_latest: 保留最新消息数量
            
        Returns:
            int: 清空的消息数量
        """
        original_count = len(self.messages)
        
        if keep_latest > 0:
            self.messages = self.messages[-keep_latest:]
        else:
            self.messages = []
        
        # 清空pending chunks
        self.pending_chunks = {}
        
        cleared_count = original_count - len(self.messages)
        self.stats['last_updated'] = datetime.datetime.now().isoformat()
        
        logger.info(f"MessageManager: 清空 {cleared_count} 个消息，保留 {len(self.messages)} 个")
        
        return cleared_count
    
    def get_stats(self) -> Dict[str, Any]:
        """
        获取统计信息
        
        Returns:
            Dict[str, Any]: 统计信息
        """
        current_stats = deepcopy(self.stats)
        current_stats.update({
            'session_id': self.session_id,
            'current_message_count': len(self.messages),
            'max_token_limit': self.max_token_limit,
            'compression_threshold': self.compression_threshold,
            'auto_merge_chunks': self.auto_merge_chunks
        })
        
        return current_stats
    
    def get_message_by_id(self, message_id: str) -> Optional[Dict[str, Any]]:
        """
        根据ID获取消息
        
        Args:
            message_id: 消息ID
            
        Returns:
            Optional[Dict[str, Any]]: 消息数据，未找到时返回None
        """
        for msg in self.messages:
            if msg.get('message_id') == message_id:
                return deepcopy(msg)
        
        return None
    
    def update_message(self, message_id: str, updates: Dict[str, Any]) -> bool:
        """
        更新消息
        
        Args:
            message_id: 消息ID
            updates: 更新内容
            
        Returns:
            bool: 是否更新成功
        """
        for i, msg in enumerate(self.messages):
            if msg.get('message_id') == message_id:
                # 不允许修改为system消息
                if updates.get('role') == 'system':
                    logger.warning(f"MessageManager: 不允许将消息修改为system类型")
                    return False
                
                self.messages[i].update(updates)
                self.messages[i]['updated_at'] = datetime.datetime.now().isoformat()
                self.stats['last_updated'] = datetime.datetime.now().isoformat()
                
                logger.debug(f"MessageManager: 成功更新消息 {message_id[:8]}...")
                return True
        
        logger.warning(f"MessageManager: 未找到消息 {message_id[:8]}...")
        return False
    
    def delete_message(self, message_id: str) -> bool:
        """
        删除消息
        
        Args:
            message_id: 消息ID
            
        Returns:
            bool: 是否删除成功
        """
        for i, msg in enumerate(self.messages):
            if msg.get('message_id') == message_id:
                del self.messages[i]
                self.stats['last_updated'] = datetime.datetime.now().isoformat()
                logger.debug(f"MessageManager: 成功删除消息 {message_id[:8]}...")
                return True
        
        logger.warning(f"MessageManager: 未找到要删除的消息 {message_id[:8]}...")
        return False
    
    # 私有辅助方法
    def _is_system_message(self, message: Dict[str, Any]) -> bool:
        """检查是否为system消息"""
        return message.get('role') == 'system' or message.get('type') == 'system'
    
    def _is_important_message(self, message: Dict[str, Any]) -> bool:
        """检查是否为重要消息"""
        role = message.get('role', '')
        msg_type = message.get('type', '')
        
        important_roles = {'user'}
        important_types = {'final_answer', 'error', 'summary'}
        
        return role in important_roles or msg_type in important_types
    
    def _try_auto_merge_message(self, message_id: str) -> bool:
        """
        兼容方法（现在不需要，因为消息直接合并）
        
        Args:
            message_id: 消息ID
            
        Returns:
            bool: 总是返回False，因为现在不需要自动合并
        """
        return False
    
    def __len__(self) -> int:
        """返回当前消息数量"""
        return len(self.messages)
    
    def __iter__(self):
        """支持迭代"""
        return iter(self.messages)
    
    def __getitem__(self, index) -> Dict[str, Any]:
        """支持索引访问"""
        return self.messages[index] 
    
    def log_print_messages(self,messages:List[Dict[str, Any]]):
        """搭建每个消息的role，前50个字符内容，以及消息的type等信息，在一行中，还要处理好tool_calls的情况下，不显示content ，而显示调用的工具"""
        for msg in messages:
            if msg.get('type') == 'tool_call':
                logger.info(f"MessageManager: 消息ID: {msg.get('message_id', '')[:8]}... - 角色: {msg.get('role', 'unknown')} - 类型: {msg.get('type', 'unknown')} - 调用工具: {msg.get('tool_calls', '')[:50]}...")
            elif msg.get('type') == 'handoff_agent':
                logger.info(f"MessageManager: 消息ID: {msg.get('message_id', '')[:8]}... - 角色: {msg.get('role', 'unknown')} - 类型: {msg.get('type', 'unknown')} - 交接给: {msg.get('content', '')[:50]}...")
            else:
                logger.info(f"MessageManager: 消息ID: {msg.get('message_id', '')[:8]}... - 角色: {msg.get('role', 'unknown')} - 类型: {msg.get('type', 'unknown')} - 内容: {msg.get('content', '')[:50]}...")

    def to_dict(self) -> Dict[str, Any]:
        """
        将MessageManager转换为字典格式
        
        Returns:
            Dict[str, Any]: 包含MessageManager状态的字典
        """
        return {
            'session_id': self.session_id,
            'max_token_limit': self.max_token_limit,
            'compression_threshold': self.compression_threshold,
            'auto_merge_chunks': self.auto_merge_chunks,
            'messages': deepcopy(self.messages),
            'stats': deepcopy(self.stats)
        }

    def get_latest_messages_by_agent(self, agent_name: str, limit: int = 10) -> List[Dict[str, Any]]:
        """
        获取特定agent的最新消息
        
        Args:
            agent_name: agent名称
            limit: 返回消息数量限制
            
        Returns:
            List[Dict[str, Any]]: 该agent的最新消息列表
        """
        # 筛选出指定agent的消息
        agent_messages = []
        for msg in self.messages:
            if msg.get('agent_name') == agent_name:
                agent_messages.append(msg)
        
        # 按时间戳排序，取最新的limit条
        agent_messages.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
        
        return agent_messages[:limit]