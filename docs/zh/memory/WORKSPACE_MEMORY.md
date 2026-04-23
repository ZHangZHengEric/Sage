---
layout: default
title: 工作空间记忆
parent: Memory
nav_order: 3
description: "Agent workspace、MEMORY.md、workspace 文件检索与 search_memory"
lang: zh
ref: memory-workspace
---

{% include lang_switcher.html %}

# 工作空间记忆

Agent workspace 也是记忆的一部分。原因很简单：Agent 可以读取、写入、总结，并且后续还可以再次检索。

## 定位

- 作用对象：当前 Agent 的工作空间
- 主要内容：`AGENT.md`、`MEMORY.md`、`IDENTITY.md`、`USER.md`、任务文件、结果文件、笔记文件
- 生命周期：随 workspace 存在，可随会话保留，也可单独导出

## 运行时如何使用

- `AgentBase` 会从 workspace 读取 `AGENT.md`、`MEMORY.md`、`USER.md`、`IDENTITY.md`
- `workspace_files` 会把当前工作空间文件树注入上下文
- `MemoryRecallAgent` 会通过 `search_memory` 搜索 workspace 中相关文件
- `agent` 路由的 `file_workspace` 接口可以列出、下载、删除工作空间内容

## 为什么它算 memory

workspace 中的文件不是普通附件，而是 Agent 自己生成并再次读取的“外部化记忆”。它承载：

- 任务过程记录
- 经验沉淀
- 临时知识素材
- 可回读的决策痕迹

这意味着 workspace 与 memory 的边界在 Agent 场景里是打通的。

## 与 `search_memory` 的关系

`search_memory` 不只是搜索用户记忆，它也承担 workspace 级别的文件检索。对 Agent 来说，workspace 中可检索的内容本身就是记忆的一部分。

