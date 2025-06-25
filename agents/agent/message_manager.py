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
        
        # 待合并的消息块缓存
        self.pending_chunks: Dict[str, List[Dict[str, Any]]] = {}
        
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
    
    def add_messages(self, messages: Union[Dict[str, Any], List[Dict[str, Any]]]) -> bool:
        """
        添加消息（支持单个消息或消息列表，自动处理chunk合并）
        
        Args:
            messages: 消息数据（单个消息字典或消息列表）
            
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
                # 有message_id，作为chunk处理（流式消息）
                chunk_data = deepcopy(message)
                chunk_data['chunk_id'] = f"chunk_{uuid.uuid4().hex[:8]}"
                chunk_data['timestamp'] = chunk_data.get('timestamp') or datetime.datetime.now().isoformat()
                chunk_data['is_chunk'] = True
                
                # 添加到pending chunks
                if message_id not in self.pending_chunks:
                    self.pending_chunks[message_id] = []
                
                self.pending_chunks[message_id].append(chunk_data)
                self.stats['total_chunks'] += 1
                
                logger.debug(f"MessageManager: 添加消息块，消息ID: {message_id[:8]}...")
                
                # 自动合并检查
                if self._try_auto_merge_message(message_id):
                    logger.debug(f"MessageManager: 自动合并消息 {message_id[:8]}...")
                
            else:
                # 没有message_id，作为完整消息处理
                msg_data = deepcopy(message)
                msg_data['message_id'] = str(uuid.uuid4())
                msg_data['timestamp'] = msg_data.get('timestamp') or datetime.datetime.now().isoformat()
                msg_data['is_chunk'] = False
                
                # 添加到消息列表
                self.messages.append(msg_data)
                self.stats['total_messages'] += 1
                
                logger.debug(f"MessageManager: 添加完整消息，ID: {msg_data['message_id'][:8]}...")
            
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
        合并指定消息ID的所有chunks为完整消息
        
        Args:
            message_id: 消息ID
            
        Returns:
            Optional[Dict[str, Any]]: 合并后的完整消息，失败时返回None
        """
        if message_id not in self.pending_chunks:
            logger.warning(f"MessageManager: 未找到消息ID {message_id[:8]}... 的chunks")
            return None
        
        chunks = self.pending_chunks[message_id]
        if not chunks:
            return None
        
        # 使用merge方法合并
        merged_messages = self.merge(chunks)
        if not merged_messages:
            return None
        
        merged_message = merged_messages[0]  # 应该只有一个合并后的消息
        merged_message['chunk_count'] = len(chunks)
        merged_message['timestamp'] = merged_message.get('timestamp') or datetime.datetime.now().isoformat()
        
        # 移除pending chunks并添加到messages
        del self.pending_chunks[message_id]
        self.messages.append(merged_message)
        
        self.stats['merged_messages'] += 1
        self.stats['total_messages'] += 1
        self.stats['last_updated'] = datetime.datetime.now().isoformat()
        
        logger.info(f"MessageManager: 成功合并消息 {message_id[:8]}...，包含 {len(chunks)} 个chunks")
        
        return merged_message
    
    def merge_all_pending_chunks(self) -> List[Dict[str, Any]]:
        """
        合并所有待处理的chunks
        
        Returns:
            List[Dict[str, Any]]: 合并后的消息列表
        """
        merged_messages = []
        
        for message_id in list(self.pending_chunks.keys()):
            merged_msg = self.merge_message_chunks(message_id)
            if merged_msg:
                merged_messages.append(merged_msg)
        
        logger.info(f"MessageManager: 批量合并完成，共合并 {len(merged_messages)} 个消息")
        
        return merged_messages
    
    def get_all_messages(self, include_pending_chunks: bool = False) -> List[Dict[str, Any]]:
        """
        获取所有消息
        
        Args:
            include_pending_chunks: 是否包含待合并的chunks
            
        Returns:
            List[Dict[str, Any]]: 所有消息列表
        """
        result = deepcopy(self.messages)
        
        if include_pending_chunks:
            # 添加所有pending chunks
            for message_id, chunks in self.pending_chunks.items():
                result.extend(chunks)
        
        # 按时间戳排序
        result.sort(key=lambda x: x.get('timestamp', ''))
        
        return result
    
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
            'pending_chunks_count': sum(len(chunks) for chunks in self.pending_chunks.values()),
            'pending_messages_count': len(self.pending_chunks),
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
        """尝试自动合并消息"""
        if message_id not in self.pending_chunks:
            return False
        
        chunks = self.pending_chunks[message_id]
        
        # 简单的自动合并策略：如果最后一个chunk包含结束标记
        if chunks:
            last_chunk = chunks[-1]
            content = last_chunk.get('content', '')
            
            # 检查是否有明显的结束标记
            end_markers = ['\n\n', '。', '！', '？', '.', '!', '?']
            if any(content.endswith(marker) for marker in end_markers):
                self.merge_message_chunks(message_id)
                return True
        
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