"""
数据库模型定义

定义MCP服务器和Agent配置的数据模型
"""

import sqlite3
import json
from datetime import datetime
from typing import Dict, Any, Optional, List


class MCPServer:
    """MCP服务器数据模型"""
    
    def __init__(self, name: str, config: Dict[str, Any], 
                 created_at: Optional[str] = None, updated_at: Optional[str] = None):
        self.name = name
        self.config = config
        self.created_at = created_at or datetime.now().isoformat()
        self.updated_at = updated_at or datetime.now().isoformat()
    
    @classmethod
    def create_table(cls, cursor: sqlite3.Cursor):
        """创建MCP服务器表"""
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS mcp_servers (
                name TEXT PRIMARY KEY,
                config TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        ''')
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            'name': self.name,
            'config': self.config,
            'created_at': self.created_at,
            'updated_at': self.updated_at
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'MCPServer':
        """从字典创建实例"""
        return cls(
            name=data['name'],
            config=data['config'],
            created_at=data.get('created_at'),
            updated_at=data.get('updated_at')
        )
    
    def save(self, cursor: sqlite3.Cursor):
        """保存到数据库"""
        self.updated_at = datetime.now().isoformat()
        cursor.execute('''
            INSERT OR REPLACE INTO mcp_servers (name, config, created_at, updated_at)
            VALUES (?, ?, ?, ?)
        ''', (self.name, json.dumps(self.config), self.created_at, self.updated_at))
    
    @classmethod
    def get_by_name(cls, cursor: sqlite3.Cursor, name: str) -> Optional['MCPServer']:
        """根据名称获取MCP服务器"""
        cursor.execute('SELECT name, config, created_at, updated_at FROM mcp_servers WHERE name = ?', (name,))
        row = cursor.fetchone()
        if row:
            return cls(
                name=row[0],
                config=json.loads(row[1]),
                created_at=row[2],
                updated_at=row[3]
            )
        return None
    
    @classmethod
    def get_all(cls, cursor: sqlite3.Cursor) -> List['MCPServer']:
        """获取所有MCP服务器"""
        cursor.execute('SELECT name, config, created_at, updated_at FROM mcp_servers ORDER BY created_at')
        rows = cursor.fetchall()
        return [cls(
            name=row[0],
            config=json.loads(row[1]),
            created_at=row[2],
            updated_at=row[3]
        ) for row in rows]
    
    @classmethod
    def delete_by_name(cls, cursor: sqlite3.Cursor, name: str) -> bool:
        """根据名称删除MCP服务器"""
        cursor.execute('DELETE FROM mcp_servers WHERE name = ?', (name,))
        return cursor.rowcount > 0


class AgentConfig:
    """Agent配置数据模型"""
    
    def __init__(self, agent_id: str, name: str, config: Dict[str, Any],
                 created_at: Optional[str] = None, updated_at: Optional[str] = None):
        self.agent_id = agent_id
        self.name = name
        self.config = config
        self.created_at = created_at or datetime.now().isoformat()
        self.updated_at = updated_at or datetime.now().isoformat()
    
    @classmethod
    def create_table(cls, cursor: sqlite3.Cursor):
        """创建Agent配置表"""
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS agent_configs (
                agent_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                config TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        ''')
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            'agent_id': self.agent_id,
            'name': self.name,
            'config': self.config,
            'created_at': self.created_at,
            'updated_at': self.updated_at
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'AgentConfig':
        """从字典创建实例"""
        return cls(
            agent_id=data['agent_id'],
            name=data['name'],
            config=data['config'],
            created_at=data.get('created_at'),
            updated_at=data.get('updated_at')
        )
    
    def save(self, cursor: sqlite3.Cursor):
        """保存到数据库"""
        self.updated_at = datetime.now().isoformat()
        cursor.execute('''
            INSERT OR REPLACE INTO agent_configs (agent_id, name, config, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
        ''', (self.agent_id, self.name, json.dumps(self.config), self.created_at, self.updated_at))
    
    @classmethod
    def get_by_id(cls, cursor: sqlite3.Cursor, agent_id: str) -> Optional['AgentConfig']:
        """根据ID获取Agent配置"""
        cursor.execute('SELECT agent_id, name, config, created_at, updated_at FROM agent_configs WHERE agent_id = ?', (agent_id,))
        row = cursor.fetchone()
        if row:
            return cls(
                agent_id=row[0],
                name=row[1],
                config=json.loads(row[2]),
                created_at=row[3],
                updated_at=row[4]
            )
        return None
    
    @classmethod
    def get_all(cls, cursor: sqlite3.Cursor) -> List['AgentConfig']:
        """获取所有Agent配置"""
        cursor.execute('SELECT agent_id, name, config, created_at, updated_at FROM agent_configs ORDER BY created_at')
        rows = cursor.fetchall()
        return [cls(
            agent_id=row[0],
            name=row[1],
            config=json.loads(row[2]),
            created_at=row[3],
            updated_at=row[4]
        ) for row in rows]
    
    @classmethod
    def delete_by_id(cls, cursor: sqlite3.Cursor, agent_id: str) -> bool:
        """根据ID删除Agent配置"""
        cursor.execute('DELETE FROM agent_configs WHERE agent_id = ?', (agent_id,))
        return cursor.rowcount > 0