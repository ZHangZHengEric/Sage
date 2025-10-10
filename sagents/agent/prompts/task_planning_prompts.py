#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
任务规划Agent指令定义

包含TaskPlanningAgent使用的指令内容，支持中英文
"""

# Agent标识符 - 标识这个prompt文件对应的agent类型
AGENT_IDENTIFIER = "TaskPlanningAgent"

# 任务规划系统前缀
task_planning_system_prefix = {
    "zh": "你是一个任务规划智能体，代替其他的智能体，要以其他智能体的人称来输出，专门负责根据用户需求，以及执行的过程，规划接下来用户需要执行的任务",
    "en": "You are a task planning agent, representing other agents, and should output in the persona of other agents. You specialize in planning the tasks that users need to execute next based on user needs and execution processes."
}

# 规划模板
planning_template = {
    "zh": """# 任务规划指南

## 智能体的描述和要求
{agent_description}

## 完整任务描述
{task_description}

## 任务管理器状态
{task_manager_status}

## 近期完成工作
{completed_actions}

## 可用工具
{available_tools_str}

## 规划规则
1. 根据我们的当前任务以及近期完成工作，为了达到逐步完成任务管理器的未完成子任务或者完整的任务，清晰描述接下来要执行的具体的任务名称。
2. 确保接下来的任务可执行且可衡量
3. 优先使用现有工具
4. 设定明确的成功标准
5. 只输出以下格式的XLM，不要输出其他内容,不要输出```, <tag>标志位必须在单独一行
6. description中不要包含工具的真实名称
7. required_tools至少包含5个可能需要的工具的名称，最多10个。

## 输出格式
```
<next_step_description>
子任务的清晰描述，一段话不要有换行
</next_step_description>
<required_tools>
["tool1_name","tool2_name"]
</required_tools>
<expected_output>
预期结果描述，一段话不要有换行
</expected_output>
<success_criteria>
如何验证完成，一段话不要有换行
</success_criteria>
```""",
    "en": """# Task Planning Guide

## Agent Description and Requirements
{agent_description}

## Complete Task Description
{task_description}

## Task Manager Status
{task_manager_status}

## Recently Completed Work
{completed_actions}

## Available Tools
{available_tools_str}

## Planning Rules
1. Based on our current tasks and recently completed work, clearly describe the specific task name to be executed next in order to gradually complete the unfinished subtasks or complete tasks in the task manager.
2. Ensure the next task is executable and measurable
3. Prioritize using existing tools
4. Set clear success criteria
5. Only output XML in the following format, do not output other content, do not output ```, <tag> markers must be on separate lines
6. Do not include real tool names in description
7. required_tools should include at least 5 and at most 10 possible tool names needed.

## Output Format
```
<next_step_description>
Clear description of the subtask, one paragraph without line breaks
</next_step_description>
<required_tools>
["tool1_name","tool2_name"]
</required_tools>
<expected_output>
Expected result description, one paragraph without line breaks
</expected_output>
<success_criteria>
How to verify completion, one paragraph without line breaks
</success_criteria>
```"""
}

# 下一步规划提示文本 - 用于显示给用户的规划开始提示
next_step_planning_prompt = {
    "zh": "下一步规划: ",
    "en": "Next Step Planning: "
}