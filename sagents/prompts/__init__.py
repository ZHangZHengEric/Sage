#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Agent指令管理模块

提供多语言和按agent分类的指令管理功能
"""

# 显式导入所有子模块，确保 PyInstaller 能打包它们
from . import agent_base_prompts
from . import fibre_agent_prompts
from . import memory_extraction_prompts
from . import query_suggest_prompts
from . import session_context_prompts
from . import simple_agent_prompts
from . import simple_react_agent_prompts
from . import task_analysis_prompts
from . import task_completion_judge_prompt
from . import task_decompose_prompts
from . import task_executor_agent_prompts
from . import task_observation_prompts
from . import task_planning_prompts
from . import task_rewrite_prompts
from . import task_router_prompts
from . import task_stage_summary_prompts
from . import task_summary_prompts
from . import workflow_select_prompts
