import os
import logging
import inspect
import sys
import traceback
from datetime import datetime
from logging.handlers import RotatingFileHandler
from typing import Dict, Optional

class Logger:
    _instance = None
    _initialized = False
    
    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super(Logger, cls).__new__(cls)
        return cls._instance
    
    def __init__(self, log_dir='logs'):
        if Logger._initialized:
            return
            
        self.log_dir = log_dir
        os.makedirs(log_dir, exist_ok=True)
        
        # Create main logger
        self.logger = logging.getLogger('sage')
        self.logger.setLevel(logging.DEBUG)
        self.logger.propagate = False
        
        # Clear existing handlers to avoid duplicate logs
        if self.logger.handlers:
            self.logger.handlers.clear()
            
        # Console handler
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.DEBUG)
        console_format = logging.Formatter('%(asctime)s - %(levelname)s - [%(session_id)s] - [%(caller_filename)s:%(caller_lineno)d] - %(message)s')
        console_handler.setFormatter(console_format)
        
        # Global file handler (rotating) - 保留全局日志
        log_file = os.path.join(log_dir, f'sage_{datetime.now().strftime("%Y%m%d")}.log')
        file_handler = RotatingFileHandler(log_file, maxBytes=10*1024*1024, backupCount=5)
        file_handler.setLevel(logging.DEBUG)
        file_format = logging.Formatter('%(asctime)s - %(levelname)s - [%(session_id)s] - [%(caller_filename)s:%(caller_lineno)d] - %(message)s')
        file_handler.setFormatter(file_format)
        
        # Add handlers
        self.logger.addHandler(console_handler)
        self.logger.addHandler(file_handler)
        
        # Session-specific loggers cache
        self.session_loggers: Dict[str, logging.Logger] = {}
        
        Logger._initialized = True
    
    def _get_current_session_id(self) -> Optional[str]:
        """尝试获取当前session id"""
        try:
            # 优先从session上下文管理器获取
            from sagents.utils.session_local import session_manager
            session_id = session_manager.get_session_id()
            if session_id:
                return session_id
            
            # fallback: 尝试从session_context模块获取（保持向后兼容）
            import sagents.context.session_context as session_module
            
            # 获取当前线程ID
            import threading
            current_thread_id = threading.get_ident()
            
            # 遍历所有活跃session，找到匹配的线程ID
            for session_id, session_context in session_module._active_sessions.items():
                if hasattr(session_context, 'thread_id') and session_context.thread_id == current_thread_id:
                    return session_id
            
            return None
        except Exception:
            # 如果获取失败，返回None
            return None
    
    def _get_session_logger(self, session_id: str) -> logging.Logger:
        """获取或创建session专用的logger"""
        if session_id not in self.session_loggers:
            # 创建session专用logger
            session_logger = logging.getLogger(f'sage_session_{session_id}')
            session_logger.setLevel(logging.DEBUG)
            session_logger.propagate = False
            
            # 清除可能存在的handlers
            if session_logger.handlers:
                session_logger.handlers.clear()
            
            try:
                # 获取session workspace路径
                from sagents.context.session_context import get_session_context
                session_context = get_session_context(session_id)
                session_workspace = session_context.session_workspace
                
                # 创建session专用的日志文件 - 使用普通FileHandler以确保追加模式
                session_log_file = os.path.join(session_workspace, f'session_{session_id}.log')
                # 使用FileHandler的追加模式，而不是RotatingFileHandler
                session_file_handler = logging.FileHandler(session_log_file, mode='a', encoding='utf-8')
                session_file_handler.setLevel(logging.DEBUG)
                session_format = logging.Formatter('%(asctime)s - %(levelname)s - [%(caller_filename)s:%(caller_lineno)d] - %(message)s')
                session_file_handler.setFormatter(session_format)
                
                session_logger.addHandler(session_file_handler)
                
            except Exception as e:
                # 如果无法创建session专用日志文件，记录错误但不影响主要功能
                print(f"Warning: Failed to create session log file for {session_id}: {e}")
            
            self.session_loggers[session_id] = session_logger
        
        return self.session_loggers[session_id]
    
    def _log(self, level, message, explicit_session_id: Optional[str] = None):
        # Get caller frame info to include filename and line number
        # 使用inspect.stack获取调用栈，跳过前两层（_log方法和debug/info等方法）
        stack = inspect.stack()
        if len(stack) >= 3:
            caller_frame = stack[2][0]
            filename = os.path.basename(caller_frame.f_code.co_filename)
            lineno = caller_frame.f_lineno
        else:
            filename = 'unknown.py'
            lineno = 0
        
        # 获取session id：优先使用显式传递的，然后从上下文获取
        session_id = explicit_session_id or self._get_current_session_id() or 'NO_SESSION'
        
        # 准备extra信息
        extra_info = {
            'caller_filename': filename, 
            'caller_lineno': lineno,
            'session_id': session_id
        }
        
        # 记录到主logger（包含session id）
        log_method = getattr(self.logger, level)
        log_method(f"{message}", extra=extra_info)
        
        # 如果有session id，同时记录到session专用日志
        if session_id != 'NO_SESSION':
            try:
                session_logger = self._get_session_logger(session_id)
                session_log_method = getattr(session_logger, level)
                session_log_method(f"{message}", extra={'caller_filename': filename, 'caller_lineno': lineno})
            except Exception as e:
                # 如果session日志记录失败，不影响主要功能
                pass
    
    def debug(self, message, session_id: Optional[str] = None):
        self._log('debug', message, session_id)
    
    def info(self, message, session_id: Optional[str] = None):
        self._log('info', message, session_id)
    
    def warning(self, message, session_id: Optional[str] = None):
        self._log('warning', message, session_id)
    
    def error(self, message, session_id: Optional[str] = None):
        # 在错误日志中自动添加traceback
        try:
            # 获取当前异常信息
            exc_info = sys.exc_info()
            if exc_info[0] is not None:
                # 如果当前有异常，添加traceback
                tb_str = ''.join(traceback.format_exception(*exc_info))
                message = f"{message}\nTraceback:\n{tb_str}"
        except Exception:
            # 如果获取traceback失败，不影响日志记录
            pass
        
        self._log('error', message, session_id)
    
    def critical(self, message, session_id: Optional[str] = None):
        # 在严重错误日志中自动添加traceback
        try:
            # 获取当前异常信息
            exc_info = sys.exc_info()
            if exc_info[0] is not None:
                # 如果当前有异常，添加traceback
                tb_str = ''.join(traceback.format_exception(*exc_info))
                message = f"{message}\nTraceback:\n{tb_str}"
        except Exception:
            # 如果获取traceback失败，不影响日志记录
            pass
        
        self._log('critical', message, session_id)
    
    def cleanup_session_logger(self, session_id: str):
        """清理session专用的logger"""
        if session_id in self.session_loggers:
            session_logger = self.session_loggers[session_id]
            # 关闭所有handlers
            for handler in session_logger.handlers:
                handler.close()
            # 清除handlers
            session_logger.handlers.clear()
            # 从缓存中移除
            del self.session_loggers[session_id]

# Create a global logger instance for easy import
logger = Logger()