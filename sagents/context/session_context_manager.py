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
        # 线程本地存储作为fallback
        self._local = threading.local()
    
    def set_session_id(self, session_id: str):
        """设置当前上下文的session ID"""
        try:
            # 优先使用contextvars（支持异步）
            self._session_id_var.set(session_id)
        except LookupError:
            # fallback到线程本地存储
            self._local.session_id = session_id
    
    def get_session_id(self) -> Optional[str]:
        """获取当前上下文的session ID"""
        try:
            # 优先从contextvars获取
            session_id = self._session_id_var.get()
            if session_id is not None:
                return session_id
        except LookupError:
            pass
        
        # fallback到线程本地存储
        return getattr(self._local, 'session_id', None)
    
    def clear_session_id(self):
        """清除当前上下文的session ID"""
        try:
            self._session_id_var.set(None)
        except LookupError:
            pass
        
        if hasattr(self._local, 'session_id'):
            delattr(self._local, 'session_id')
    
    @contextmanager
    def session_context(self, session_id: str):
        """同步Session上下文管理器
        
        使用方式:
        with session_manager.session_context("session_123"):
            logger.info("这条日志会自动携带session_123")
        """
        old_session_id = self.get_session_id()
        try:
            self.set_session_id(session_id)
            yield session_id
        finally:
            if old_session_id is not None:
                self.set_session_id(old_session_id)
            else:
                self.clear_session_id()
    
    @asynccontextmanager
    async def async_session_context(self, session_id: str):
        """异步Session上下文管理器
        
        使用方式:
        async with session_manager.async_session_context("session_123"):
            logger.info("这条日志会自动携带session_123")
        """
        old_session_id = self.get_session_id()
        try:
            self.set_session_id(session_id)
            yield session_id
        finally:
            if old_session_id is not None:
                self.set_session_id(old_session_id)
            else:
                self.clear_session_id()

# 全局实例
session_manager = SessionContextManager()
