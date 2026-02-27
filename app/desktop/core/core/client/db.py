import asyncio
import json
import os
from contextlib import asynccontextmanager
from functools import wraps
from typing import Optional
from pathlib import Path

from loguru import logger
from sqlalchemy.exc import InterfaceError, OperationalError
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

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
            
            logger.error(f"数据库操作最终失败: {last_err}")
            raise Exception(f"数据库操作失败: {last_err}")
        return wrapper
    return decorator


class SessionManager:
    """
    异步数据库会话管理器
    支持 SQLite 文件 / 内存数据库
    """

    def __init__(self):
        self._lock = asyncio.Lock()
        self._engine = None
        self._SessionLocal: Optional[async_sessionmaker] = None
        sage_home = Path.home() / ".sage"
        self.db_file = os.path.join(sage_home, "sage.db")

    async def init_conn(self):
        """
        初始化数据库连接和 session 工厂
        """
        try:
            async with self._lock:
                engine_kwargs = {
                    "pool_recycle": 1800,
                    "pool_pre_ping": True,
                    "json_serializer": lambda obj: json.dumps(
                        obj, ensure_ascii=False
                    ),
                    "json_deserializer": json.loads,
                }
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

        except Exception as e:
            err_msg = str(e)
            logger.error(f"数据库初始化失败: {err_msg}")
            raise Exception(f"数据库初始化失败: {err_msg}")

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
            raise Exception("数据库未初始化: SQLAlchemy 引擎或会话工厂不存在")

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
            raise Exception(f"数据库操作失败: {e}")

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


async def init_db_client() -> Optional[SessionManager]:
    """
    初始化全局数据库客户端
    """
    global DB_MANAGER
    if DB_MANAGER is not None:
        return DB_MANAGER

    mgr = SessionManager()
    await mgr.init_conn()
    DB_MANAGER = mgr
    return DB_MANAGER


async def get_global_db() -> SessionManager:
    """
    获取全局数据库客户端
    """
    global DB_MANAGER
    if DB_MANAGER is None:
        raise Exception("全局数据库管理器未设置: 请在项目启动时初始化数据库客户端")
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
