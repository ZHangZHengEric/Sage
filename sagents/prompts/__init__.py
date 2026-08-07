#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Agent指令管理模块

提供多语言和按agent分类的指令管理功能
"""

# 显式导入所有子模块，确保提示词注册完整。
from . import agent_base_prompts
from . import common_util_prompts
from . import fibre_agent_prompts
from . import memory_extraction_prompts
from . import memory_recall_prompts
from . import plan_agent_prompts
from . import query_suggest_prompts
from . import session_context_prompts
from . import simple_agent_prompts
from . import simple_react_agent_prompts
from . import team_agent_prompts
from . import tool_suggestion_prompts

__all__ = [
    "agent_base_prompts",
    "common_util_prompts",
    "fibre_agent_prompts",
    "memory_extraction_prompts",
    "memory_recall_prompts",
    "plan_agent_prompts",
    "query_suggest_prompts",
    "session_context_prompts",
    "simple_agent_prompts",
    "simple_react_agent_prompts",
    "team_agent_prompts",
    "tool_suggestion_prompts",
]
