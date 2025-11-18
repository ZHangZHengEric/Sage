import os
import json
import asyncio
from typing import Dict, Any, Optional
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    create_async_engine,
    async_sessionmaker,
    AsyncSession,
)
from sagents.utils.logger import logger
from common.exceptions import SageHTTPException
from config.settings import StartupConfig


class SessionManager:

    def __init__(self, cfg: StartupConfig):
        self.cfg = cfg
        self.db_type = cfg.db_type
        self.db_path = cfg.db_path
        self._lock = asyncio.Lock()

        self._engine_name = "sqlite"
        self._engine = None
        self._SessionLocal: Optional[async_sessionmaker[AsyncSession]] = None

        if self.db_type == "file":
            os.makedirs(self.db_path, exist_ok=True)
            self.db_file = os.path.join(self.db_path, "agent_platform.db")
            logger.info(f"使用文件数据库: {self.db_file}")
        elif self.db_type == "memory":
            self.db_file = ":memory:"
            logger.info("使用内存数据库")
        elif self.db_type == "mysql":
            self._engine_name = "mysql"
            self.db_file = None
            self.mysql_config = {
                "host": cfg.mysql_host,
                "port": int(cfg.mysql_port),
                "user": cfg.mysql_user,
                "password": cfg.mysql_password,
                "database": cfg.mysql_database,
                "charset": cfg.mysql_charset,
            }
            logger.info(
                f"使用MySQL数据库: {self.mysql_config.get('host')}:{self.mysql_config.get('port')} / {self.mysql_config.get('database')}"
            )
        else:
            raise SageHTTPException(
                status_code=400,
                detail="不支持的数据库类型",
                error_detail=f"db_type={self.db_type}",
            )

    async def init_conn(self):
        try:
            async with self._lock:
                if self._engine_name == "mysql":
                    user = self.mysql_config.get("user", "")
                    password = self.mysql_config.get("password", "")
                    host = self.mysql_config.get("host", "127.0.0.1")
                    from urllib.parse import quote_plus

                    password = quote_plus(password)
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

                self._SessionLocal = async_sessionmaker[AsyncSession](
                    bind=self._engine,
                    autoflush=False,
                    autocommit=False,
                    expire_on_commit=False,
                )

                logger.debug(f"数据库连接初始化完成 ({self._engine_name})")

        except Exception as e:
            logger.error(f"数据库初始化失败: {e}")
            raise SageHTTPException(
                status_code=500, detail="数据库初始化失败", error_detail=str(e)
            )

    async def close(self):
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


# ===== 全局 DB 管理 =====
DB_MANAGER: Optional[SessionManager] = None


async def init_db_client(cfg: StartupConfig) -> SessionManager:
    global DB_MANAGER
    if DB_MANAGER is not None:
        return DB_MANAGER
    if cfg.db_type == "mysql":
        required = [cfg.mysql_host, cfg.mysql_port, cfg.mysql_user, cfg.mysql_password, cfg.mysql_database]
        if not all(required):
            logger.warning("MySQL 参数不足，未初始化数据库客户端")
            return None
    mgr = SessionManager(cfg)
    await mgr.init_conn()
    DB_MANAGER = mgr
    return DB_MANAGER


async def get_global_db() -> SessionManager:
    global DB_MANAGER
    if DB_MANAGER is None:
        raise SageHTTPException(
            status_code=500,
            detail="全局数据库管理器未设置",
            error_detail="请在项目启动时初始化数据库客户端",
        )
    return DB_MANAGER


async def close_db_client() -> None:
    global DB_MANAGER
    try:
        if DB_MANAGER is not None:
            await DB_MANAGER.close()
    finally:
        DB_MANAGER = None
