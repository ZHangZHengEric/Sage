"""记忆类型定义

定义用户记忆的类型和存储后端类型。

Author: Eric ZZ
Date: 2024-12-21
"""

import time
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List


class MemoryType(Enum):
    """记忆类型枚举 - 分层管理"""
    # 系统级记忆（自动注入system prompt）
    PREFERENCE = "preference"           # 用户偏好  相同内容要去重，比如姓名，就不能够有两个
    REQUIREMENT = "requirement"         # 用户要求  相同内容要去重
    PERSONA = "persona"                 # 用户人设  相同内容要去重
    CONSTRAINT = "constraint"           # 约束条件  相同内容要去重
    
    # 上下文记忆（按需查询）
    CONTEXT = "context"                 # 个人上下文
    PROJECT = "project"                 # 项目信息
    WORKFLOW = "workflow"               # 工作流程
    
    # 知识记忆（智能检索）
    EXPERIENCE = "experience"           # 个人经验
    LEARNING = "learning"               # 学习进度
    SKILL = "skill"                     # 技能水平
    
    # 辅助记忆（补充信息）
    NOTE = "note"                       # 个人备注
    BOOKMARK = "bookmark"               # 个人书签
    PATTERN = "pattern"                 # 行为模式


class MemoryBackend(Enum):
    """记忆存储后端类型"""
    LOCAL_FILE = "local_file"           # 本地文件存储
    MCP_TOOL = "mcp_tool"               # MCP工具存储
    HYBRID = "hybrid"                   # 混合模式


@dataclass
class MemoryEntry:
    """用户记忆条目数据结构 - 扁平化设计，便于搜索"""
    key: str                        # 记忆标识（唯一键）
    content: str                    # 记忆内容（统一使用字符串存储）
    memory_type: MemoryType         # 记忆类型
    created_at: datetime = None     # 创建时间
    updated_at: datetime = None     # 更新时间
    importance: float = 0.5         # 重要性评分 (0-1)
    tags: List[str] = None          # 标签列表
    access_count: int = 0           # 访问次数
    version: int = 1                # 版本号（用于追踪更新历史）
    
    def __post_init__(self):
        if self.tags is None:
            self.tags = []
        if self.created_at is None:
            self.created_at = datetime.now()
        if self.updated_at is None:
            self.updated_at = self.created_at
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return {
            'key': self.key,
            'content': self.content,
            'memory_type': self.memory_type.value,
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat(),
            'importance': self.importance,
            'tags': self.tags,
            'access_count': self.access_count,
            'version': self.version
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'MemoryEntry':
        """从字典创建记忆条目"""
        data = data.copy()
        data['memory_type'] = MemoryType(data['memory_type'])
        data['created_at'] = datetime.fromisoformat(data['created_at'])
        data['updated_at'] = datetime.fromisoformat(data['updated_at'])
        return cls(**data)
    
    def update_access(self):
        """更新访问信息"""
        self.access_count += 1
        self.updated_at = datetime.now()
    
    def update_content(self, content: str, increment_version: bool = True):
        """更新记忆内容
        
        Args:
            content: 新的内容
            increment_version: 是否增加版本号
        """
        self.content = content
        
        if increment_version:
            self.version += 1
        self.updated_at = datetime.now()
    
    def is_preference_type(self) -> bool:
        """判断是否为偏好类型记忆"""
        return self.memory_type == MemoryType.PREFERENCE
    
    def is_experience_type(self) -> bool:
        """判断是否为经验类型记忆"""
        return self.memory_type == MemoryType.EXPERIENCE
    
    def should_append_version(self) -> bool:
        """判断是否应该追加版本而非覆盖更新"""
        # 经验类记忆建议追加版本，保留历史
        return self.memory_type in [MemoryType.EXPERIENCE, MemoryType.NOTE]
    
    def is_system_memory(self) -> bool:
        """判断是否为系统级记忆（需要自动注入system prompt）"""
        return self.memory_type in [MemoryType.PREFERENCE, MemoryType.REQUIREMENT, 
                                   MemoryType.PERSONA, MemoryType.CONSTRAINT]
    
    def is_context_memory(self) -> bool:
        """判断是否为上下文记忆（按需查询）"""
        return self.memory_type in [MemoryType.CONTEXT, MemoryType.PROJECT, MemoryType.WORKFLOW]
    
    def is_knowledge_memory(self) -> bool:
        """判断是否为知识记忆（智能检索）"""
        return self.memory_type in [MemoryType.EXPERIENCE, MemoryType.LEARNING, MemoryType.SKILL]
    
    def is_auxiliary_memory(self) -> bool:
        """判断是否为辅助记忆（补充信息）"""
        return self.memory_type in [MemoryType.NOTE, MemoryType.BOOKMARK, MemoryType.PATTERN]
    
    def matches_query(self, query: str) -> bool:
        """检查是否匹配搜索查询，感觉好像不需要，这个是一个记忆的最好单元，应该是管理类，来进行搜索"""
        if not query:
            return True
        
        query_lower = query.lower()
        
        # 在内容中搜索
        if query_lower in self.content.lower():
            return True
        
        # 在标签中搜索
        for tag in self.tags:
            if query_lower in tag.lower():
                return True
        
        # 在key中搜索
        if query_lower in self.key.lower():
            return True
        
        return False


def generate_memory_id(memory_type: MemoryType) -> str:
    """生成记忆ID
    
    Args:
        memory_type: 记忆类型
    
    Returns:
        格式化的记忆ID
    """
    timestamp = int(time.time())
    return f"{memory_type.value}.{timestamp}"


def get_system_memory_types() -> List[MemoryType]:
    """获取系统级记忆类型列表
    
    Returns:
        系统级记忆类型列表
    """
    return [MemoryType.PREFERENCE, MemoryType.REQUIREMENT, MemoryType.PERSONA, MemoryType.CONSTRAINT]


def get_context_memory_types() -> List[MemoryType]:
    """获取上下文记忆类型列表
    
    Returns:
        上下文记忆类型列表
    """
    return [MemoryType.CONTEXT, MemoryType.PROJECT, MemoryType.WORKFLOW]


def get_knowledge_memory_types() -> List[MemoryType]:
    """获取知识记忆类型列表
    
    Returns:
        知识记忆类型列表
    """
    return [MemoryType.EXPERIENCE, MemoryType.LEARNING, MemoryType.SKILL]


def get_auxiliary_memory_types() -> List[MemoryType]:
    """获取辅助记忆类型列表
    
    Returns:
        辅助记忆类型列表
    """
    return [MemoryType.NOTE, MemoryType.BOOKMARK, MemoryType.PATTERN]