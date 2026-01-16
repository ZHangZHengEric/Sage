"""用户记忆驱动接口定义

定义用户记忆后端的抽象接口，支持多种实现（Tool/MCP、Direct、Local等）。

Author: Eric ZZ
Date: 2024-12-21
"""

from abc import ABC, abstractmethod
from typing import List, Optional, Any
from .schemas import MemoryEntry

class IMemoryDriver(ABC):
    """用户记忆驱动接口
    
    定义了记忆存储后端必须实现的方法。
    """
    
    @abstractmethod
    async def remember(self, user_id: str, memory_key: str, content: str, memory_type: str, tags: str, session_id: Optional[str] = None, session_context: Optional[Any] = None) -> str:
        """记住某个记忆
        
        Args:
            user_id: 用户ID
            memory_key: 记忆键
            content: 记忆内容
            memory_type: 记忆类型
            tags: 标签字符串
            session_id: 会话ID
            session_context: 会话上下文
            
        Returns:
            操作结果描述
        """
        pass

    @abstractmethod
    async def recall(self, user_id: str, query: str, limit: int, session_id: Optional[str] = None, session_context: Optional[Any] = None) -> List[MemoryEntry]:
        """检索记忆
        
        Args:
            user_id: 用户ID
            query: 查询内容
            limit: 数量限制
            session_id: 会话ID
            session_context: 会话上下文
            
        Returns:
            记忆条目列表
        """
        pass

    @abstractmethod
    async def recall_by_type(self, user_id: str, memory_type: str, query: str, limit: int, session_id: Optional[str] = None, session_context: Optional[Any] = None) -> List[MemoryEntry]:
        """按类型检索记忆
        
        Args:
            user_id: 用户ID
            memory_type: 记忆类型
            query: 查询内容
            limit: 数量限制
            session_id: 会话ID
            session_context: 会话上下文
            
        Returns:
            记忆条目列表
        """
        pass

    @abstractmethod
    async def forget(self, user_id: str, memory_key: str, session_id: Optional[str] = None, session_context: Optional[Any] = None) -> str:
        """忘记某个记忆
        
        Args:
            user_id: 用户ID
            memory_key: 记忆键
            session_id: 会话ID
            session_context: 会话上下文
            
        Returns:
            操作结果描述
        """
        pass

    @abstractmethod
    def is_available(self) -> bool:
        """检查驱动是否可用
        
        Returns:
            是否可用
        """
        pass
