"""用户记忆管理模块

提供用户级记忆的存储、检索和管理功能，支持多种存储后端。
记忆工具已移至 sagents.tool.memory_tool 模块。

主要组件：
- MemoryType: 记忆类型枚举
- MemoryBackend: 存储后端类型
- MemoryEntry: 记忆条目数据结构
- UserMemoryManager: 用户记忆管理器（集成工具管理器）
- IMemoryDriver: 记忆驱动接口
- ToolMemoryDriver: 基于工具的记忆驱动实现
"""

from .schemas import MemoryType, MemoryBackend, MemoryEntry
from .manager import UserMemoryManager
from .interfaces import IMemoryDriver
from .drivers.tool import ToolMemoryDriver
from .drivers.vector import VectorMemoryDriver

__all__ = [
    'MemoryType',
    'MemoryBackend',
    'MemoryEntry',
    'UserMemoryManager',
    'IMemoryDriver',
    'ToolMemoryDriver',
    'VectorMemoryDriver'
]

__version__ = '1.0.0'
__author__ = 'Eric ZZ'