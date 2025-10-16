"""
数据库管理器

提供SQLite数据库的连接、初始化和管理功能
支持文件模式和内存模式
"""

import os
import sqlite3
import json
import asyncio
from typing import Dict, Any, Optional, List
from contextlib import asynccontextmanager
from sagents.utils.logger import logger

from .models import MCPServer, AgentConfig
from entities.entities import SageHTTPException


class DatabaseManager:
    """数据库管理器"""
    
    def __init__(self, db_type: str = "file", db_path: str = "./"):
        """
        初始化数据库管理器
        
        Args:
            db_type: 数据库类型，"file" 或 "memory"
            db_path: 数据库文件路径，仅在file模式下有效
        """
        self.db_type = db_type
        self.db_path = db_path
        self._connection = None
        self._lock = asyncio.Lock()
        
        if db_type == "file":
            # 确保数据库目录存在
            os.makedirs(db_path, exist_ok=True)
            self.db_file = os.path.join(db_path, "agent_platform.db")
            logger.info(f"使用文件数据库: {self.db_file}")
        else:
            self.db_file = ":memory:"
            logger.info("使用内存数据库")
    
    async def initialize(self):
        """初始化数据库连接和表结构"""
        async with self._lock:
            try:
                self._connection = sqlite3.connect(self.db_file, check_same_thread=False)
                self._connection.row_factory = sqlite3.Row
                
                # 创建表结构
                cursor = self._connection.cursor()
                MCPServer.create_table(cursor)
                AgentConfig.create_table(cursor)
                self._connection.commit()
                
                logger.info("数据库初始化完成")
                
            except Exception as e:
                logger.error(f"数据库初始化失败: {e}")
                raise SageHTTPException(
                    status_code=500,
                    detail="数据库初始化失败",
                    error_detail=str(e)
                )
    
    async def close(self):
        """关闭数据库连接"""
        async with self._lock:
            if self._connection:
                self._connection.close()
                self._connection = None
                logger.info("数据库连接已关闭")
    
    @asynccontextmanager
    async def get_cursor(self):
        """获取数据库游标的上下文管理器"""
        async with self._lock:
            if not self._connection:
                raise SageHTTPException(
                    status_code=500,
                    detail="数据库未初始化",
                    error_detail="数据库连接不存在"
                )
            
            cursor = self._connection.cursor()
            try:
                yield cursor
                self._connection.commit()
            except Exception as e:
                self._connection.rollback()
                logger.error(f"数据库操作失败: {e}")
                raise SageHTTPException(
                    status_code=500,
                    detail="数据库操作失败",
                    error_detail=str(e)
                )
            finally:
                cursor.close()
    
    # ============= MCP服务器相关方法 =============
    
    async def save_mcp_server(self, name: str, config: Dict[str, Any]) -> bool:
        """保存MCP服务器配置"""
        try:
            async with self.get_cursor() as cursor:
                server = MCPServer(name=name, config=config)
                server.save(cursor)
                logger.info(f"MCP服务器配置已保存: {name}")
                return True
        except SageHTTPException:
            # 重新抛出 SageHTTPException
            raise
        except Exception as e:
            logger.error(f"保存MCP服务器配置失败: {e}")
            raise SageHTTPException(
                status_code=500,
                detail="保存MCP服务器配置失败",
                error_detail=str(e)
            )
    
    async def get_mcp_server(self, name: str) -> Optional[MCPServer]:
        """获取MCP服务器配置"""
        try:
            async with self.get_cursor() as cursor:
                return MCPServer.get_by_name(cursor, name)
        except SageHTTPException:
            # 重新抛出 SageHTTPException
            raise
        except Exception as e:
            logger.error(f"获取MCP服务器配置失败: {e}")
            raise SageHTTPException(
                status_code=500,
                detail="获取MCP服务器配置失败",
                error_detail=str(e)
            )
    
    async def get_all_mcp_servers(self) -> List[MCPServer]:
        """获取所有MCP服务器配置"""
        try:
            async with self.get_cursor() as cursor:
                return MCPServer.get_all(cursor)
        except SageHTTPException:
            # 重新抛出 SageHTTPException
            raise
        except Exception as e:
            logger.error(f"获取所有MCP服务器配置失败: {e}")
            raise SageHTTPException(
                status_code=500,
                detail="获取所有MCP服务器配置失败",
                error_detail=str(e)
            )
    
    async def delete_mcp_server(self, name: str) -> bool:
        """删除MCP服务器配置"""
        try:
            async with self.get_cursor() as cursor:
                result = MCPServer.delete_by_name(cursor, name)
                if result:
                    logger.info(f"MCP服务器配置已删除: {name}")
                return result
        except SageHTTPException:
            # 重新抛出 SageHTTPException
            raise
        except Exception as e:
            logger.error(f"删除MCP服务器配置失败: {e}")
            raise SageHTTPException(
                status_code=500,
                detail="删除MCP服务器配置失败",
                error_detail=str(e)
            )
    
    async def get_enabled_mcp_servers(self) -> List[MCPServer]:
        """获取所有启用的MCP服务器"""
        servers = await self.get_all_mcp_servers()
        return [server for server in servers if not server.config.get('disabled', False)]
    
    # ============= Agent配置相关方法 =============
    
    async def save_agent_config(self, agent_id: str, name: str, config: Dict[str, Any]) -> bool:
        """保存Agent配置"""
        try:
            async with self.get_cursor() as cursor:
                agent = AgentConfig(agent_id=agent_id, name=name, config=config)
                agent.save(cursor)
                logger.info(f"Agent配置已保存: {agent_id}")
                return True
        except SageHTTPException:
            # 重新抛出 SageHTTPException
            raise
        except Exception as e:
            logger.error(f"保存Agent配置失败: {e}")
            raise SageHTTPException(
                status_code=500,
                detail="保存Agent配置失败",
                error_detail=str(e)
            )
    
    async def get_agent_config(self, agent_id: str) -> Optional[AgentConfig]:
        """获取Agent配置"""
        try:
            async with self.get_cursor() as cursor:
                return AgentConfig.get_by_id(cursor, agent_id)
        except SageHTTPException:
            # 重新抛出 SageHTTPException
            raise
        except Exception as e:
            logger.error(f"获取Agent配置失败: {e}")
            raise SageHTTPException(
                status_code=500,
                detail="获取Agent配置失败",
                error_detail=str(e)
            )
    
    async def get_all_agent_configs(self) -> List[AgentConfig]:
        """获取所有Agent配置"""
        try:
            async with self.get_cursor() as cursor:
                return AgentConfig.get_all(cursor)
        except SageHTTPException:
            # 重新抛出 SageHTTPException
            raise
        except Exception as e:
            logger.error(f"获取所有Agent配置失败: {e}")
            raise SageHTTPException(
                status_code=500,
                detail="获取所有Agent配置失败",
                error_detail=str(e)
            )
    
    async def delete_agent_config(self, agent_id: str) -> bool:
        """删除Agent配置"""
        try:
            async with self.get_cursor() as cursor:
                result = AgentConfig.delete_by_id(cursor, agent_id)
                if result:
                    logger.info(f"Agent配置已删除: {agent_id}")
                return result
        except SageHTTPException:
            # 重新抛出 SageHTTPException
            raise
        except Exception as e:
            logger.error(f"删除Agent配置失败: {e}")
            raise SageHTTPException(
                status_code=500,
                detail="删除Agent配置失败",
                error_detail=str(e)
            )
    
    # ============= 初始化相关方法 =============
    
    async def initialize_from_preset_configs(self, preset_mcp_config: str, preset_running_config: str):
        """从预设配置文件初始化数据库"""
        logger.info("开始从预设配置文件初始化数据库")
        
        # 检查是否需要初始化
        if await self._should_initialize():
            await self._load_preset_mcp_config(preset_mcp_config)
            await self._load_preset_agent_config(preset_running_config)
            logger.info("数据库初始化完成")
        else:
            logger.info("数据库已存在数据，跳过初始化")
    
    async def _should_initialize(self) -> bool:
        """检查是否需要初始化数据库"""
        # 如果是内存模式，总是需要初始化
        if self.db_type == "memory":
            return True
        
        # 如果是文件模式，检查是否有数据
        mcp_servers = await self.get_all_mcp_servers()
        agent_configs = await self.get_all_agent_configs()
        
        return len(mcp_servers) == 0 and len(agent_configs) == 0
    
    async def _load_preset_mcp_config(self, config_path: str):
        """加载预设MCP配置"""
        if not config_path or not os.path.exists(config_path):
            logger.warning(f"预设MCP配置文件不存在: {config_path}")
            return
        
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
            
            mcp_servers = config.get('mcpServers', {})
            for name, server_config in mcp_servers.items():
                await self.save_mcp_server(name, server_config)
            
            logger.info(f"已加载 {len(mcp_servers)} 个MCP服务器配置")
            
        except Exception as e:
            logger.error(f"加载预设MCP配置失败: {e}")
            raise SageHTTPException(
                status_code=500,
                detail="加载预设MCP配置失败",
                error_detail=str(e)
            )
    
    async def _load_preset_agent_config(self, config_path: str):
        """加载预设Agent配置"""
        if not config_path or not os.path.exists(config_path):
            logger.warning(f"预设Agent配置文件不存在: {config_path}")
            return
        
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
            
            # 处理旧格式配置（单个agent）
            if 'systemPrefix' in config or 'systemContext' in config:
                # 这是旧格式，保存为default agent
                await self.save_agent_config('default', 'Default Agent', config)
                logger.info("已加载默认Agent配置（旧格式）")
            else:
                # 新格式，包含多个agents
                count = 0
                for agent_id, agent_config in config.items():
                    if isinstance(agent_config, dict):
                        name = agent_config.get('name', f'Agent {agent_id}')
                        await self.save_agent_config(agent_id, name, agent_config)
                        count += 1
                
                logger.info(f"已加载 {count} 个Agent配置")
            
        except Exception as e:
            logger.error(f"加载预设Agent配置失败: {e}")
            raise SageHTTPException(
                status_code=500,
                detail="加载预设Agent配置失败",
                error_detail=str(e)
            )
    
    # ============= MCP服务器验证方法 =============
    
    async def validate_and_cleanup_mcp_servers(self, tool_manager):
        """验证MCP服务器列表，移除不可用的服务器"""
        logger.info("开始验证MCP服务器可用性")
        
        servers = await self.get_all_mcp_servers()
        removed_count = 0
        
        for server in servers:
            try:
                # 尝试注册MCP服务器来验证可用性
                success = await tool_manager.register_mcp_server(server.name, server.config)
                if not success:
                    # 如果注册失败，从数据库中移除
                    await self.delete_mcp_server(server.name)
                    removed_count += 1
                    logger.warning(f"MCP服务器不可用，已移除: {server.name}")
            except Exception as e:
                # 如果验证过程中出错，也移除该服务器
                await self.delete_mcp_server(server.name)
                removed_count += 1
                logger.error(f"MCP服务器验证失败，已移除: {server.name}, 错误: {e}")
        
        logger.info(f"MCP服务器验证完成，移除了 {removed_count} 个不可用的服务器")