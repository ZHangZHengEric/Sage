#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Prompt管理器 - 统一管理系统中的所有prompt
"""

import os
import json
import yaml
from typing import Dict, Any, Optional
from pathlib import Path
from sagents.utils.logger import logger
from sagents.utils.builtin_prompts import BUILTIN_PROMPTS

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
            self._load_prompts()
            PromptManager._initialized = True
    
    def _get_user_config_path(self) -> Path:
        """获取用户prompt配置路径（用户目录下的隐藏文件）"""
        home_dir = Path.home()
        config_dir = home_dir / ".sagents"
        config_dir.mkdir(exist_ok=True)
        return config_dir / "prompts.yaml"
    
    def _load_prompts(self):
        """加载prompt配置：先加载内置，再加载用户配置（用户配置优先级更高）"""
        # 1. 先加载内置prompt（优先级低）
        try:
            self.prompts.update(BUILTIN_PROMPTS)
            logger.info(f"已加载内置prompt: {len(BUILTIN_PROMPTS)} 个")
        except Exception as e:
            logger.error(f"加载内置prompt失败: {e}")
        
        # 2. 再加载用户配置（优先级高，会覆盖内置配置）
        user_config_path = self._get_user_config_path()
        
        if user_config_path.exists():
            try:
                with open(user_config_path, 'r', encoding='utf-8') as f:
                    user_prompts = yaml.safe_load(f) or {}
                    # 过滤掉注释行（以#开头的键）
                    user_prompts = {k: v for k, v in user_prompts.items() if not k.startswith('#')}
                    self.prompts.update(user_prompts)
                    logger.info(f"已加载用户prompt配置: {len(user_prompts)} 个覆盖")
            except Exception as e:
                logger.warning(f"加载用户prompt配置失败: {e}")
        else:
            # 创建默认的用户配置文件
            self._create_user_config_template(user_config_path)
    

    
    def _create_user_config_template(self, path: Path):
        """创建用户配置模板文件"""
        # 这里的示例模版，不要和builtin_prompts.py中的模版重复
        user_config_template = {
            "# 用户自定义prompt配置 - 使用一层key-value结构": None,
            "# 这里的配置会覆盖内置配置": None,
            "# 可用的内置prompt键名请参考: sagents/utils/builtin_prompts.py": None,
            "# 以下是一个示例":None,
            "custom_prompt": "这是一个自定义的prompt"
        }

        try:
            with open(path, 'w', encoding='utf-8') as f:
                yaml.dump(user_config_template, f, default_flow_style=False, allow_unicode=True, indent=2)
            logger.info(f"已创建用户prompt配置模板: {path}")
        except Exception as e:
            logger.error(f"创建用户prompt配置模板失败: {e}")
    
    def get(self, key: str) -> str:
        """获取prompt内容
        
        Args:
            key: prompt的键名
            
        Returns:
            prompt内容，如果不存在则返回空字符串
        """
        return self.prompts.get(key, "")
    
    def set(self, key: str, content: str):
        """设置prompt内容（运行时修改）
        
        Args:
            key: prompt的键名
            content: prompt内容
        """
        self.prompts[key] = content
    
    def format(self, key: str, **kwargs) -> str:
        """格式化prompt模板
        
        Args:
            key: prompt的键名
            **kwargs: 模板参数
            
        Returns:
            格式化后的prompt内容
        """
        template = self.get(key)
        if template and kwargs:
            try:
                return template.format(**kwargs)
            except KeyError as e:
                logger.warning(f"模板格式化失败，缺少参数: {e}")
                return template
        return template
    
    def list_keys(self) -> list:
        """列出所有可用的prompt键名"""
        return list(self.prompts.keys())
    
    def exists(self, key: str) -> bool:
        """检查prompt是否存在"""
        return key in self.prompts
    
    def __getattr__(self, key: str) -> str:
        """支持通过属性方式访问prompt
        
        Args:
            key: prompt的键名
            
        Returns:
            prompt内容，如果不存在则抛出AttributeError
        """
        if key in self.prompts:
            return self.prompts[key]
        raise AttributeError(f"PromptManager has no prompt '{key}'")
    
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
    
    def save_user_prompt_config(self):
        """保存当前配置到用户配置文件"""
        user_config_path = self._get_user_config_path()
        try:
            # 只保存非内置的prompt（用户自定义的）
            user_prompts = {k: v for k, v in self.prompts.items() if k not in BUILTIN_PROMPTS}
            with open(user_config_path, 'w', encoding='utf-8') as f:
                yaml.dump(user_prompts, f, default_flow_style=False, allow_unicode=True, indent=2)
            logger.info(f"已保存用户prompt配置: {len(user_prompts)} 个")
        except Exception as e:
            logger.error(f"保存用户prompt配置失败: {e}")
    
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
