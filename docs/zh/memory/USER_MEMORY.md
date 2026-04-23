---
layout: default
title: 用户记忆
parent: Memory
nav_order: 2
description: "UserMemoryManager、长期记忆、自动提取与注入"
lang: zh
ref: memory-user
---

{% include lang_switcher.html %}

# 用户记忆

用户记忆是 Sage 的长期记忆层，用于跨会话保存用户偏好、要求、经验、技能和约束。

## 定位

- 作用对象：user_id
- 主要内容：偏好、要求、人设、约束、经验、学习、技能等
- 生命周期：跨会话存在，可持久化到本地文件、MCP 服务或向量存储

## 运行时组件

- [UserMemoryManager](../../sagents/context/user_memory/manager.py)
- [MemoryType / MemoryEntry](../../sagents/context/user_memory/schemas.py)
- [ToolMemoryDriver](../../sagents/context/user_memory/drivers/tool.py)
- [VectorMemoryDriver](../../sagents/context/user_memory/drivers/vector.py)
- [MemoryExtractor](../../sagents/context/user_memory/extractor.py)

## 分层

- 系统级记忆：`preference / requirement / persona / constraint`
- 上下文记忆：`context / project / workflow`
- 知识记忆：`experience / learning / skill`
- 辅助记忆：`note / bookmark / pattern`

## 关键行为

- `remember / recall / forget` 是核心接口
- 支持按类型召回
- 支持自动抽取、去重、更新
- 会把系统级记忆注入 `system_context`

## 为什么它算 memory

这部分是最典型的“Agent 记忆”。Agent 能主动记住、主动回忆、主动删除，它不是静态资料，而是随使用持续生长的长期上下文。

