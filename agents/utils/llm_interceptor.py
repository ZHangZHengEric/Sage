"""
LLM API拦截器

自动拦截所有OpenAI API调用，记录请求和响应信息。
可以简化agent base中的大量记录代码。

作者: Eric ZZ
版本: 1.0
"""

import functools
import json
import time
from typing import Any, Dict, List, Optional
import inspect
from .llm_request_logger import get_llm_logger
from .logger import logger


class LLMInterceptor:
    """OpenAI API拦截器 - 自动记录所有LLM请求和响应"""
    
    def __init__(self):
        self.original_methods = {}
        self.is_patched = False
        self.enabled = True
    
    def patch_openai_methods(self):
        """补丁OpenAI API方法以自动记录请求"""
        if self.is_patched:
            return
        
        try:
            import openai
            
            # 新版本OpenAI (v1.x)
            if hasattr(openai, 'chat') and hasattr(openai.chat, 'completions'):
                self.original_methods['chat_completions_create'] = openai.chat.completions.create
                openai.chat.completions.create = self._wrap_chat_completion(openai.chat.completions.create)
                logger.info("LLMInterceptor: 已补丁 openai.chat.completions.create")
            
            # 旧版本OpenAI (v0.x) - 兼容性支持
            if hasattr(openai, 'ChatCompletion'):
                self.original_methods['chat_completion_create'] = openai.ChatCompletion.create
                openai.ChatCompletion.create = self._wrap_chat_completion_legacy(openai.ChatCompletion.create)
                logger.info("LLMInterceptor: 已补丁 openai.ChatCompletion.create")
            
            self.is_patched = True
            logger.info("LLMInterceptor: OpenAI API方法补丁完成")
            
        except ImportError:
            logger.warning("LLMInterceptor: 未找到openai库，跳过补丁")
        except Exception as e:
            logger.error(f"LLMInterceptor: 补丁OpenAI API失败: {e}")
    
    def unpatch_openai_methods(self):
        """恢复原始的OpenAI API方法"""
        if not self.is_patched:
            return
        
        try:
            import openai
            
            # 恢复新版本方法
            if 'chat_completions_create' in self.original_methods:
                openai.chat.completions.create = self.original_methods['chat_completions_create']
                logger.info("LLMInterceptor: 已恢复 openai.chat.completions.create")
            
            # 恢复旧版本方法
            if 'chat_completion_create' in self.original_methods:
                openai.ChatCompletion.create = self.original_methods['chat_completion_create']
                logger.info("LLMInterceptor: 已恢复 openai.ChatCompletion.create")
            
            self.is_patched = False
            logger.info("LLMInterceptor: OpenAI API方法已恢复")
            
        except Exception as e:
            logger.error(f"LLMInterceptor: 恢复OpenAI API失败: {e}")
    
    def enable(self):
        """启用拦截器"""
        self.enabled = True
        logger.info("LLMInterceptor: 已启用")
    
    def disable(self):
        """禁用拦截器"""
        self.enabled = False
        logger.info("LLMInterceptor: 已禁用")
    
    def _wrap_chat_completion(self, original_method):
        """包装新版本的openai.chat.completions.create方法"""
        @functools.wraps(original_method)
        def wrapper(*args, **kwargs):
            if not self.enabled:
                return original_method(*args, **kwargs)
            
            # 记录请求开始时间
            start_time = time.time()
            
            # 提取agent信息
            agent_name = self._extract_agent_name()
            
            # 提取prompt信息
            messages = kwargs.get('messages', args[0] if args else [])
            prompt = self._extract_prompt_from_messages(messages)
            model = kwargs.get('model', 'gpt-4')
            
            try:
                # 调用原始方法
                response = original_method(*args, **kwargs)
                
                # 计算耗时
                elapsed_time = time.time() - start_time
                
                # 提取响应信息
                response_text = ""
                tokens_used = 0
                cost = 0.0
                
                if hasattr(response, 'choices') and response.choices:
                    response_text = response.choices[0].message.content or ""
                
                if hasattr(response, 'usage'):
                    tokens_used = getattr(response.usage, 'total_tokens', 0)
                    # 简单的成本估算（可以根据实际模型调整）
                    cost = self._estimate_cost(model, tokens_used)
                
                # 记录到日志
                self._log_request(
                    agent_name=agent_name,
                    prompt=prompt,
                    response=response_text,
                    model=model,
                    tokens_used=tokens_used,
                    cost=cost,
                    elapsed_time=elapsed_time,
                    api_version="v1"
                )
                
                return response
                
            except Exception as e:
                # 记录错误
                self._log_request(
                    agent_name=agent_name,
                    prompt=prompt,
                    response=f"ERROR: {str(e)}",
                    model=model,
                    additional_info={
                        "error": True,
                        "elapsed_time": time.time() - start_time
                    }
                )
                raise
        
        return wrapper
    
    def _wrap_chat_completion_legacy(self, original_method):
        """包装旧版本的ChatCompletion.create方法"""
        @functools.wraps(original_method)
        def wrapper(*args, **kwargs):
            if not self.enabled:
                return original_method(*args, **kwargs)
            
            start_time = time.time()
            agent_name = self._extract_agent_name()
            
            messages = kwargs.get('messages', args[0] if args else [])
            prompt = self._extract_prompt_from_messages(messages)
            model = kwargs.get('model', 'gpt-3.5-turbo')
            
            try:
                response = original_method(*args, **kwargs)
                elapsed_time = time.time() - start_time
                
                response_text = ""
                tokens_used = 0
                cost = 0.0
                
                if hasattr(response, 'choices') and response.choices:
                    choice = response.choices[0]
                    if hasattr(choice, 'message'):
                        response_text = choice.message.content or ""
                    elif hasattr(choice, 'text'):
                        response_text = choice.text or ""
                
                if hasattr(response, 'usage'):
                    tokens_used = getattr(response.usage, 'total_tokens', 0)
                    cost = self._estimate_cost(model, tokens_used)
                
                self._log_request(
                    agent_name=agent_name,
                    prompt=prompt,
                    response=response_text,
                    model=model,
                    tokens_used=tokens_used,
                    cost=cost,
                    elapsed_time=elapsed_time,
                    api_version="v0"
                )
                
                return response
                
            except Exception as e:
                self._log_request(
                    agent_name=agent_name,
                    prompt=prompt,
                    response=f"ERROR: {str(e)}",
                    model=model,
                    additional_info={
                        "error": True,
                        "elapsed_time": time.time() - start_time
                    }
                )
                raise
        
        return wrapper
    
    def _extract_agent_name(self) -> str:
        """从调用栈中提取智能体名称"""
        try:
            # 遍历调用栈，查找包含agent的类
            for frame_info in inspect.stack():
                frame = frame_info.frame
                
                # 检查frame中的self对象
                if 'self' in frame.f_locals:
                    obj = frame.f_locals['self']
                    class_name = obj.__class__.__name__
                    
                    # 如果类名包含Agent，则认为是智能体
                    if 'Agent' in class_name:
                        return class_name
                    
                    # 检查是否有agent_name属性
                    if hasattr(obj, 'agent_name'):
                        return str(obj.agent_name)
                    
                    # 检查是否有name属性
                    if hasattr(obj, 'name'):
                        return str(obj.name)
            
            return "UnknownAgent"
            
        except Exception:
            return "UnknownAgent"
    
    def _extract_prompt_from_messages(self, messages: List[Dict[str, Any]]) -> str:
        """从消息列表中提取prompt文本"""
        if not messages:
            return ""
        
        prompt_parts = []
        
        for message in messages:
            role = message.get('role', '')
            content = message.get('content', '')
            
            if role and content:
                prompt_parts.append(f"[{role.upper()}]: {content}")
        
        return "\n\n".join(prompt_parts)
    
    def _estimate_cost(self, model: str, tokens: int) -> float:
        """估算API调用成本"""
        # 简化的成本估算，实际使用时可以根据OpenAI的定价更新
        cost_per_1k_tokens = {
            'gpt-4': 0.03,
            'gpt-4-32k': 0.06,
            'gpt-3.5-turbo': 0.002,
            'gpt-3.5-turbo-16k': 0.004,
        }
        
        base_cost = cost_per_1k_tokens.get(model, 0.002)  # 默认使用gpt-3.5-turbo的价格
        return (tokens / 1000) * base_cost
    
    def _log_request(self, agent_name: str, prompt: str, response: str, 
                    model: str, tokens_used: int = 0, cost: float = 0.0,
                    elapsed_time: float = 0.0, api_version: str = "v1",
                    additional_info: Dict[str, Any] = None):
        """记录LLM请求到日志"""
        logger_instance = get_llm_logger()
        if logger_instance:
            extra_info = {
                "elapsed_time": elapsed_time,
                "api_version": api_version,
                "intercepted": True
            }
            if additional_info:
                extra_info.update(additional_info)
            
            logger_instance.log_request(
                agent_name=agent_name,
                prompt=prompt,
                response=response,
                model=model,
                tokens_used=tokens_used,
                cost=cost,
                additional_info=extra_info
            )


# 全局拦截器实例
_global_interceptor: Optional[LLMInterceptor] = None

def init_llm_interceptor() -> LLMInterceptor:
    """初始化全局LLM拦截器"""
    global _global_interceptor
    _global_interceptor = LLMInterceptor()
    _global_interceptor.patch_openai_methods()
    return _global_interceptor

def get_llm_interceptor() -> Optional[LLMInterceptor]:
    """获取全局LLM拦截器"""
    return _global_interceptor

def cleanup_llm_interceptor():
    """清理LLM拦截器"""
    global _global_interceptor
    if _global_interceptor:
        _global_interceptor.unpatch_openai_methods()
        _global_interceptor = None

def enable_llm_logging():
    """启用LLM日志记录"""
    if _global_interceptor:
        _global_interceptor.enable()

def disable_llm_logging():
    """禁用LLM日志记录"""
    if _global_interceptor:
        _global_interceptor.disable()

# 装饰器：为特定方法启用LLM日志记录
def log_llm_calls(func):
    """
    装饰器：为被装饰的方法启用LLM调用日志记录
    这个装饰器确保在方法执行期间LLM拦截器是活跃的
    """
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        # 确保拦截器已初始化
        if not _global_interceptor:
            init_llm_interceptor()
        
        return func(*args, **kwargs)
    
    return wrapper 