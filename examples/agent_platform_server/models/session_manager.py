"""
数据库管理器

提供数据库的连接、初始化和管理功能。
支持：
- SQLite 文件模式与内存模式
- MySQL（通过传入 db_type = "mysql" 并提供连接配置）
"""

from re import A
from sqlalchemy.ext.asyncio.session import AsyncSession


import os
import json
import asyncio
from urllib.parse import urlparse
from typing import Dict, Any, Optional
from contextlib import asynccontextmanager
from sagents.utils.logger import logger

from common.exceptions import SageHTTPException

from sqlalchemy.ext.asyncio import (
    create_async_engine,
    async_sessionmaker,
    AsyncSession,
)


from .base import Base


class SessionManager:
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
        self._lock = asyncio.Lock()

        self._engine_name = "sqlite"  # 默认引擎名，用于日志
        self._engine = None
        self._SessionLocal: Optional[async_sessionmaker[AsyncSession]] = None

        if db_type == "file":
            # 确保数据库目录存在
            os.makedirs(db_path, exist_ok=True)
            self.db_file = os.path.join(db_path, "agent_platform.db")
            logger.debug(f"使用文件数据库: {self.db_file}")
        elif db_type == "memory":
            self.db_file = ":memory:"
            logger.debug("使用内存数据库")
        elif db_type == "mysql":
            self._engine_name = "mysql"
            self.db_file = None
            self.mysql_config = self._parse_mysql_config(db_path)
            logger.debug(
                f"使用MySQL数据库: {self.mysql_config.get('host')}:{self.mysql_config.get('port')} / {self.mysql_config.get('database')}"
            )
        else:
            raise SageHTTPException(
                status_code=400,
                detail="不支持的数据库类型",
                error_detail=f"db_type={db_type}",
            )

    async def init_conn(self):
        """初始化数据库连接和表结构，并在提供预设配置时进行首次数据加载"""
        try:
            async with self._lock:
                # 创建 SQLAlchemy 引擎
                if self._engine_name == "mysql":
                    user = self.mysql_config.get("user", "")
                    password = self.mysql_config.get("password", "")
                    host = self.mysql_config.get("host", "127.0.0.1")
                    port = int(self.mysql_config.get("port", 3306))
                    database = self.mysql_config.get("database", "")
                    charset = self.mysql_config.get("charset", "utf8mb4")
                    url = f"mysql+aiomysql://{user}:{password}@{host}:{port}/{database}?charset={charset}"
                    self._engine = create_async_engine(
                        url,
                        future=True,
                        json_serializer=lambda obj: json.dumps(obj, ensure_ascii=False),
                        json_deserializer=json.loads,
                    )
                else:
                    if self.db_file == ":memory:":
                        url = "sqlite+aiosqlite:///:memory:"
                    else:
                        url = f"sqlite+aiosqlite:///{self.db_file}"
                    self._engine = create_async_engine(
                        url,
                        future=True,
                        json_serializer=lambda obj: json.dumps(obj, ensure_ascii=False),
                        json_deserializer=json.loads,
                    )
                # 创建 AsyncSession 工厂
                self._SessionLocal = async_sessionmaker[AsyncSession](
                    bind=self._engine,
                    autoflush=False,
                    autocommit=False,
                    expire_on_commit=False,
                )
                # 创建表结构（异步）
                async with self._engine.begin() as conn:
                    await conn.run_sync(Base.metadata.create_all)
                logger.debug(f"数据库初始化完成 ({self._engine_name})")

        except Exception as e:
            logger.error(f"数据库初始化失败: {e}")
            raise SageHTTPException(
                status_code=500, detail="数据库初始化失败", error_detail=str(e)
            )

    async def init_data(
        self, preset_mcp_config: str = None, preset_agent_config: str = None
    ):
        """初始化数据库数据（仅在空数据库时加载预设配置）"""
        if await self._should_initialize_data():
            await self._load_preset_mcp_config(preset_mcp_config)
            await self._load_preset_agent_config(preset_agent_config)
            logger.debug("数据库预加载完成")
        else:
            logger.debug("数据库已存在数据，跳过预加载")

    async def _should_initialize_data(self) -> bool:
        """检查是否需要初始化数据库数据：内存模式始终初始化；文件模式需空库"""
        if self.db_type == "memory":
            return True
        from .mcp_server import MCPServerDao
        from .agent import AgentConfigDao

        mcp_server_dao = await MCPServerDao.create()
        mcp_servers = await mcp_server_dao.get_all()
        agent_config_dao = await AgentConfigDao.create()
        agent_configs = await agent_config_dao.get_all()
        return len(mcp_servers) == 0 and len(agent_configs) == 0

    async def _load_preset_mcp_config(self, config_path: str):
        """加载预设 MCP 配置到数据库"""
        if not config_path or not os.path.exists(config_path):
            logger.warning(f"预设MCP配置文件不存在: {config_path}")
            return
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                config = json.load(f)
            mcp_servers = config.get("mcpServers", {})
            from .mcp_server import MCPServerDao

            mcp_server_dao = await MCPServerDao.create()
            for name, server_config in mcp_servers.items():
                await mcp_server_dao.save_mcp_server(name, server_config)
            logger.info(f"已加载 {len(mcp_servers)} 个MCP服务器配置")
        except Exception as e:
            logger.error(f"加载预设MCP配置失败: {e}")
            raise SageHTTPException(
                status_code=500, detail="加载预设MCP配置失败", error_detail=str(e)
            )

    async def _load_preset_agent_config(self, config_path: str):
        """加载预设 Agent 配置到数据库（兼容旧/新格式）"""
        if not config_path or not os.path.exists(config_path):
            logger.warning(f"预设Agent配置文件不存在: {config_path}")
            return
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                config = json.load(f)
            # 旧格式（单个 agent）
            from .agent import AgentConfigDao, Agent

            agent_config_dao = await AgentConfigDao.create()
            if "systemPrefix" in config or "systemContext" in config:
                obj = Agent(agent_id="default", name="Default Agent", config=config)
                await agent_config_dao.save(obj)
                logger.info("已加载默认Agent配置（旧格式）")
            else:
                # 新格式（多个 agents）
                count = 0
                for agent_id, agent_config in config.items():
                    if isinstance(agent_config, dict):
                        name = agent_config.get("name", f"Agent {agent_id}")
                        obj = Agent(agent_id=agent_id, name=name, config=agent_config)
                        await agent_config_dao.save(obj)
                        count += 1
                logger.info(f"已加载 {count} 个Agent配置")
        except Exception as e:
            logger.error(f"加载预设Agent配置失败: {e}")
            raise SageHTTPException(
                status_code=500, detail="加载预设Agent配置失败", error_detail=str(e)
            )

    async def close(self):
        """关闭数据库连接"""
        async with self._lock:
            if self._engine:
                self._engine.dispose()
                self._engine = None

    @asynccontextmanager
    async def get_session(self):
        async with self._lock:
            if not self._SessionLocal or not self._engine:
                raise SageHTTPException(
                    status_code=500,
                    detail="数据库未初始化",
                    error_detail="SQLAlchemy 引擎或会话工厂不存在",
                )
            session: AsyncSession = self._SessionLocal()
            try:
                yield session
                await session.commit()
            except Exception as e:
                await session.rollback()
                logger.error(f"数据库操作失败: {e}")
                raise SageHTTPException(
                    status_code=500, detail="数据库操作失败", error_detail=str(e)
                )
            finally:
                await session.close()

    # ============= MySQL 配置解析 =============
    def _parse_mysql_config(self, db_path: str) -> Dict[str, Any]:
        """解析 MySQL 连接配置。兼容 DSN、JSON 文件与环境变量。

        - DSN: mysql://user:pass@host:port/database?charset=utf8mb4
        - JSON 文件路径: 指向包含上述字段的 JSON 文件
        - 环境变量: MYSQL_HOST, MYSQL_PORT, MYSQL_USER, MYSQL_PASSWORD, MYSQL_DATABASE, MYSQL_CHARSET
        """
        cfg: Dict[str, Any] = {}

        # DSN 字符串
        if isinstance(db_path, str) and db_path.startswith("mysql://"):
            parsed = urlparse(db_path)
            cfg["user"] = parsed.username or ""
            cfg["password"] = parsed.password or ""
            cfg["host"] = parsed.hostname or "127.0.0.1"
            cfg["port"] = parsed.port or 3306
            # 路径中的数据库名可能带前导斜杠
            cfg["database"] = (parsed.path or "").lstrip("/")
            # 解析查询参数中的 charset
            query = parsed.query or ""
            if "charset=" in query:
                try:
                    cfg["charset"] = query.split("charset=")[1].split("&")[0]
                except Exception:
                    pass
            return cfg

        # JSON 文件路径
        if (
            isinstance(db_path, str)
            and os.path.exists(db_path)
            and os.path.isfile(db_path)
        ):
            try:
                with open(db_path, "r", encoding="utf-8") as f:
                    file_cfg = json.load(f)
                for key in ["host", "port", "user", "password", "database", "charset"]:
                    if key in file_cfg:
                        cfg[key] = file_cfg[key]
                if "port" in cfg:
                    cfg["port"] = int(cfg["port"])
                return cfg
            except Exception as e:
                logger.warning(f"解析MySQL配置文件失败: {e}")

        # 环境变量兜底
        cfg["host"] = os.environ.get("MYSQL_HOST", "127.0.0.1")
        cfg["port"] = int(os.environ.get("MYSQL_PORT", "3306"))
        cfg["user"] = os.environ.get("MYSQL_USER", "")
        cfg["password"] = os.environ.get("MYSQL_PASSWORD", "")
        cfg["database"] = os.environ.get("MYSQL_DATABASE", "")
        cfg["charset"] = os.environ.get("MYSQL_CHARSET", "utf8mb4")
        return cfg
