"""
Database schema management - handles table structure changes
"""

import logging
from typing import Dict, List, Set

from sqlalchemy import inspect, text, String, Integer, Boolean, DateTime, Float
from common.models.base import Base

logger = logging.getLogger(__name__)


def _migrate_agent_is_default(sync_conn):
    """
    迁移 agent_configs 表的 is_default 字段
    将第一个 Agent 设为默认（如果还没有默认 Agent）
    """
    try:
        # 检查是否有 Agent 已经是默认
        result = sync_conn.execute(
            text("SELECT COUNT(*) FROM agent_configs WHERE is_default = 1")
        )
        default_count = result.scalar()

        if default_count == 0:
            # 没有默认 Agent，将第一个（按创建时间）设为默认
            result = sync_conn.execute(
                text("SELECT agent_id FROM agent_configs ORDER BY created_at ASC LIMIT 1")
            )
            first_agent = result.fetchone()

            if first_agent:
                agent_id = first_agent[0]
                sync_conn.execute(
                    text("UPDATE agent_configs SET is_default = 1 WHERE agent_id = :agent_id"),
                    {"agent_id": agent_id}
                )
                logger.info(f"[DB] 已将 Agent '{agent_id}' 设为默认")
            else:
                logger.info("[DB] 没有 Agent 需要设置默认")
        else:
            logger.info(f"[DB] 已有 {default_count} 个默认 Agent，跳过迁移")

    except Exception as e:
        logger.error(f"[DB] 迁移 is_default 字段失败: {e}")


def sync_database_schema(sync_conn):
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
                            # SQLite doesn't strictly enforce types, but for DateTime we might want CURRENT_TIMESTAMP or similar
                            # However, SQLAlchemy DateTime usually maps to String or specific type in SQLite
                            # Let's try to be safe with a safe default or allow NULL temporarily?
                            # SQLite ALTER TABLE ADD COLUMN NOT NULL must have DEFAULT
                            import datetime
                            now_str = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                            default_clause = f" DEFAULT '{now_str}'"

                    # Construct ALTER TABLE statement
                    # SQLite syntax: ALTER TABLE table_name ADD COLUMN column_definition
                    sql = f"ALTER TABLE {table_name} ADD COLUMN {col_name} {col_type}{default_clause}"
                    logger.info(f"[DB] 尝试添加列: {sql}")
                    sync_conn.execute(text(sql))
                    logger.info(f"[DB] 成功添加列 '{col_name}' 到表 '{table_name}'")

                    # 如果是 is_default 列，执行数据迁移
                    if col_name == "is_default" and table_name == "agent_configs":
                        _migrate_agent_is_default(sync_conn)

                except Exception as e:
                    logger.error(f"[DB] 无法自动添加列 '{col_name}' 到表 '{table_name}': {e}")
                    # If ALTER fails, we could fallback to DROP, but let's be safe and just log error
                    # The user can manually drop if needed.
        else:
            logger.debug(f"[DB] 表 '{table_name}' 结构正常")
