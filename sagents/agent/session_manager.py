"""
Session Manager 模块

负责管理智能体会话的状态、生命周期和中断控制。

作者: Eric ZZ
版本: 1.0
"""

import time
import threading
from typing import Dict, Any, Optional, List
from enum import Enum

from sagents.utils.logger import logger


class SessionStatus(Enum):
    """会话状态枚举"""
    IDLE = "idle"                    # 空闲状态
    RUNNING = "running"              # 运行中
    INTERRUPTED = "interrupted"      # 被中断
    COMPLETED = "completed"          # 已完成
    ERROR = "error"                  # 错误状态


class SessionManager:
    """
    会话状态管理器
    
    负责管理智能体会话的完整生命周期，包括：
    - 会话创建和销毁
    - 状态跟踪和更新
    - 中断请求处理
    - 过期会话清理
    
    线程安全设计，支持并发访问。
    """
    
    def __init__(self):
        """初始化会话管理器"""
        self._sessions = {}  # session_id -> session_info
        self._lock = threading.RLock()
        logger.info("SessionManager: 初始化完成")
    
    def create_session(self, session_id: str) -> Dict[str, Any]:
        """
        创建新会话
        
        Args:
            session_id: 会话唯一标识符
            
        Returns:
            Dict[str, Any]: 创建的会话信息
        """
        with self._lock:
            session_info = {
                'session_id': session_id,
                'status': SessionStatus.IDLE,
                'created_at': time.time(),
                'updated_at': time.time(),
                'current_phase': None,
                'interrupt_requested': False,
                'interrupt_message': None,
                'metadata': {}
            }
            self._sessions[session_id] = session_info
            logger.info(f"SessionManager: 创建会话 {session_id}")
            return session_info.copy()
    
    def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """
        获取会话信息
        
        Args:
            session_id: 会话ID
            
        Returns:
            Optional[Dict[str, Any]]: 会话信息，不存在则返回None
        """
        with self._lock:
            session = self._sessions.get(session_id)
            return session.copy() if session else None
    
    def update_session_status(self, session_id: str, status: SessionStatus, phase: str = None) -> bool:
        """
        更新会话状态
        
        Args:
            session_id: 会话ID
            status: 新的会话状态
            phase: 当前执行阶段（可选）
            
        Returns:
            bool: 更新是否成功
        """
        with self._lock:
            if session_id not in self._sessions:
                logger.warning(f"SessionManager: 尝试更新不存在的会话 {session_id}")
                return False
            
            self._sessions[session_id]['status'] = status
            self._sessions[session_id]['updated_at'] = time.time()
            
            if phase:
                self._sessions[session_id]['current_phase'] = phase
            
            logger.debug(f"SessionManager: 会话 {session_id} 状态更新为 {status.value}")
            return True
    
    def request_interrupt(self, session_id: str, message: str = "用户请求中断") -> bool:
        """
        请求中断会话
        
        Args:
            session_id: 会话ID
            message: 中断消息
            
        Returns:
            bool: 中断请求是否成功
        """
        with self._lock:
            if session_id not in self._sessions:
                logger.warning(f"SessionManager: 尝试中断不存在的会话 {session_id}")
                return False
            
            session = self._sessions[session_id]
            if session['status'] not in [SessionStatus.RUNNING]:
                logger.warning(f"SessionManager: 会话 {session_id} 状态为 {session['status'].value}，无法中断")
                return False
            
            session['interrupt_requested'] = True
            session['interrupt_message'] = message
            session['updated_at'] = time.time()
            
            logger.info(f"SessionManager: 请求中断会话 {session_id}: {message}")
            return True
    
    def is_interrupted(self, session_id: str) -> bool:
        """
        检查会话是否被中断
        
        Args:
            session_id: 会话ID
            
        Returns:
            bool: 是否被中断
        """
        with self._lock:
            session = self._sessions.get(session_id)
            return session['interrupt_requested'] if session else False
    
    def get_interrupt_message(self, session_id: str) -> Optional[str]:
        """
        获取中断消息
        
        Args:
            session_id: 会话ID
            
        Returns:
            Optional[str]: 中断消息，无中断则返回None
        """
        with self._lock:
            session = self._sessions.get(session_id)
            return session.get('interrupt_message') if session else None
    
    def clear_interrupt(self, session_id: str) -> bool:
        """
        清除中断标志
        
        Args:
            session_id: 会话ID
            
        Returns:
            bool: 清除是否成功
        """
        with self._lock:
            if session_id not in self._sessions:
                logger.warning(f"SessionManager: 尝试清除不存在会话的中断标志 {session_id}")
                return False
            
            self._sessions[session_id]['interrupt_requested'] = False
            self._sessions[session_id]['interrupt_message'] = None
            self._sessions[session_id]['updated_at'] = time.time()
            logger.debug(f"SessionManager: 清除会话 {session_id} 的中断标志")
            return True
    
    def remove_session(self, session_id: str) -> bool:
        """
        移除会话
        
        Args:
            session_id: 会话ID
            
        Returns:
            bool: 移除是否成功
        """
        with self._lock:
            if session_id in self._sessions:
                del self._sessions[session_id]
                logger.info(f"SessionManager: 移除会话 {session_id}")
                return True
            else:
                logger.warning(f"SessionManager: 尝试移除不存在的会话 {session_id}")
                return False
    
    def list_sessions(self) -> List[Dict[str, Any]]:
        """
        列出所有会话
        
        Returns:
            List[Dict[str, Any]]: 所有会话信息列表
        """
        with self._lock:
            return [session.copy() for session in self._sessions.values()]
    
    def list_active_sessions(self) -> List[Dict[str, Any]]:
        """
        列出所有活跃会话（运行中的会话）
        
        Returns:
            List[Dict[str, Any]]: 活跃会话信息列表
        """
        with self._lock:
            active_sessions = []
            for session in self._sessions.values():
                if session['status'] == SessionStatus.RUNNING:
                    active_sessions.append(session.copy())
            return active_sessions
    
    def cleanup_old_sessions(self, max_age_seconds: int = 3600) -> int:
        """
        清理过期会话
        
        Args:
            max_age_seconds: 最大会话年龄（秒），默认1小时
            
        Returns:
            int: 清理的会话数量
        """
        current_time = time.time()
        removed_count = 0
        
        with self._lock:
            expired_sessions = []
            for session_id, session in self._sessions.items():
                if current_time - session['updated_at'] > max_age_seconds:
                    expired_sessions.append(session_id)
            
            for session_id in expired_sessions:
                del self._sessions[session_id]
                removed_count += 1
            
            if removed_count > 0:
                logger.info(f"SessionManager: 清理了 {removed_count} 个过期会话")
        
        return removed_count
    
    def get_session_count(self) -> int:
        """
        获取当前会话总数
        
        Returns:
            int: 会话总数
        """
        with self._lock:
            return len(self._sessions)
    
    def get_active_session_count(self) -> int:
        """
        获取活跃会话数量
        
        Returns:
            int: 活跃会话数量
        """
        with self._lock:
            count = 0
            for session in self._sessions.values():
                if session['status'] == SessionStatus.RUNNING:
                    count += 1
            return count
    
    def update_session_metadata(self, session_id: str, metadata: Dict[str, Any]) -> bool:
        """
        更新会话元数据
        
        Args:
            session_id: 会话ID
            metadata: 要更新的元数据
            
        Returns:
            bool: 更新是否成功
        """
        with self._lock:
            if session_id not in self._sessions:
                logger.warning(f"SessionManager: 尝试更新不存在会话的元数据 {session_id}")
                return False
            
            self._sessions[session_id]['metadata'].update(metadata)
            self._sessions[session_id]['updated_at'] = time.time()
            logger.debug(f"SessionManager: 更新会话 {session_id} 的元数据")
            return True
    
    def get_session_statistics(self) -> Dict[str, Any]:
        """
        获取会话统计信息
        
        Returns:
            Dict[str, Any]: 统计信息
        """
        with self._lock:
            stats = {
                'total_sessions': len(self._sessions),
                'status_distribution': {},
                'oldest_session_age': 0,
                'newest_session_age': 0
            }
            
            if not self._sessions:
                return stats
            
            current_time = time.time()
            status_counts = {}
            oldest_time = current_time
            newest_time = 0
            
            for session in self._sessions.values():
                # 统计状态分布
                status = session['status'].value
                status_counts[status] = status_counts.get(status, 0) + 1
                
                # 统计年龄
                created_at = session['created_at']
                if created_at < oldest_time:
                    oldest_time = created_at
                if created_at > newest_time:
                    newest_time = created_at
            
            stats['status_distribution'] = status_counts
            stats['oldest_session_age'] = current_time - oldest_time
            stats['newest_session_age'] = current_time - newest_time
            
            return stats 