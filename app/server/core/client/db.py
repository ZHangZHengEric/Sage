import asyncio
import json
import os
from contextlib import asynccontextmanager
from functools import wraps
from typing import Optional

from loguru import logger
from sqlalchemy import inspect, text, String, Integer, Boolean, DateTime, Float
from sqlalchemy.exc import InterfaceError, OperationalError
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from ...core.config import StartupConfig
from ...core.exceptions import SageHTTPException


def sync_database_schema(sync_conn, Base):
    """
    Check all registered tables and update schema if outdated.
    Tries to ALTER TABLE ADD COLUMN first.
    If that fails, it logs an error (does NOT drop table automatically to prevent data loss).
    """
    inspector = inspect(sync_conn)
    existing_tables = set(inspector.get_table_names())

    # Iterate over all defined models in Base.metadata
    for table_name, table in Base.metadata.tables.items():
        if table_name not in existing_tables:
            continue

        # Get actual columns
        actual_columns = {col['name'] for col in inspector.get_columns(table_name)}
        # Get expected columns from model
        expected_columns_map = {col.name: col for col in table.columns}
        expected_columns = set(expected_columns_map.keys())

        # Check for missing columns
        missing_columns = expected_columns - actual_columns

        if missing_columns:
            logger.info(f"[DB] 检测到表 '{table_name}' 缺少列: {missing_columns}")

            for col_name in missing_columns:
                col = expected_columns_map[col_name]
                try:
                    # Determine column type and default value
                    col_type = col.type.compile(sync_conn.dialect)
                    default_clause = ""

                    # Handle NOT NULL constraints by adding a default value
                    if not col.nullable:
                        if isinstance(col.type, String):
                            default_clause = " DEFAULT ''"
                        elif isinstance(col.type, Integer):
                            default_clause = " DEFAULT 0"
                        elif isinstance(col.type, Boolean):
                            default_clause = " DEFAULT 0"
                        elif isinstance(col.type, Float):
                            default_clause = " DEFAULT 0.0"
                        elif isinstance(col.type, DateTime):
                            # MySQL: use CURRENT_TIMESTAMP for DateTime default
                            # SQLite: use fixed timestamp string
                            if sync_conn.dialect.name == 'mysql':
                                default_clause = " DEFAULT CURRENT_TIMESTAMP"
                            else:
                                import datetime
                                now_str = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                                default_clause = f" DEFAULT '{now_str}'"

                    # Construct ALTER TABLE statement
                    sql = f"ALTER TABLE {table_name} ADD COLUMN {col_name} {col_type}{default_clause}"
                    logger.info(f"[DB] 尝试添加列: {sql}")
                    sync_conn.execute(text(sql))
                    logger.info(f"[DB] 成功添加列 '{col_name}' 到表 '{table_name}'")

                except Exception as e:
                    logger.error(f"[DB] 无法自动添加列 '{col_name}' 到表 '{table_name}': {e}")
                    # If ALTER fails, we could fallback to DROP, but let's be safe and just log error
                    # The user can manually drop if needed.
        else:
            logger.debug(f"[DB] 表 '{table_name}' 结构正常")


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
        self._lock = asyncio.Lock()

        self._engine_name = "sqlite"
        self._engine = None
        self._SessionLocal: Optional[async_sessionmaker] = None

        # 数据库初始化
        if self.db_type == "file":
            self.db_file = os.path.join("./agent_platform.db")
            logger.debug(f"使用file数据库, 数据地址: {self.db_file}")
        elif self.db_type == "memory":
            self.db_file = ":memory:"
            logger.debug("使用内存数据库")
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
            logger.debug(f"使用MySQL数据库: {self.mysql_config.get('host')}:{self.mysql_config.get('port')} / {self.mysql_config.get('database')}")
        else:
            raise SageHTTPException(
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
                    except OperationalError as e:
                        # 错误码 1049: Unknown database
                        if "1049" in str(e) or "Unknown database" in str(e):
                            logger.warning(f"数据库 '{database}' 不存在，尝试自动创建...")
                            try:
                                # 创建临时连接用于创建数据库
                                # 不指定数据库名进行连接
                                admin_url = f"mysql+aiomysql://{user}:{password}@{host}:{port}/?charset={charset}"
                                admin_engine = create_async_engine(
                                    admin_url,
                                    isolation_level="AUTOCOMMIT",
                                    future=True
                                )
                                
                                async with admin_engine.connect() as admin_conn:
                                    # 创建数据库
                                    await admin_conn.execute(text(f"CREATE DATABASE IF NOT EXISTS `{database}` CHARACTER SET {charset}"))
                                    logger.info(f"数据库 '{database}' 创建成功")
                                
                                await admin_engine.dispose()
                                
                                # 再次验证原连接
                                async with self._engine.connect() as conn:
                                    await conn.execute(text("SELECT 1"))
                            except Exception as create_e:
                                logger.error(f"自动创建数据库失败: {create_e}")
                                raise e  # 抛出原始连接错误
                        else:
                            logger.error(f"MySQL 连接验证失败: {e}")
                            raise e
                    except Exception as e:
                        logger.error(f"MySQL 连接验证失败: {e}")
                        raise e
                        
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
