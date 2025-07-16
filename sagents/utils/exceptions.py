"""
异常处理工具模块

提供统一的异常处理机制，包括自定义异常类、重试机制和异常处理函数。
"""

import asyncio
import time
import random
from typing import Callable, Any, Optional
from functools import wraps

from sagents.utils.logger import logger

# 基础异常类
class SageException(Exception):
    """Sage框架基础异常类"""
    pass

class ToolExecutionError(SageException):
    """工具执行错误"""
    def __init__(self, message: str, tool_name: str = None):
        super().__init__(message)
        self.tool_name = tool_name

class AgentTimeoutError(SageException):
    """智能体超时错误"""
    pass

# 重试配置
class RetryConfig:
    """重试配置类"""
    def __init__(self, max_attempts=3, base_delay=1.0, max_delay=60.0):
        self.max_attempts = max_attempts
        self.base_delay = base_delay
        self.max_delay = max_delay

def exponential_backoff(max_attempts=3, base_delay=1.0, max_delay=60.0):
    """指数退避重试配置"""
    return RetryConfig(max_attempts, base_delay, max_delay)

def with_retry(config: RetryConfig):
    """重试装饰器"""
    def decorator(func):
        if asyncio.iscoroutinefunction(func):
            @wraps(func)
            async def async_wrapper(*args, **kwargs):
                last_exception = None
                for attempt in range(config.max_attempts):
                    try:
                        return await func(*args, **kwargs)
                    except Exception as e:
                        last_exception = e
                        if attempt < config.max_attempts - 1:
                            delay = min(config.base_delay * (2 ** attempt), config.max_delay)
                            await asyncio.sleep(delay)
                        else:
                            break
                raise last_exception
            return async_wrapper
        else:
            @wraps(func)
            def sync_wrapper(*args, **kwargs):
                last_exception = None
                for attempt in range(config.max_attempts):
                    try:
                        return func(*args, **kwargs)
                    except Exception as e:
                        last_exception = e
                        if attempt < config.max_attempts - 1:
                            delay = min(config.base_delay * (2 ** attempt), config.max_delay)
                            time.sleep(delay)
                        else:
                            break
                raise last_exception
            return sync_wrapper
    return decorator

def handle_exception(exception: Exception, context: dict = None):
    """统一异常处理函数"""
    error_info = {
        'type': exception.__class__.__name__,
        'message': str(exception),
        'category': 'system',
        'severity': 'medium',
        'context': context or {},
        'recovery_suggestions': ['检查系统日志', '重试操作', '联系技术支持']
    }
    
    if isinstance(exception, ToolExecutionError):
        error_info['category'] = 'tool'
        error_info['recovery_suggestions'] = ['检查工具配置', '重试工具调用']
    elif isinstance(exception, AgentTimeoutError):
        error_info['category'] = 'timeout'
        error_info['recovery_suggestions'] = ['增加超时时间', '检查网络连接']
    
    logger.error(f"异常处理: {error_info}")
    return error_info

__all__ = [
    'SageException',
    'ToolExecutionError', 
    'AgentTimeoutError',
    'RetryConfig',
    'exponential_backoff',
    'with_retry',
    'handle_exception'
] 