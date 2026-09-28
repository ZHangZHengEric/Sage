---
layout: default
title: 记忆与上下文
nav_order: 7
lang: zh
ref: v2-memory-README
---

{% include lang_switcher.html %}

# 记忆与上下文

## 四层不同职责

| 层次 | 数据归属与用途 |
| --- | --- |
| SessionStore | 权威 Session 历史、Run 状态与事件。 |
| Context | 本次发送给模型的内容，只包含预算内选取的历史和指令。 |
| 派生状态 | 由历史生成的摘要等数据；摘要失败或重建不改变原始消息。 |
| Memory provider | 长期记忆，以及对未进入当前上下文的会话历史进行检索。 |

例如，一段对话很长时，模型可能只看到旧消息的摘要和最近的完整消息，SessionStore 仍保留原始事件。需要查找没有放进本次请求的细节时，可由配置的 Memory provider 检索。

上下文压缩不会删除原始 Session 事件。固定指令和必须保留的当前回合受到预算保护，无法容纳时明确报错，不会静默删除约束。

Skill 加载有独立的活跃上下文预算。供应商报告的 usage 可校准输入估算，但不能编造缺失 usage，或把估算声称为供应商实测 token。

Desktop 摘要保存在所选 SessionStore 的 derived namespace。工作区身份与记忆文件属于工作区，不替代 Session 存储。无论本地摘要还是 SQL 持久化，都不代表可以自动重放结果不明的工具副作用。

[上下文预算](../architecture/sagents-v2-context-budget.md) · [运行时参考](https://github.com/ZHangZHengEric/Sage/blob/main/sagents/v2/README.md)
