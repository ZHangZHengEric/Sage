---
layout: default
title: 会话记忆
parent: Memory
nav_order: 1
description: "SessionMemoryManager 与历史消息检索策略"
lang: zh
ref: memory-session
---

{% include lang_switcher.html %}

# 会话记忆

会话记忆是 Sage 的短期记忆层，主要负责当前会话内历史消息的组织、压缩与召回。

## 定位

- 作用对象：单个 session
- 主要内容：历史消息、对话轮次、上下文压缩结果
- 生命周期：随会话存在，关闭后不作为长期记忆持久化

## 运行时组件

- [SessionMemoryManager](../../sagents/context/session_memory/session_memory_manager.py)
- `MessageManager`
- `ContextBudgetManager`

## 关键行为

- 默认使用 BM25 做历史消息检索
- 支持 `messages` 与 `grouped_chat` 两种策略
- 在 Agent 调用 LLM 前，按预算选择性拼接历史消息
- 在会话运行过程中，和消息流式输出保持一致
- 主会话只使用大模型生成的持久摘要进行压缩，不截断消息或工具内容，不创建上下文 artifact。
- 压缩模型不会收到 `reasoning_content`；reasoning 仍保留在持久 ledger 中，但会从压缩 prompt 直接丢弃。

## 为什么它算 memory

会话记忆不是“知识库”，而是当前 Agent 正在使用的短期上下文。它决定 Agent 这一次对话记得什么、忘掉什么、如何压缩历史。

## 与 workspace 的关系

会话记忆会影响 Agent 对 workspace 文件的理解，但不会替代 workspace 本身。workspace 是文件层，session memory 是短期对话层。
