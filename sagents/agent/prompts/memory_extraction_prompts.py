#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
记忆提取Agent指令定义

包含MemoryExtractionAgent使用的指令内容，支持中英文
"""

# Agent标识符 - 标识这个prompt文件对应的agent类型
AGENT_IDENTIFIER = "MemoryExtractionAgent"

# 记忆提取系统前缀
memory_extraction_system_prefix = {
    "zh": "你是一个记忆提取智能体，专门负责从对话历史中提取潜在的系统级记忆，检测和处理记忆冲突，提供智能化的记忆管理建议。",
    "en": "You are a memory extraction agent, specializing in extracting potential system-level memories from conversation history, detecting and handling memory conflicts, and providing intelligent memory management recommendations."
}

# 记忆提取模板
memory_extraction_template = {
    "zh": """请分析以下对话，提取值得长期记忆的系统级信息。

<当前系统上下文>
{system_context}
</当前系统上下文>

<对话历史>
{formatted_conversation}
</对话历史>

请提取以下四种类型的系统级记忆：
1. **用户偏好 (preference)**：用户明确表达自身的喜好、习惯、风格偏好
2. **用户要求 (requirement)**：用户对AI回答方式、格式、内容的具体偏好要求，而不是用户要做的事情的记录
3. **用户人设 (persona)**：用户的身份、背景、经验、技能水平等个人信息
4. **约束条件 (constraint)**：用户提到的时间、环境、工作等约束条件

提取原则：
- 只提取明确表达的、具有长期价值的信息
- 忽略临时性、一次性的内容，用户要求做的事情不需要作为"用户要求"系统级的记忆。
- 确保记忆内容准确、具体
- 为每个记忆生成简洁明确的标识key
- memory的 key 和 content 中的描述尽可能使用绝对值，例如时间"明天"，要转换成绝对日期。
- 记忆必须要在User的表达的内容中提取，不能在系统上下文中以及AI的执行过程中提取。
- 不要提取系统上下文中已经提到的信息。

<返回格式要求>
请以JSON格式返回，格式如下：
{{
    "extracted_memories": [
        {{
            "key": "记忆的唯一标识",
            "content": "记忆的具体内容，精确不要有遗漏的信息",
            "type": "记忆类型(preference/requirement/persona/constraint/context/project/workflow/experience/learning/skill/note/bookmark/pattern）",
            "tags": ["相关标签1", "相关标签2"],
            "source": "提取依据的对话片段"
        }}
    ]
}}

如果没有找到值得记忆的信息，请返回空的extracted_memories数组。
{{
    "extracted_memories": []
}}
</返回格式要求>""",
    "en": """Please analyze the following dialogue and extract system-level information worth long-term memory.

<Current System Context>
{system_context}
</Current System Context>

<Dialogue History>
{formatted_conversation}
</Dialogue History>

Please extract the following four types of system-level memories:
1. **User Preferences (preference)**: User's explicitly expressed preferences, habits, style preferences
2. **User Requirements (requirement)**: User's specific preference requirements for AI response methods, formats, content, not records of what users want to do
3. **User Persona (persona)**: User's identity, background, experience, skill level and other personal information
4. **Constraints (constraint)**: Time, environment, work and other constraints mentioned by users

Extraction Principles:
- Only extract explicitly expressed information with long-term value
- Ignore temporary, one-time content. Things users want to do do not need to be recorded as "user requirements" system-level memories.
- Ensure memory content is accurate and specific
- Generate concise and clear identification keys for each memory
- Descriptions in memory key and content should use absolute values as much as possible, for example, time "tomorrow" should be converted to absolute date.
- Memories must be extracted from User's expressed content, not from system context or AI execution processes.
- Do not extract information already mentioned in system context.

<Return Format Requirements>
Please return in JSON format as follows:
{{
    "extracted_memories": [
        {{
            "key": "Unique identifier of memory",
            "content": "Specific content of memory, accurate without missing information",
            "type": "Memory type (preference/requirement/persona/constraint/context/project/workflow/experience/learning/skill/note/bookmark/pattern)",
            "tags": ["Related tag 1", "Related tag 2"],
            "source": "Dialogue fragment on which extraction is based"
        }}
    ]
}}

If no information worth remembering is found, please return an empty extracted_memories array.
{{
    "extracted_memories": []
}}
</Return Format Requirements>"""
}

# 记忆去重模板
memory_deduplication_template = {
    "zh": """请分析以下现有记忆，识别需要删除的重复记忆。

判断是否有重复的记忆的规则要满足以下两个条件：
1. 两个记忆的key 基本上表达一样的内容，并且两个记忆的content 也基本上相似领域或者相反的意思的内容。
2. 两个记忆在一起会导致矛盾和冲突

示例1
记忆1的key：语言偏好
记忆1的content：中文
记忆2的key：语言偏好
记忆2的content：英文
结论：重复，用户偏好只能有一种

示例2
记忆1的key：用户的语言能力
记忆1的content：中文
记忆2的key：用户的语言能力
记忆2的content：英文
结论：不重复，用户可以有两种语言能力

示例3
记忆1的key：喜欢的运动
记忆1的content：用户喜欢足球
记忆2的key：喜欢的运动
记忆2的content：用户喜欢篮球
结论：不重复，用户可以有两种喜欢的运动

示例4
记忆1的key：称呼
记忆1的content：张三
记忆2的key：称呼
记忆2的content：李四
结论：重复，用户不能有两个称呼

当前存在的记忆：
{existing_memories}

输出格式为Json的key的列表，例如：
```json
{{
    "duplicate_keys": ["key1"]
}}
```
输出要求描述：
1. key1是要遗忘的记忆的key。
2. 不要输出任何其他的内容或解释，只输出Json格式的内容。""",
    "en": """Please analyze the following existing memories and identify duplicate memories that need to be deleted.

Rules for judging whether there are duplicate memories must satisfy the following two conditions:
1. The keys of two memories basically express the same content, and the content of the two memories is also in similar fields or opposite meanings.
2. The two memories together will cause contradictions and conflicts

Example 1
Memory 1 key: Language preference
Memory 1 content: Chinese
Memory 2 key: Language preference
Memory 2 content: English
Conclusion: Duplicate, user can only have one preference

Example 2
Memory 1 key: User's language ability
Memory 1 content: Chinese
Memory 2 key: User's language ability
Memory 2 content: English
Conclusion: Not duplicate, user can have two language abilities

Example 3
Memory 1 key: Favorite sport
Memory 1 content: User likes football
Memory 2 key: Favorite sport
Memory 2 content: User likes basketball
Conclusion: Not duplicate, user can have two favorite sports

Example 4
Memory 1 key: Name/Title
Memory 1 content: Zhang San
Memory 2 key: Name/Title
Memory 2 content: Li Si
Conclusion: Duplicate, user cannot have two names/titles

Current existing memories:
{existing_memories}

Output format is a Json list of keys, for example:
```json
{{
    "duplicate_keys": ["key1"]
}}
```
Output requirements:
1. key1 is the key of the memory to be forgotten.
2. Do not output any other content or explanations, only output Json format content."""
}