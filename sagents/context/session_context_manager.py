#!/usr/bin/env python3
"""
Session上下文管理器
用于在多session环境下正确识别当前session，支持同步和异步环境
"""

import threading
from typing import Optional
from contextlib import contextmanager, asynccontextmanager
import contextvars

class SessionContextManager:
    """Session上下文管理器，支持同步和异步环境"""
    
    def __init__(self):
        # 使用contextvars支持异步环境
        self._session_id_var: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
            'session_id', default=None
        )
    
    def set_session_id(self, session_id: str):
        """设置当前上下文的session ID"""
        return self._session_id_var.set(session_id)
    
    def reset_session_id(self, token):
        """重置session ID到之前的状态"""
        self._session_id_var.reset(token)
    
    def get_session_id(self) -> Optional[str]:
        """获取当前上下文的session ID"""
        return self._session_id_var.get()
    
    def clear_session_id(self):
        """清除当前上下文的session ID"""
        self._session_id_var.set(None)
    
    @contextmanager
    def session_context(self, session_id: str):
        """同步Session上下文管理器
        
        使用方式:
        with session_manager.session_context("session_123"):
            logger.info("这条日志会自动携带session_123")
        """
        token = self.set_session_id(session_id)
        try:
            yield session_id
        finally:
            self.reset_session_id(token)
    
    @asynccontextmanager
    async def async_session_context(self, session_id: str):
        """异步Session上下文管理器
        
        使用方式:
        async with session_manager.async_session_context("session_123"):
            logger.info("这条日志会自动携带session_123")
        """
        token = self.set_session_id(session_id)
        try:
            yield session_id
        finally:
            self.reset_session_id(token)

# 全局实例
session_manager = SessionContextManager()
