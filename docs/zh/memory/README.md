---
layout: default
title: Memory
nav_order: 12
has_children: true
description: "与会话记忆、用户记忆、工作空间记忆与记忆搜索相关的文档集合"
lang: zh
ref: memory
---

{% include lang_switcher.html %}

# Memory

这里收纳与 Sage 记忆体系相关的文档。Sage 的 memory 不只是用户记忆，还包括会话历史、Agent workspace 文件、以及基于 `search_memory` 的工作空间检索。

## 体系结构

```mermaid
flowchart TB
    A[会话消息 / 文件 / 经验] --> B[Session Memory<br/>短期会话历史]
    A --> C[User Memory<br/>长期用户记忆]
    A --> D[Agent Workspace<br/>工作空间文件 / 任务文件 / MEMORY.md]
    C --> E[Memory Extraction<br/>自动提取与去重]
    D --> F[search_memory<br/>工作空间检索]
    B --> G[SessionContext]
    C --> G
    D --> G
    E --> G
    F --> G
```

## 这个目录包含什么

- 会话记忆：当前会话内的历史消息与上下文压缩
- 用户记忆：跨会话的长期记忆与自动提取
- 工作空间记忆：Agent workspace 内的文件、笔记、任务结果
- 记忆搜索：基于 `search_memory` 的工作空间检索与验证

## 当前文档

1. [会话记忆](SESSION_MEMORY.md)
2. [用户记忆](USER_MEMORY.md)
3. [工作空间记忆](WORKSPACE_MEMORY.md)
4. [Memory Search 验证](memory-search/README.md)
