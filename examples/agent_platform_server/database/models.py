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



class Conversation:
    """会话数据模型"""
    
    def __init__(self, user_id: str, session_id: str, agent_id: str, agent_name: str, title: str, messages: List[Dict[str, Any]],
                 created_at: Optional[str] = None, updated_at: Optional[str] = None):
        self.user_id = user_id
        self.session_id = session_id
        self.agent_id = agent_id
        self.agent_name = agent_name
        self.title = title
        self.messages = messages
        self.created_at = created_at or datetime.now().isoformat()
        self.updated_at = updated_at or datetime.now().isoformat()
    
    @classmethod
    def create_table(cls, cursor: sqlite3.Cursor):
        """创建会话表"""
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS conversations (
                session_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                agent_id TEXT NOT NULL,
                agent_name TEXT NOT NULL,
                title TEXT NOT NULL,
                messages TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        ''')
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            'user_id': self.user_id,
            'session_id': self.session_id,
            'agent_id': self.agent_id,
            'agent_name': self.agent_name,
            'title': self.title,
            'messages': self.messages,
            'created_at': self.created_at,
            'updated_at': self.updated_at
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Conversation':
        """从字典创建实例"""
        return cls(
            user_id=data['user_id'],
            session_id=data['session_id'],
            agent_id=data['agent_id'],
            agent_name=data['agent_name'],
            title=data['title'],
            messages=data['messages'],
            created_at=data.get('created_at'),
            updated_at=data.get('updated_at')
        )
    
    def save(self, cursor: sqlite3.Cursor):
        """保存到数据库"""
        self.updated_at = datetime.now().isoformat()
        cursor.execute('''
            INSERT OR REPLACE INTO conversations (session_id, user_id, agent_id, agent_name, title, messages, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (self.session_id, self.user_id, self.agent_id, self.agent_name, self.title, 
              json.dumps(self.messages), self.created_at, self.updated_at))
    
    @classmethod
    def get_by_session_id(cls, cursor: sqlite3.Cursor, session_id: str) -> Optional['Conversation']:
        """根据会话ID获取会话"""
        cursor.execute('''
            SELECT session_id, user_id, agent_id, agent_name, title, messages, created_at, updated_at 
            FROM conversations WHERE session_id = ?
        ''', (session_id,))
        row = cursor.fetchone()
        if row:
            return cls(
                user_id=row[1],
                session_id=row[0],
                agent_id=row[2],
                agent_name=row[3],
                title=row[4],
                messages=json.loads(row[5]),
                created_at=row[6],
                updated_at=row[7]
            )
        return None
    
    @classmethod
    def get_all(cls, cursor: sqlite3.Cursor) -> List['Conversation']:
        """获取所有会话"""
        cursor.execute('''
            SELECT session_id, user_id, agent_id, agent_name, title, messages, created_at, updated_at 
            FROM conversations ORDER BY updated_at DESC
        ''')
        rows = cursor.fetchall()
        return [cls(
            user_id=row[1],
            session_id=row[0],
            agent_id=row[2],
            agent_name=row[3],
            title=row[4],
            messages=json.loads(row[5]),
            created_at=row[6],
            updated_at=row[7]
        ) for row in rows]
    
    @classmethod
    def get_by_agent_id(cls, cursor: sqlite3.Cursor, agent_id: str) -> List['Conversation']:
        """根据Agent ID获取会话列表"""
        cursor.execute('''
            SELECT session_id, user_id, agent_id, agent_name, title, messages, created_at, updated_at 
            FROM conversations WHERE agent_id = ? ORDER BY updated_at DESC
        ''', (agent_id,))
        rows = cursor.fetchall()
        return [cls(
            user_id=row[1],
            session_id=row[0],
            agent_id=row[2],
            agent_name=row[3],
            title=row[4],
            messages=json.loads(row[5]),
            created_at=row[6],
            updated_at=row[7]
        ) for row in rows]
    
    @classmethod
    def get_paginated(cls, cursor: sqlite3.Cursor, page: int = 1, page_size: int = 10, 
                     user_id: Optional[str] = None, search: Optional[str] = None, 
                     agent_id: Optional[str] = None, sort_by: str = "date") -> tuple[List['Conversation'], int]:
        """分页获取会话列表
        
        Args:
            cursor: 数据库游标
            page: 页码，从1开始
            page_size: 每页数量
            user_id: 可选的用户ID过滤
            search: 可选的搜索关键词
            agent_id: 可选的Agent ID过滤
            sort_by: 排序方式 (date, title, messages)
            
        Returns:
            tuple: (会话列表, 总数量)
        """
        # 构建查询条件
        where_conditions = []
        params = []
        
        if user_id:
            where_conditions.append("user_id = ?")
            params.append(user_id)
            
        if agent_id:
            where_conditions.append("agent_id = ?")
            params.append(agent_id)
            
        if search:
            where_conditions.append("(title LIKE ? OR messages LIKE ?)")
            search_param = f"%{search}%"
            params.extend([search_param, search_param])
        
        where_clause = "WHERE " + " AND ".join(where_conditions) if where_conditions else ""
        
        # 获取总数量
        count_sql = f"SELECT COUNT(*) FROM conversations {where_clause}"
        cursor.execute(count_sql, params)
        total_count = cursor.fetchone()[0]
        
        # 构建排序条件
        order_clause = "ORDER BY updated_at DESC"  # 默认按更新时间排序
        if sort_by == "title":
            order_clause = "ORDER BY title ASC"
        elif sort_by == "messages":
            order_clause = "ORDER BY LENGTH(messages) DESC"
        
        # 计算偏移量
        offset = (page - 1) * page_size
        
        # 获取分页数据
        data_sql = f'''
            SELECT session_id, user_id, agent_id, agent_name, title, messages, created_at, updated_at 
            FROM conversations {where_clause}
            {order_clause}
            LIMIT ? OFFSET ?
        '''
        params.extend([page_size, offset])
        cursor.execute(data_sql, params)
        rows = cursor.fetchall()
        
        conversations = [cls(
            user_id=row[1],
            session_id=row[0],
            agent_id=row[2],
            agent_name=row[3],
            title=row[4],
            messages=json.loads(row[5]),
            created_at=row[6],
            updated_at=row[7]
        ) for row in rows]
        
        return conversations, total_count

    @classmethod
    def delete_by_session_id(cls, cursor: sqlite3.Cursor, session_id: str) -> bool:
        """根据会话ID删除会话"""
        cursor.execute('DELETE FROM conversations WHERE session_id = ?', (session_id,))
        return cursor.rowcount > 0
    
    def add_message(self, message: Dict[str, Any]):
        """添加消息到会话"""
        if not isinstance(self.messages, list):
            self.messages = []
        self.messages.append(message)
        self.updated_at = datetime.now().isoformat()
    
    def update_title(self, title: str):
        """更新会话标题"""
        self.title = title
        self.updated_at = datetime.now().isoformat()
    
    def get_message_count(self) -> Dict[str, int]:
        """获取用户输入数量和agent回复数量"""
        if not isinstance(self.messages, list):
            return {"user_count": 0, "agent_count": 0}
        
        user_count = 0
        agent_count = 0
        
        for message in self.messages:
            if isinstance(message, dict) and 'role' in message:
                role = message['role'].lower()
                if role == 'user':
                    user_count += 1
                elif role in ['assistant', 'agent']:
                    agent_count += 1
        
        return {"user_count": user_count, "agent_count": agent_count}
    