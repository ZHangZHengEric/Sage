"""用户记忆管理器

提供用户记忆的存储、检索、管理功能，支持多种存储后端。
"""

import asyncio
import traceback
import os
from typing import List, Any, Optional
from sagents.utils.logger import logger
from .schemas import MemoryEntry
from .interfaces import IMemoryDriver
from .drivers.tool import ToolMemoryDriver


class UserMemoryManager:
    """用户记忆管理器
    
    作为统一的记忆管理入口，通过IMemoryDriver接口与具体的记忆后端交互。
    以user_id为索引，自动选择最佳的记忆工具实现。
    """

    def __init__(
        self,
        workspace: str,
        driver: Optional[IMemoryDriver] = None,
        model: Any = None,
    ):
        """
        初始化用户记忆管理器
        
        Args:
            driver: 自定义的记忆驱动实例（可选，如果提供则优先使用）
            model: LLM模型实例（用于记忆提取）
            workspace: 工作空间根目录
        """
        self.memory_root = os.environ.get("MEMORY_ROOT_PATH")
        if not self.memory_root:
            self.memory_root = os.path.join(workspace, "user_memory")
            os.environ["MEMORY_ROOT_PATH"] = self.memory_root
            logger.info(f"UserMemoryManager: 未设置MEMORY_ROOT_PATH，使用默认路径: {self.memory_root}")
        else:
            logger.info(f"UserMemoryManager: 使用环境变量MEMORY_ROOT_PATH: {self.memory_root}")

        self.driver = driver
        if not self.driver:
            logger.info("UserMemoryManager 初始化完成，使用默认驱动, ToolMemoryDriver")
        else:
            logger.info(f"UserMemoryManager 初始化完成，使用自定义驱动: {self.driver.__class__.__name__}    ")

    def _get_driver(self) -> Optional[IMemoryDriver]:
        """获取记忆驱动
        
        优先使用初始化的driver，如果未初始化则尝试使用tool_manager创建ToolMemoryDriver
        """
        if self.driver:
            return self.driver
        return ToolMemoryDriver()

    def _get_active_driver(self) -> Optional[IMemoryDriver]:
        """获取可用的记忆驱动，如果不可用则返回None"""
        driver = self._get_driver()
        if driver and driver.is_available():
            return driver
        return None

    def is_enabled(self) -> bool:
        """检查记忆功能是否可用"""
        return self._get_active_driver() is not None

    def get_user_memory_usage_description(self) -> str:
        """获取用户记忆的使用说明"""
        return """
## 用户记忆工具使用指南

**remember_user_memory**: 记录用户偏好、个人信息、特殊要求、重要上下文、活动、和用户主动告知的信息。使用相同的key可以进行记忆的更新覆盖。
**recall_user_memory**: 检索记忆以提供个性化回答和保持对话连续性
**forget_user_memory**: 删除过时、错误或用户要求删除的记忆

**使用原则**: 主动识别有价值信息，适度记录长期内容，及时更新变化
**标签建议**: preference, work, learning, project, personal, requirement
"""

    async def _safe_remember(self, memory: dict, user_id: str, session_id: str, session_context: Any) -> None:
        """辅助方法：安全地保存单条记忆"""
        try:
            logger.info(f"UserMemoryManager: 开始保存记忆 {memory['key']}")
            await self.remember(
                user_id=user_id,
                memory_key=memory['key'],
                content=memory['content'],
                memory_type=memory['type'],
                tags=memory.get('tags', []),
                session_id=session_id,
                session_context=session_context
            )
        except Exception as e:
            logger.error(f"UserMemoryManager: 保存记忆失败 {memory.get('key')}: {e}")

    async def _safe_forget(self, key: str, user_id: str, session_id: str, session_context: Any) -> None:
        """辅助方法：安全地删除单条记忆"""
        try:
            await self.forget(
                user_id=user_id,
                memory_key=key, 
                session_id=session_id, 
                session_context=session_context,
                tool_manager=session_context.tool_manager
            )
        except Exception as e:
            logger.error(f"UserMemoryManager: 删除记忆失败 {key}: {e}")

    def _format_memories_for_llm(self, memories: List[MemoryEntry]) -> str:
        """将MemoryEntry列表格式化为大模型友好的字符串
        
        Args:
            memories: MemoryEntry对象列表
            
        Returns:
            格式化的字符串，便于大模型理解和使用
        """
        if not memories:
            return "没有找到相关记忆。"

        formatted_lines = []
        formatted_lines.append(f"找到 {len(memories)} 条相关记忆：")
        formatted_lines.append("")

        for i, memory in enumerate(memories, 1):
            # 格式化时间
            created_time = "Unknown"
            if memory.created_at:
                created_time = memory.created_at.strftime("%Y-%m-%d %H:%M")

            # 构建简化的记忆条目
            memory_line = f"{i}. 【{memory.key}】{memory.content} ({created_time})"

            formatted_lines.append(memory_line)
            formatted_lines.append("")  # 空行分隔

        return "\n".join(formatted_lines)

    # ========== 核心记忆操作接口 ==========

    async def remember(self, user_id: str, memory_key: str, content: str, memory_type: str = "experience", tags: str = "", session_id: Optional[str] = None, session_context: Optional[Any] = None, tool_manager: Any = None) -> str:
        """记住某个记忆
        
        Args:
            user_id: 用户ID
            memory_key: 记忆键（唯一标识）
            content: 记忆内容
            memory_type: 记忆类型
            tags: 标签（逗号分隔）
            session_id: 会话ID
            session_context: 会话上下文
            tool_manager: 工具管理器（用于创建临时驱动）
            
        Returns:
            操作结果描述
        """
        driver = self._get_active_driver()
        if not driver:
            logger.warning("记忆功能已禁用：未配置记忆存储路径且无可用的MCP记忆服务")
            return

        try:
            return await driver.remember(
                user_id=user_id,
                memory_key=memory_key,
                content=content,
                memory_type=memory_type,
                tags=tags,
                session_id=session_id,
                session_context=session_context
            )

        except Exception as e:
            logger.error(f"记住记忆失败: {e}")
            return f"记住记忆失败：{str(e)}"

    async def recall(self, user_id: str, query: str, limit: int = 5, session_id: Optional[str] = None, session_context: Optional[Any] = None, tool_manager: Any = None) -> str:
        """获取相似的记忆
        
        Args:
            user_id: 用户ID
            query: 查询内容（关键词）
            limit: 返回结果数量限制
            session_id: 会话ID
            session_context: 会话上下文
            tool_manager: 工具管理器
            
        Returns:
            格式化的记忆字符串，便于大模型理解和使用
        """
        driver = self._get_active_driver()
        if not driver:
            return "记忆功能已禁用：未配置记忆存储路径且无可用的MCP记忆服务"

        try:
            # 通过驱动获取记忆对象列表
            memory_entries = await driver.recall(
                user_id=user_id,
                query=query,
                limit=limit,
                session_id=session_id,
                session_context=session_context
            )

            if not memory_entries:
                return f"未找到与 '{query}' 相关的记忆。"

            # 格式化为大模型友好的字符串
            return self._format_memories_for_llm(memory_entries)

        except Exception as e:
            logger.error(f"回忆记忆失败: {e}")
            return f"回忆记忆失败：{str(e)}"

    async def forget(self, user_id: str, memory_key: str, session_id: Optional[str] = None, session_context: Optional[Any] = None, tool_manager: Any = None) -> str:
        """忘掉某个记忆
        
        Args:
            user_id: 用户ID
            memory_key: 要删除的记忆键
            session_id: 会话ID（可选）
            session_context: 会话上下文
            tool_manager: 工具管理器
            
        Returns:
            操作结果描述
        """
        driver = self._get_active_driver()
        if not driver:
            return "记忆功能已禁用：未配置记忆存储路径且无可用的MCP记忆服务"

        try:
            return await driver.forget(
                user_id=user_id,
                memory_key=memory_key,
                session_id=session_id,
                session_context=session_context
            )

        except Exception as e:
            logger.error(f"忘记记忆失败: {e}")
            return f"忘记记忆失败：{str(e)}"

    async def _fetch_single_memory_type(self, driver: IMemoryDriver, user_id: str, memory_type: str, session_id: str, session_context: Any) -> Optional[tuple[str, str]]:
        """辅助方法：获取单个类型的记忆"""
        try:
            memories = await driver.recall_by_type(
                user_id=user_id,
                memory_type=memory_type,
                query="",
                limit=10,
                session_id=session_id,
                session_context=session_context
            )

            if memories:
                formatted_memories = []
                for memory in memories:
                    formatted_memories.append(f"- {memory.key}: {memory.content}")

                if formatted_memories:
                    return memory_type, "\n".join(formatted_memories)
            return None

        except Exception as e:
            logger.error(traceback.format_exc())
            logger.warning(f"查询 {memory_type} 类型记忆失败: {e}")
            return None

    async def get_system_memories(self, user_id: str, session_id: Optional[str] = None, session_context: Optional[Any] = None, tool_manager: Any = None) -> dict:
        """获取系统级记忆并格式化
        
        Args:
            user_id: 用户ID
            session_id: 会话ID
            session_context: 会话上下文
            tool_manager: 工具管理器
            
        Returns:
            格式化的系统级记忆字典
        """
        driver = self._get_active_driver()
        if not driver:
            logger.info("记忆功能已禁用，跳过系统级记忆获取")
            return {}

        try:
            # 系统级记忆类型
            system_memory_types = ['preference', 'requirement', 'persona', 'constraint']
            system_memories = {}
            effective_session_id = session_id or f"memory_session_{user_id}"

            # 并发获取所有类型的记忆
            tasks = [
                self._fetch_single_memory_type(driver, user_id, m_type, effective_session_id, session_context)
                for m_type in system_memory_types
            ]

            results = await asyncio.gather(*tasks)

            for result in results:
                if result:
                    memory_type, content = result
                    system_memories[memory_type] = content

            logger.info(f"成功获取 {len(system_memories)} 种类型的系统级记忆")
            return system_memories

        except Exception as e:
            logger.error(traceback.format_exc())
            logger.error(f"获取系统级记忆失败: {e}")
            return {}

    def format_system_memories_for_context(self, system_memories: dict) -> str:
        """将系统级记忆格式化为适合注入system_context的字符串
        
        Args:
            system_memories: 系统级记忆字典
            
        Returns:
            格式化的记忆字符串
        """
        if not system_memories:
            return ""

        memory_context = []

        if 'preference' in system_memories:
            memory_context.append(f"## 用户偏好\n{system_memories['preference']}")

        if 'requirement' in system_memories:
            memory_context.append(f"## 用户要求\n{system_memories['requirement']}")

        if 'persona' in system_memories:
            memory_context.append(f"## 用户人设\n{system_memories['persona']}")

        if 'constraint' in system_memories:
            memory_context.append(f"## 约束条件\n{system_memories['constraint']}")

        return "\n\n".join(memory_context) if memory_context else ""

    async def get_system_memories_summary(self, user_id: str, session_id: Optional[str] = None, tool_manager: Any = None) -> str:
        """获取系统级记忆的摘要
        
        Args:
            user_id: 用户ID
            session_id: 会话ID
            tool_manager: 工具管理器
            
        Returns:
            系统级记忆的摘要字符串
        """
        system_memories = await self.get_system_memories(user_id, session_id=session_id)
        return self.format_system_memories_for_context(system_memories)
