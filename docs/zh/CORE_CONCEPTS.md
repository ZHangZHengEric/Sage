---
layout: default
title: 核心概念
nav_order: 3
description: "Sage 背后的运行时模型"
lang: zh
ref: core-concepts
---

{% include lang_switcher.html %}

# 核心概念

## `SAgent` 是运行时入口

`sagents/sagents.py` 暴露了 `SAgent` 类。它的 `run_stream(...)` 方法是执行会话时最核心的运行时 API，负责组合：

- 输入消息
- 模型客户端与模型配置
- 工具和技能管理器
- 沙箱配置
- 智能体模式与流程选择

## 会话是状态承载单元

在 Sage 中，会话是执行的基本单位。一个会话会携带：

- 消息历史
- 任务进度
- 运行时锁
- 工具与技能访问能力
- 记忆和上下文预算设置

运行时通过 `sagents/session_runtime.py` 里的全局 session manager 创建或复用这些会话。

## 智能体模式

运行时支持多种执行风格：

- `simple`：直接单智能体交互
- `multi`：通过规划与执行智能体完成多步编排
- `fibre`：支持委派的高级多智能体编排

模式选择会影响 `SAgent._build_default_flow(...)` 内部组装的默认流程。

## 工具与技能

工具负责把外部能力暴露给运行时，例如执行命令、访问网络服务或代理 MCP。技能则提供结构化工作流与领域知识，指导模型如何完成一类任务。

## 沙箱与可观察性

Sage 把代码执行、命令调用和部分工具运行放进沙箱抽象中，以便控制权限边界。同时，运行时还集成了可观察性链路，方便排查性能和执行路径问题。
