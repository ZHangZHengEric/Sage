import asyncio
import json
import os
from contextlib import asynccontextmanager
from functools import wraps
from typing import Optional

from ...core.exceptions import SageHTTPException
from ...core.config import StartupConfig
from sqlalchemy import text
from sqlalchemy.exc import OperationalError, InterfaceError
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from loguru import logger


def db_retry(max_retries: int = 3, delay: float = 1.0):
    """
    数据库操作重试装饰器
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            last_err = None
            for attempt in range(max_retries):
                try:
                    return await func(*args, **kwargs)
                except (OperationalError, InterfaceError) as e:
                    last_err = e
                    logger.warning(f"数据库操作异常 (尝试 {attempt + 1}/{max_retries}): {e}")
                    if attempt < max_retries - 1:
                        await asyncio.sleep(delay)
            
            # 重试耗尽，抛出 SageHTTPException
            logger.error(f"数据库操作最终失败: {last_err}")
            raise SageHTTPException(
                status_code=500,
                detail="数据库操作失败",
                error_detail=str(last_err)
            )
        return wrapper
    return decorator


class SessionManager:
    """
    异步数据库会话管理器
    支持 SQLite 文件 / 内存数据库和 MySQL
    """

    def __init__(self, cfg: StartupConfig):
        self.cfg = cfg
        self.db_type = cfg.db_type
        self.db_path = cfg.db_path
        self._lock = asyncio.Lock()

        self._engine_name = "sqlite"
        self._engine = None
        self._SessionLocal: Optional[async_sessionmaker] = None

        # 数据库初始化
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
        """
        初始化数据库连接和 session 工厂
        """
        try:
            async with self._lock:
                if self._engine_name == "mysql":
                    from urllib.parse import quote_plus

                    user = self.mysql_config.get("user", "")
                    password = quote_plus(self.mysql_config.get("password", ""))
                    host = self.mysql_config.get("host", "127.0.0.1")
                    port = int(self.mysql_config.get("port", 3306))
                    database = self.mysql_config.get("database", "")
                    charset = self.mysql_config.get("charset", "utf8mb4")

                    url = f"mysql+aiomysql://{user}:{password}@{host}:{port}/{database}?charset={charset}"
                    self._engine = create_async_engine(
                        url,
                        future=True,
                        pool_size=100,
                        max_overflow=50,
                        pool_recycle=1800,
                        pool_timeout=30,
                        pool_pre_ping=True,
                        json_serializer=lambda obj: json.dumps(obj, ensure_ascii=False),
                        json_deserializer=json.loads,
                    )
                else:
                    engine_kwargs = {
                        "pool_recycle": 1800,
                        "pool_pre_ping": True,
                        "json_serializer": lambda obj: json.dumps(
                            obj, ensure_ascii=False
                        ),
                        "json_deserializer": json.loads,
                    }

                    if self.db_file == ":memory:":
                        from sqlalchemy.pool import StaticPool

                        url = "sqlite+aiosqlite:///:memory:"
                        engine_kwargs.update(
                            {
                                "poolclass": StaticPool,
                                "connect_args": {"check_same_thread": False},
                            }
                        )
                    else:
                        url = f"sqlite+aiosqlite:///{self.db_file}"

                    self._engine = create_async_engine(
                        url, future=True, **engine_kwargs
                    )

                self._SessionLocal = async_sessionmaker(
                    bind=self._engine,
                    autoflush=False,
                    autocommit=False,
                    expire_on_commit=False,
                )

                # 立即验证连接
                if self._engine_name == "mysql":
                    try:
                        async with self._engine.connect() as conn:
                            await conn.execute(text("SELECT 1"))
                    except Exception as e:
                        logger.error(f"MySQL 连接验证失败: {e}")
                        raise e

                logger.debug(f"数据库连接初始化完成 ({self._engine_name})")

        except Exception as e:
            err_msg = str(e)
            logger.error(f"数据库初始化失败: {err_msg}")

            # 提供更友好的错误提示
            hint = ""
            if (
                "Name or service not known" in err_msg
                or "gaierror" in err_msg
                or "Can't connect to MySQL server" in err_msg
            ):
                hint = "可能是数据库 Host 配置错误，请检查 mysql_host"
            elif "Access denied" in err_msg:
                hint = "可能是数据库用户名或密码错误"
            elif "Connection refused" in err_msg:
                hint = "可能是数据库端口错误或服务未启动"

            if hint:
                logger.error(f"提示: {hint}")

            raise SageHTTPException(
                status_code=500,
                detail="数据库初始化失败",
                error_detail=f"{err_msg} | {hint}",
            )

    async def close(self):
        """
        关闭数据库连接
        """
        async with self._lock:
            if self._engine:
                await self._engine.dispose()
                self._engine = None

    @asynccontextmanager
    async def get_session(self, autocommit: bool = True):
        """
        获取异步数据库会话
        - 适配 StreamingResponse / 高并发
        - 正确处理 CancelledError
        """
        if not self._SessionLocal or not self._engine:
            raise SageHTTPException(
                status_code=500,
                detail="数据库未初始化",
                error_detail="SQLAlchemy 引擎或会话工厂不存在",
            )

        session: AsyncSession = self._SessionLocal()
        cancelled = False

        try:
            yield session

            # ⚠️ 如果 Task 已被 cancel，不要再 commit
            if autocommit and not cancelled:
                await session.commit()

        except asyncio.CancelledError:
            # ✅ 标记取消，但不再尝试 rollback（连接可能已不可用）
            cancelled = True
            raise

        except (OperationalError, InterfaceError) as e:
            # ✅ aiomysql 在取消时抛 InterfaceError: Cancelled during execution
            if "Cancelled during execution" in str(e):
                cancelled = True
                logger.debug(f"数据库操作被取消: {e}")
                raise asyncio.CancelledError() from e

            # 正常数据库异常
            try:
                await session.rollback()
            except Exception:
                pass
            raise

        except Exception as e:
            try:
                await session.rollback()
            except Exception:
                pass

            logger.error(f"数据库操作失败: {e}")
            raise SageHTTPException(
                status_code=500,
                detail="数据库操作失败",
                error_detail=str(e),
            )

        finally:
            # ✅ close 必须 shield，但取消时允许直接放弃连接
            try:
                await asyncio.shield(session.close())
            except asyncio.CancelledError:
                pass
            except (OperationalError, InterfaceError) as e:
                # 忽略因取消导致的 InterfaceError
                if "Cancelled during execution" in str(e):
                    pass
                else:
                    logger.error(f"关闭 Session 失败 (DB Error): {e}")
            except Exception as e:
                logger.error(f"关闭 Session 失败: {e}")


# ===== 全局 DB 管理 =====
DB_MANAGER: Optional[SessionManager] = None


async def init_db_client(cfg: StartupConfig) -> Optional[SessionManager]:
    """
    初始化全局数据库客户端
    """
    global DB_MANAGER
    if DB_MANAGER is not None:
        return DB_MANAGER

    # MySQL 参数检查
    if cfg.db_type == "mysql":
        required = [
            cfg.mysql_host,
            cfg.mysql_port,
            cfg.mysql_user,
            cfg.mysql_password,
            cfg.mysql_database,
        ]
        if not all(required):
            logger.warning("MySQL 参数不足，未初始化数据库客户端")
            return None

    mgr = SessionManager(cfg)
    await mgr.init_conn()
    DB_MANAGER = mgr
    return DB_MANAGER


async def get_global_db() -> SessionManager:
    """
    获取全局数据库客户端
    """
    global DB_MANAGER
    if DB_MANAGER is None:
        raise SageHTTPException(
            status_code=500,
            detail="全局数据库管理器未设置",
            error_detail="请在项目启动时初始化数据库客户端",
        )
    return DB_MANAGER


async def close_db_client() -> None:
    """
    关闭全局数据库客户端
    """
    global DB_MANAGER
    try:
        if DB_MANAGER is not None:
            await DB_MANAGER.close()
    finally:
        DB_MANAGER = None
