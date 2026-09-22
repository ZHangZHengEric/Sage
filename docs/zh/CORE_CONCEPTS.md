---
layout: default
title: 核心概念
nav_order: 3
lang: zh
ref: v2-CORE_CONCEPTS
---

{% include lang_switcher.html %}

# 核心概念

| 概念 | 含义 |
| --- | --- |
| Agent 包 | 经过校验的配置，选择 Agent、模型、工具、Skills 与运行插件；可以来自 YAML 字符串、Python 对象或文件。 |
| Application | `SAgentApplication` 持有已装配的组件、服务和生命周期，使用后需要关闭。 |
| Session | 对话历史、Run、检查点和交互状态的权威来源。 |
| Run | Session 中的一次执行，可能完成、失败、取消，或暂停等待继续。 |
| Context | 从历史、指令、工具和派生记忆组装的模型请求投影。 |
| Interaction | 持久化的审批或用户输入请求。 |
| Host | Desktop、Server 或自建应用，负责身份、凭据、界面和会话索引。 |

## 执行过程

`StartRun → 组装上下文 → 模型调用 → 授权工具执行 → 后续步骤 → 完成或暂停`。

事件描述运行时已经接受的事实。关闭观察连接只会 detach，不会取消 Run；恢复、取消和交互回复使用明确的命令。暂停不等于任务完成。

摘要、记忆或诊断失败不能改写权威 Session 历史。无法确认结果的工具副作用需要核对，不能盲目重放。

[Python API](api/API_REFERENCE.md) · [架构](architecture/README.md)
