"""
Database schema management - handles table structure changes
"""

import logging
from typing import Dict, List, Set

from sqlalchemy import inspect, text

logger = logging.getLogger(__name__)

# Define expected columns for each table
# If actual columns don't match expected, table will be dropped and recreated
TABLE_SCHEMAS: Dict[str, Set[str]] = {
    "im_channels": {"provider_type", "config", "created_at", "updated_at"},
    # Add other tables here if needed
    # "table_name": {"column1", "column2", ...},
}


def check_and_drop_outdated_tables(sync_conn):
    """
    Check all registered tables and drop if schema is outdated (missing required columns).
    Only drop table when columns are missing (new code needs them).
    Extra columns (old columns no longer needed) are ignored.
    This should be called before create_all() to ensure tables are recreated with new schema.
    """
    inspector = inspect(sync_conn)
    existing_tables = set(inspector.get_table_names())
    
    for table_name, expected_columns in TABLE_SCHEMAS.items():
        if table_name not in existing_tables:
            continue
        
        # Get actual columns
        actual_columns = {col['name'] for col in inspector.get_columns(table_name)}
        
        # Only check for missing columns (new code needs these columns)
        missing_columns = expected_columns - actual_columns
        
        if missing_columns:
            logger.info(f"[DB] 检测到表 '{table_name}' 缺少必要列: {missing_columns}")
            logger.info(f"[DB] 删除旧表 '{table_name}' 并重新创建")
            
            sync_conn.execute(text(f"DROP TABLE {table_name}"))
            logger.info(f"[DB] 表 '{table_name}' 已删除")
        else:
            # Extra columns are OK (backward compatible)
            extra_columns = actual_columns - expected_columns
            if extra_columns:
                logger.debug(f"[DB] 表 '{table_name}' 结构正常 (包含额外列: {extra_columns})")
            else:
                logger.debug(f"[DB] 表 '{table_name}' 结构正常")


def register_table_schema(table_name: str, columns: List[str]):
    """
    Register expected schema for a table.
    Can be called from model files to register their schema.
    """
    TABLE_SCHEMAS[table_name] = set(columns)
    logger.debug(f"[DB] 注册表结构: {table_name} -> {columns}")
