"""Generic desktop database schema synchronization."""

import logging
from importlib import import_module

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text, inspect, text

from common.core.client.db import drop_undeclared_indexes, sync_missing_indexes
from common.models.base import Base

logger = logging.getLogger(__name__)

_DESKTOP_MODEL_MODULES = (
    "common.models.agent",
    "common.models.conversation",
    "common.models.file",
    "common.models.im_channel",
    "common.models.llm_provider",
    "common.models.mcp_server",
    "common.models.questionnaire",
    "common.models.system",
    "common.models.task",
    "common.models.token_usage",
    "common.models.user",
)


def ensure_desktop_models_registered():
    for module_name in _DESKTOP_MODEL_MODULES:
        import_module(module_name)


def _drop_unused_sqlite_columns(sync_conn, table_name, unused_columns):
    if sync_conn.dialect.name != "sqlite":
        return

    preparer = sync_conn.dialect.identifier_preparer
    quoted_table = preparer.quote(table_name)
    for col_name in sorted(unused_columns):
        quoted_col = preparer.quote(col_name)
        try:
            sql = f"ALTER TABLE {quoted_table} DROP COLUMN {quoted_col}"
            logger.info(f"[DB] 清理无用列: {sql}")
            sync_conn.execute(text(sql))
            logger.info(f"[DB] 已清理表 '{table_name}' 的无用列 '{col_name}'")
        except Exception as e:
            logger.error(
                f"[DB] 无法自动清理表 '{table_name}' 的无用列 '{col_name}': {e}"
            )


def sync_database_schema(sync_conn):
    """Align desktop SQLite tables with ORM metadata without business rules."""
    ensure_desktop_models_registered()
    inspector = inspect(sync_conn)
    existing_tables = set(inspector.get_table_names())

    for table_name, table in Base.metadata.tables.items():
        if table_name not in existing_tables:
            continue

        actual_columns = {col["name"] for col in inspector.get_columns(table_name)}
        expected_columns_map = {col.name: col for col in table.columns}
        missing_columns = set(expected_columns_map) - actual_columns

        if missing_columns:
            logger.info(f"[DB] 检测到表 '{table_name}' 缺少列: {missing_columns}")
        for col_name in missing_columns:
            col = expected_columns_map[col_name]
            try:
                col_type = col.type.compile(sync_conn.dialect)
                default_clause = ""
                if not col.nullable:
                    if isinstance(col.type, (String, Text)):
                        default_clause = " DEFAULT ''"
                    elif isinstance(col.type, Integer):
                        default_clause = " DEFAULT 0"
                    elif isinstance(col.type, Boolean):
                        default_clause = " DEFAULT 0"
                    elif isinstance(col.type, Float):
                        default_clause = " DEFAULT 0.0"
                    elif isinstance(col.type, DateTime):
                        import datetime

                        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        default_clause = f" DEFAULT '{now_str}'"

                sql = (
                    f"ALTER TABLE {table_name} ADD COLUMN "
                    f"{col_name} {col_type}{default_clause}"
                )
                logger.info(f"[DB] 尝试添加列: {sql}")
                sync_conn.execute(text(sql))
                logger.info(f"[DB] 成功添加列 '{col_name}' 到表 '{table_name}'")
            except Exception as e:
                logger.error(
                    f"[DB] 无法自动添加列 '{col_name}' 到表 '{table_name}': {e}"
                )

        unused_columns = actual_columns - set(expected_columns_map)
        if unused_columns:
            logger.info(f"[DB] 检测到表 '{table_name}' 存在无用列: {unused_columns}")
            _drop_unused_sqlite_columns(sync_conn, table_name, unused_columns)

    sync_missing_indexes(sync_conn, Base.metadata)
    drop_undeclared_indexes(sync_conn, Base.metadata)
