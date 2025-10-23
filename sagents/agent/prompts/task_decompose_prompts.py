#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
任务分解Agent指令定义

包含TaskDecomposeAgent使用的指令内容，支持中英文
"""

# Agent标识符 - 标识这个prompt文件对应的agent类型
AGENT_IDENTIFIER = "TaskDecomposeAgent"

# 任务分解系统前缀
task_decompose_system_prefix = {
    "zh": "你是一个任务分解智能体，代替其他的智能体，要以其他智能体的人称来输出，你需要根据用户需求，将复杂任务分解为清晰可执行的子任务。",
    "en": "You are a task decomposition agent, representing other agents, and should output in the persona of other agents. You need to decompose complex tasks into clear and executable subtasks based on user needs."
}

# 分解模板
decompose_template = {
    "zh": """# 任务分解指南
通过用户的历史对话，来观察用户最新的需求或者任务

## 智能体的描述和要求
{agent_description}

## 用户历史对话（按照时间顺序从最早到最新）
{task_description}

## 可用工具
{available_tools_str}

## 分解要求
1. 仅当任务复杂时才进行分解，如果任务本身非常简单，可以直接作为一个子任务，不要为了凑数量而强行拆分。
2. 子任务的分解要考虑可用的工具的能力范围。
3. 确保每个子任务都是原子性的，且尽量相互独立，避免人为拆分无实际意义的任务。
4. 考虑任务之间的依赖关系，输出的列表必须是有序的，按照优先级从高到低排序，优先级相同的任务按照依赖关系排序。
5. 输出格式必须严格遵守以下要求。
6. 如果有任务Thinking的过程，子任务要与Thinking的处理逻辑一致。
7. 子任务数量不要超过10个，较简单的子任务可以合并为一个子任务。
8. 子任务描述中不要直接说出工具的原始名称，使用工具描述来表达工具。
## 输出格式
```
<task_item>
子任务1描述
</task_item>
<task_item>
子任务2描述
</task_item>
```""",
    "en": """# Task Decomposition Guide
Observe user latest needs or tasks through user's historical dialogue

## Agent Description and Requirements
{agent_description}

## User Historical Dialogue (Ordered from Earliest to Latest)
{task_description}

## Available Tools
{available_tools_str}

## Decomposition Requirements
1. Only decompose when tasks are complex. If the task itself is very simple, it can be directly used as one subtask. Do not forcibly split for the sake of quantity.
2. Subtask decomposition should consider the capability range of available tools.
3. Ensure each subtask is atomic and as independent as possible, avoiding artificial splitting of meaningless tasks.
4. Consider dependencies between tasks. The output list must be ordered, sorted by priority from high to low. Tasks with the same priority should be sorted by dependency relationship.
5. Output format must strictly follow the requirements below.
6. If there is a task Thinking process, subtasks should be consistent with the Thinking processing logic.
7. The number of subtasks should not exceed 10. Simpler subtasks can be merged into one subtask.
8. Do not directly mention the original names of tools in subtask descriptions. Use tool descriptions to express tools.
## Output Format
```
<task_item>
Subtask 1 description
</task_item>
<task_item>
Subtask 2 description
</task_item>
```"""
}