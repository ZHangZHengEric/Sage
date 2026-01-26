#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Prompt管理器 - 统一管理系统中的所有prompt
"""

import inspect
from typing import Optional
from pathlib import Path
from sagents.utils.logger import logger

# 自动导入agent prompt模块
def _auto_import_prompt_modules():
    """自动导入prompts文件夹下的所有prompt模块"""
    import importlib
    import glob
    
    prompt_modules = {}
    prompts_dir = Path(__file__).parent.parent / "prompts"
    
    try:
        # 获取所有.py文件（排除__init__.py）
        pattern = str(prompts_dir / "*.py")
        for file_path in glob.glob(pattern):
            file_name = Path(file_path).stem
            if file_name == "__init__":
                continue
                
            try:
                # 动态导入模块
                module_name = f"sagents.prompts.{file_name}"
                module = importlib.import_module(module_name)
                
                # 获取模块的AGENT_IDENTIFIER
                agent_identifier = getattr(module, 'AGENT_IDENTIFIER', None)
                if agent_identifier is None:
                    logger.warning(f"模块 {module_name} 缺少AGENT_IDENTIFIER变量，跳过")
                    continue
                
                # 新结构：查找模块中的prompt变量（不以_开头，不是AGENT_IDENTIFIER，且是字典类型）
                zh_prompts = {}
                en_prompts = {}
                pt_prompts = {}
                
                for attr_name in dir(module):
                    if (not attr_name.startswith('_') and 
                        attr_name != 'AGENT_IDENTIFIER' and 
                        not attr_name.endswith('_PROMPTS_ZH') and 
                        not attr_name.endswith('_PROMPTS_EN') and
                        not attr_name.endswith('_PROMPTS_PT')):
                        
                        attr_value = getattr(module, attr_name)
                        # 检查是否是包含zh、en和pt键的字典
                        if isinstance(attr_value, dict) and 'zh' in attr_value and 'en' in attr_value and 'pt' in attr_value:
                            zh_prompts[attr_name] = attr_value['zh']
                            en_prompts[attr_name] = attr_value['en']
                            pt_prompts[attr_name] = attr_value['pt']
                
                # 如果找到了prompt，则存储
                if zh_prompts or en_prompts or pt_prompts:
                    if zh_prompts:
                        prompt_modules[f"{agent_identifier}_PROMPTS_ZH"] = zh_prompts
                    if en_prompts:
                        prompt_modules[f"{agent_identifier}_PROMPTS_EN"] = en_prompts
                    if pt_prompts:
                        prompt_modules[f"{agent_identifier}_PROMPTS_PT"] = pt_prompts
                    logger.debug(f"成功导入prompt模块: {module_name} (agent: {agent_identifier}, zh: {len(zh_prompts)}, en: {len(en_prompts)}, pt: {len(pt_prompts)})")
                else:
                    # 兼容旧格式：查找模块中的PROMPTS变量
                    for attr_name in dir(module):
                        if attr_name.endswith("_PROMPTS_ZH") or attr_name.endswith("_PROMPTS_EN") or attr_name.endswith("_PROMPTS_PT"):
                            # 使用AGENT_IDENTIFIER + 语言后缀作为键
                            if attr_name.endswith("_PROMPTS_ZH"):
                                key = f"{agent_identifier}_PROMPTS_ZH"
                            elif attr_name.endswith("_PROMPTS_EN"):
                                key = f"{agent_identifier}_PROMPTS_EN"
                            else:
                                key = f"{agent_identifier}_PROMPTS_PT"
                            prompt_modules[key] = getattr(module, attr_name)
                    logger.debug(f"成功导入prompt模块(旧格式): {module_name} (agent: {agent_identifier})")
                        
            except ImportError as e:
                logger.warning(f"无法导入prompt模块 {module_name}: {e}")
                
        return prompt_modules, True
    except Exception as e:
        logger.error(f"自动导入prompt模块失败: {e}")
        return {}, False

# 执行自动导入
PROMPT_MODULES, AGENT_PROMPTS_AVAILABLE = _auto_import_prompt_modules()

class PromptManager:
    """Prompt管理器，负责加载和管理系统中的所有prompt"""
    
    _instance = None
    _initialized = False
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(PromptManager, cls).__new__(cls)
        return cls._instance
    
    def __init__(self):
        if not self._initialized:
            self.prompts = {}
            self.agent_prompts_zh = {}
            self.agent_prompts_en = {}
            self.agent_prompts_pt = {}
            self.agent_prompts_map = {
                'zh': self.agent_prompts_zh,
                'en': self.agent_prompts_en,
                'pt': self.agent_prompts_pt,
            }
            self._load_agent_prompts()
            PromptManager._initialized = True
    
    def _load_agent_prompts(self):
        """加载agent prompt"""
        if not AGENT_PROMPTS_AVAILABLE:
            logger.warning("Agent prompt模块不可用，跳过加载")
            return
        
        # 自动加载所有导入的prompt模块
        for module_key, module_content in PROMPT_MODULES.items():
            if module_key.endswith("_PROMPTS_ZH"):
                # 提取agent名称（去掉_PROMPTS_ZH后缀），保持原始大小写
                agent_name = module_key[:-11]  # 去掉"_PROMPTS_ZH"
                self.agent_prompts_zh[agent_name] = module_content
            elif module_key.endswith("_PROMPTS_EN"):
                # 提取agent名称（去掉_PROMPTS_EN后缀），保持原始大小写
                agent_name = module_key[:-11]  # 去掉"_PROMPTS_EN"
                self.agent_prompts_en[agent_name] = module_content
            elif module_key.endswith("_PROMPTS_PT"):
                # 提取agent名称（去掉_PROMPTS_PT后缀），保持原始大小写
                agent_name = module_key[:-11]  # 去掉"_PROMPTS_PT"
                self.agent_prompts_pt[agent_name] = module_content
        print(f"Agent prompt加载完成: 中文{len(self.agent_prompts_zh)}个, 英文{len(self.agent_prompts_en)}个, 葡萄牙语{len(self.agent_prompts_pt)}个")
    
    
    def get_prompt(self, key: str, default: Optional[str] = None, agent: Optional[str] = None, language: str = 'zh') -> str:
        """获取prompt内容
        
        Args:
            key: prompt的键名
            default: 默认值，如果找不到对应的prompt则返回此值
            agent: agent类型，如果指定则从对应agent的prompt中获取
            language: 语言，'zh'、'en'或'pt'，默认为'zh'
            
        Returns:
            prompt内容
            
        Raises:
            KeyError: 当找不到对应的prompt且没有提供default值时
        """
        # 如果指定了agent，从agent prompt中获取
        if agent:
            # agent_prompts = self.agent_prompts_zh if language == 'zh' else self.agent_prompts_en
            agent_prompts = self.agent_prompts_map.get(language, 'zh')
            if agent in agent_prompts and key in agent_prompts[agent]:
                return agent_prompts[agent][key]
            # 如果在指定agent中找不到，尝试从common中获取
            if 'common' in agent_prompts and key in agent_prompts['common']:
                return agent_prompts['common'][key]
        
        # 从内置prompts中获取
        result = self.prompts.get(key, default)
        
        # 如果没有找到且没有默认值，抛出异常
        if result is None:
            error_msg = f"找不到prompt: key='{key}'"
            if agent:
                error_msg += f", agent='{agent}'"
            error_msg += f", language='{language}'"
            raise KeyError(error_msg)
            
        return result
    
    def get(self, key: str, default: str = "", agent: Optional[str] = None, language: str = 'zh') -> str:
        """获取prompt内容（简化版本，找不到时返回默认值）
        
        Args:
            key: prompt的键名
            default: 默认值，如果找不到则返回此值
            agent: agent类型，如果指定则从对应agent的prompt中获取
            language: 语言，'zh'、'en'或'pt'，默认为'zh'
            
        Returns:
            prompt内容，如果找不到则返回默认值
        """
        return self.get_prompt(key, default=default, agent=agent, language=language)
    
    def set(self, key: str, content: str):
        """设置prompt内容（运行时修改）
        
        Args:
            key: prompt的键名
            content: prompt内容
        """
        self.prompts[key] = content
    
    def format(self, key: str, agent: Optional[str] = None, language: str = 'zh', **kwargs) -> str:
        """格式化prompt模板
        
        Args:
            key: prompt的键名
            agent: agent类型，如果指定则从对应agent的prompt中获取
            language: 语言，'zh'、'en'或'pt'，默认为'zh'
            **kwargs: 模板参数
            
        Returns:
            格式化后的prompt内容
        """
        try:
            template = self.get_prompt(key, default="", agent=agent, language=language)
            if not template:
                logger.warning(f"未找到prompt模板: {key}")
                return ""
            
            return template.format(**kwargs)
        except KeyError as e:
            logger.error(f"格式化prompt模板失败，缺少参数: {e}")
            return template
        except Exception as e:
            logger.error(f"格式化prompt模板失败: {e}")
            return template if 'template' in locals() else ""
    
    def list_keys(self) -> list:
        """列出所有可用的prompt键名"""
        return list(self.prompts.keys())
    
    def exists(self, key: str) -> bool:
        """检查prompt是否存在"""
        return key in self.prompts
    
    def __getattr__(self, key: str) -> str:
        """支持属性访问方式获取prompt
        
        Args:
            key: prompt的键名
            
        Returns:
            prompt内容
        """
        if key.startswith('_'):
            raise AttributeError(f"'{self.__class__.__name__}' object has no attribute '{key}'")
        return self.get(key)
    
    def get_agent_prompt(self, agent: str, key: str, language: str = 'zh', default: Optional[str] = None) -> str:
        """获取指定agent的prompt
        
        Args:
            agent: agent类型
            key: prompt的键名
            language: 语言，'zh'、'en'或'pt'，默认为'zh'
            default: 默认值，如果不提供且找不到prompt则抛出异常
            
        Returns:
            prompt内容
            
        Raises:
            KeyError: 当找不到对应的prompt且没有提供default值时
        """
        return self.get_prompt(key, default=default, agent=agent, language=language)
    
    def get_agent_prompt_auto(self, key: str, language: str = 'zh', default: Optional[str] = None) -> str:
        """自动获取调用者类名并获取对应的agent prompt
        
        Args:
            key: prompt的键名
            language: 语言，'zh'、'en'或'pt'，默认为'zh'
            default: 默认值，如果不提供且找不到prompt则抛出异常
            
        Returns:
            prompt内容
            
        Raises:
            KeyError: 当找不到对应的prompt且没有提供default值时
            ValueError: 当无法自动获取类名时
        """
        agent = self._get_caller_class_name()
        if agent is None:
            if default is not None:
                return default
            raise ValueError("无法自动获取调用者类名，请使用get_agent_prompt方法并手动指定agent参数")
        
        return self.get_prompt(key, default=default, agent=agent, language=language)
    
    def _get_caller_class_name(self) -> Optional[str]:
        """从调用栈中自动获取调用者的类名
        
        Returns:
            类名，如果无法获取则返回None
        """
        try:
            # 获取调用栈
            frame = inspect.currentframe()
            # 遍历调用栈，寻找包含self的frame，但跳过PromptManager自身
            for i in range(10):  # 最多查找10层
                if frame is None:
                    break
                frame = frame.f_back
                if frame is None:
                    break
                    
                # 获取调用者的局部变量中的self
                caller_locals = frame.f_locals
                if 'self' in caller_locals:
                    class_name = caller_locals['self'].__class__.__name__
                    # 跳过PromptManager自身
                    if class_name == 'PromptManager':
                        continue
                    if class_name == 'AgentRuntime':
                        # 如果是AgentRuntime包装的，尝试获取内部agent的类名
                        agent_runtime = caller_locals['self']
                        if hasattr(agent_runtime, 'agent'):
                            class_name = agent_runtime.agent.__class__.__name__
                    # 直接返回类名，不进行格式转换
                    logger.debug(f"自动获取到类名: {class_name}")
                    return class_name
                
        except Exception as e:
            logger.warning(f"无法自动获取类名: {e}")
            
        return None
    

    
    def __setattr__(self, key: str, value):
        """支持通过属性方式设置prompt
        
        Args:
            key: prompt的键名或实例属性名
            value: prompt内容或属性值
        """
        # 如果是内部属性，使用默认行为
        if key.startswith('_') or key in ['prompts']:
            super().__setattr__(key, value)
        else:
            # 如果prompts已经初始化，则设置为prompt
            if hasattr(self, 'prompts'):
                self.prompts[key] = value
            else:
                super().__setattr__(key, value)
    

    
    def reload(self):
        """重新加载配置"""
        self.prompts.clear()
        self._load_prompts()
        logger.info("已重新加载prompt配置")

# 全局prompt管理器实例
prompt_manager = PromptManager()

# 便捷函数
def get_prompt(key: str, **kwargs) -> str:
    """获取并格式化prompt
    
    Args:
        key: prompt的键名
        **kwargs: 模板参数（可选）
        
    Returns:
        prompt内容或格式化后的内容
    """
    if kwargs:
        return prompt_manager.format(key, **kwargs)
    return prompt_manager.get(key)

def set_prompt(key: str, content: str):
    """设置prompt内容
    
    Args:
        key: prompt的键名
        content: prompt内容
    """
    prompt_manager.set(key, content)

def list_prompts() -> list:
    """列出所有可用的prompt键名"""
    return prompt_manager.list_keys()

def prompt_exists(key: str) -> bool:
    """检查prompt是否存在"""
    return prompt_manager.exists(key)
