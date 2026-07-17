---
layout: default
title: 问卷格式
nav_order: 8.5
description: "Sage Inline Questionnaire 的 YAML 与 XML+JSON 协议"
lang: zh
ref: questionnaire-formats
---

{% include lang_switcher.html %}

# Sage 支持的问卷格式

Sage 的 Self-check 支持两种 Inline Questionnaire 编码：

1. fenced YAML
2. XML 标签包裹 JSON 对象

两种编码都正式可用。XML+JSON 没有被废弃，也没有迁移期限。

Inline Questionnaire 是 assistant 消息中的文本协议，与 Sage Server Web 中通过 `questionnaire` 工具调用创建的问卷不同。工具问卷拥有独立的会话、提交接口和 UI 卡片，不使用本文的 Inline Questionnaire 标签。

## 已注册的问卷名称

两种编码都使用以下五个注册名称：

| 名称 | 典型用途 |
| --- | --- |
| `yiii-questionnaire` | Yiii 集成 |
| `movo-questionnaire` | Movo / Sage Desktop 兼容流程 |
| `ling-questionnaire` | Ling 集成 |
| `sage-questionnaire` | Sage 命名空间 |
| `questionnaire` | 无业务前缀的通用格式 |

`foo-questionnaire` 之类的未知前缀不属于注册协议。Self-check 会要求使用上述名称之一重新输出。

对应的回答标签是在名称后追加 `-response`，例如 `yiii-questionnaire-response` 和 `questionnaire-response`。回答继续使用 XML+JSON，不使用 fenced YAML。

## fenced YAML

fenced YAML 适合模型或人工直接编写。问卷前必须先有一段非空普通说明文字，不能只发送问卷块。

当前事实和需要用户决定的边界已经整理完毕。

```yiii-questionnaire
title: "项目确认"
questions:
  - type: single_choice
    text: "下一步如何处理？"
    options:
      - "继续"
      - "调整"
    default: "继续"
    allow_other: true
  - type: multi_choice
    text: "需要调整哪些部分？"
    options:
      - "内容"
      - "风格"
    default: []
  - type: free_text
    text: "还有哪些约束？"
    default: ""
```

围栏名称可以替换为任一已注册名称。起始和结束围栏必须各自独占一行，结束围栏不能短于起始围栏。

### 顶层字段

- `title`：必填的非空字符串。
- `questions`：必填的非空数组。
- 不允许 `id`、`subtitle`、字段描述或其他额外字段。

### 题型规则

每个问题都必须包含 `type`、非空 `text` 和 `default`。

| `type` | `options` | `default` | `allow_other` |
| --- | --- | --- | --- |
| `single_choice` | 必填的非空字符串数组 | 必须等于其中一个选项 | 可选布尔值 |
| `multi_choice` | 必填的非空字符串数组 | 字符串数组，且每项都属于选项 | 可选布尔值 |
| `free_text` | 禁止 | 字符串，可以为空 | 禁止 |

fenced 内容必须使用块状 YAML。JSON 对象、XML、嵌套代码围栏和未知字段都会触发 Self-check 失败。

## XML+JSON

XML+JSON 适合已有生成器、历史会话和仍依赖该协议的客户端。它继续是受支持格式。

```xml
<yiii-questionnaire>{"title":"项目确认","questions":[{"type":"single_choice","text":"下一步如何处理？","options":["继续","调整"],"default":"继续"}]}</yiii-questionnaire>
```

开始标签和结束标签必须使用相同的已注册名称，标签内容必须是 JSON 对象。Self-check 保留各别名现有的兼容规则：`yiii-questionnaire` 继续校验 title、题型和 default；其他别名继续兼容已有扩展字段和 `{value, label}` 选项对象。

XML+JSON 不会被自动转换成 YAML。修复失败问卷时，可以保持 XML+JSON，也可以使用同一问卷名称改写为 fenced YAML。

## 回答格式

Inline Questionnaire 的回答继续使用 XML+JSON：

```xml
<yiii-questionnaire-response>{"id":"q_demo","title":"项目确认","answers":[{"index":0,"type":"single_choice","question":"下一步如何处理？","answer":"继续","answers":["继续"]}]}</yiii-questionnaire-response>
```

具体回答字段由提交该问卷的客户端决定，Self-check 要求顶层存在 `answers` 数组。

## Self-check 行为

Self-check 只检查当前用户消息之后最新的一条非空 assistant 回复。

- 合法 fenced YAML 和合法 XML+JSON 都会通过。
- 无效问卷会生成用户不可见的运行时诊断，并要求模型重新输出完整问卷。
- `self_check_required_structured_tags` 会保留所需的问卷名称，防止修复回复只输出解释文字而遗漏问卷。
- 同一名称可以在修复时切换编码，例如从无效 YAML 改成有效 XML+JSON。
- 未知前缀会要求重新使用任一已注册名称，不会把未知名称永久写入修复要求。

Self-check 不根据问号或自然语言关键词推断“是否应该提问”。是否需要问卷仍由 Agent Prompt、Skill 和业务流程决定。

## 客户端渲染能力

Self-check 通过只表示运行时协议有效，不保证每个客户端都能把该编码渲染成可交互卡片。

| 客户端 | fenced YAML | XML+JSON | questionnaire 工具调用 |
| --- | --- | --- | --- |
| Sage Desktop | 当前不渲染为 Inline 卡片 | `movo`、`ling`、`sage`、无前缀 | 不适用此 Inline 渲染器 |
| Sage Server Web | 当前不渲染为 Inline 卡片 | 当前不渲染为 Inline 卡片 | 支持 |
| Yiii Flutter | `yiii-questionnaire` | 五种注册名称 | 不适用此 Inline 渲染器 |

生成问卷前应同时确认目标客户端支持对应编码和名称。不要仅因为 Self-check 支持某种格式就假设客户端已经支持显示或提交。

## 常见错误

### 只发送问卷块

fenced YAML 前必须有普通说明文字。XML+JSON 的消息包装规则由具体 Agent Prompt 和客户端合同决定。

### 单选默认值不在选项中

```yaml
type: single_choice
text: "下一步如何处理？"
options:
  - "继续"
  - "调整"
default: "稍后"
```

应把 `default` 改成 `继续` 或 `调整`。

### 在 YAML 围栏中放 JSON

名为 `yiii-questionnaire` 的围栏内必须写块状 YAML。需要输出 JSON 时，应使用对应的 XML+JSON 格式。
