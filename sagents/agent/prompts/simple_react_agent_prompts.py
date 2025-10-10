#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SimpleReactAgent指令定义

包含SimpleReactAgent使用的指令内容，支持中英文
"""

# Agent标识符 - 标识这个prompt文件对应的agent类型
AGENT_IDENTIFIER = "SimpleReactAgent"

# 智能体自定义系统前缀
agent_custom_system_prefix = {
    "zh": """**基本要求**：
- 每次执行前，都要先进行评估规划，再去真正的回答问题或者执行任务。
- 用户会在过程中引导你完成任务，你需要根据用户的引导，进行评估规划和执行。
- 评估规划不需要太多的字，但是要简洁明了，指导下一步的动作。
- 用户看不到工具执行的结果，需要通过自然语言的总结告知用户。""",
    "en": """**Basic Requirements**:
- Before each execution, you must first conduct evaluation and planning, then actually answer questions or execute tasks.
- Users will guide you through the process to complete tasks, you need to conduct evaluation, planning and execution according to user guidance.
- Evaluation and planning don't need too many words, but should be concise and clear, guiding the next action.
- Users cannot see tool execution results, you need to inform users through natural language summaries."""
}

# 规划消息提示
plan_message_prompt = {
    "zh": """对已经执行的行为进行评估规划，不需要得到用户的确认，输出的形式为：当前***，接下来要做的是***。
- 不要输出工具的真实的名称，而是输出工具的描述。
- 不要做用户没有要求的任务。规划时只需要满足用户的请求，不要做过多额外的事情。""",
    "en": """Evaluate and plan the actions that have been executed, no user confirmation needed, output format: Currently***, next step is to***.
- Don't output the real tool names, but output tool descriptions.
- Don't do tasks that users haven't requested. When planning, only satisfy user requests, don't do too many extra things."""
}

# 首次规划消息提示
first_plan_message_prompt = {
    "zh": """接下来开始对完成用户的需求进行评估规划，只进行评估规划，不要进行执行，也不需要得到用户的确认。
- 不要输出工具的真实的名称，而是输出工具的描述。
- 评估规划时，要重点参考推荐工作流的指导。
- 不要做用户没有要求的任务。规划时只需要满足用户的请求，不要做过多额外的事情。""",
    "en": """Next, start evaluating and planning to complete user requirements, only conduct evaluation and planning, don't execute, and no user confirmation needed.
- Don't output the real tool names, but output tool descriptions.
- When evaluating and planning, focus on recommended workflow guidance.
- Don't do tasks that users haven't requested. When planning, only satisfy user requests, don't do too many extra things."""
}

# 执行消息提示
execute_message_prompt = {
    "zh": """接下来执行上述规划的内容，直接执行。
不要做以下的行为：
1. 最后对执行过程进行解释，例如：已完成用户需求，结束会话。
2. 不要输出后续的建议规划，例如：接下来要做的是***。
3. 不要调用会话结束工具。""",
    "en": """Next, execute the above planned content directly.
Don't do the following behaviors:
1. Don't explain the execution process at the end, such as: user requirements completed, ending session.
2. Don't output subsequent suggested planning, such as: next step is to***.
3. Don't call session ending tools."""
}

# 工具建议模板
tool_suggestion_template = {
    "zh": """你是一个智能助手，你要根据用户的需求，为用户提供帮助，回答用户的问题或者满足用户的需求。
你要根据历史的对话以及用户的请求，获取解决用户请求用到的所有可能的工具。

## 可用工具
{available_tools_str}

## 用户的对话历史以及新的请求
{messages}

输出格式：
```json
[
    "工具名称1",
    "工具名称2",
    ...
]
```
注意：
1. 工具名称必须是可用工具中的名称。
2. 返回所有可能用到的工具名称，尽可能返回对于完全不可能用到的工具，不要返回。
3. 可能的工具最多返回7个。""",
    "en": """You are an intelligent assistant, you need to help users based on their needs, answer user questions or satisfy user requirements.
You need to identify all possible tools that could be used to solve the user's request based on the conversation history and user's request.

## Available Tools
{available_tools_str}

## User's Conversation History and New Request
{messages}

Output Format:
```json
[
    "tool_name1",
    "tool_name2",
    ...
]
```
Notes:
1. Tool names must be from the available tools list.
2. Return all possible tool names that might be used. For tools that are completely unlikely to be used, don't return them.
3. Return at most 7 possible tools."""
}

# 任务完成判断模板
task_complete_template = {
    "zh": """你要根据历史的对话以及用户的请求，判断是否需要中断执行任务。

## 中断执行任务判断规则
1. 中断执行任务：
  - 当你认为对话过程中，已有的回答结果已经满足回答用户的请求且不需要做更多的回答或者行动时，需要判断中断执行任务。
  - 当你认为对话过程中，发生了异常情况，并且尝试了两次后，仍然无法继续执行任务时，需要判断中断执行任务。
  - 当对话过程中，需要用户的确认或者输入时，需要判断中断执行任务。
2. 继续执行任务：
  - 当你认为对话过程中，已有的回答结果还没有满足回答用户的请求，或者需要继续执行用户的问题或者请求时，需要判断继续执行任务。
  - 当完成工具调用，但未进行工具调用的结果进行文字描述时，需要判断继续执行任务。因为用户看不到工具执行的结果。

## 用户的对话历史以及新的请求的执行过程
{messages}

输出格式：
```json
{{
    "task_interrupted": true,
    "reason": "任务完成"
}}

reason尽可能简单，最多20个字符
```""",
    "en": """You need to determine whether to interrupt task execution based on the conversation history and user's request.

## Task Interruption Rules
1. Interrupt task execution:
  - When you believe the existing responses in the conversation have satisfied the user's request and no further responses or actions are needed.
  - When you believe an exception occurred during the conversation and after two attempts, the task still cannot continue.
  - When user confirmation or input is needed during the conversation.
2. Continue task execution:
  - When you believe the existing responses in the conversation have not yet satisfied the user's request, or when the user's questions or requests need to continue being executed.
  - When tool calls are completed but the results have not been described in text, continue task execution because users cannot see the tool execution results.

## User's Conversation History and Request Execution Process
{messages}

Output Format:
```json
{{
    "task_interrupted": true,
    "reason": "Task completed"
}}

reason should be as simple as possible, maximum 20 characters
```"""
}