---
layout: default
title: 问卷提供方式
nav_order: 8.5
description: "Sage Inline Questionnaire 与 questionnaire_async 的协议、生命周期和前端接入规范"
lang: zh
ref: questionnaire-formats
---

{% include lang_switcher.html %}

# Sage 提供问卷的方式

本文说明 Sage 当前仍支持、且不阻塞运行线程等待答案的问卷方式：

1. assistant 文本中的 Inline Questionnaire；
2. `questionnaire_async` 工具调用。

原同步等待答案的 `questionnaire` 工具已从工具目录移除；旧会话仍可兼容展示其历史消息。

## 方式总览

| 方式 | 载体 | 主要用途 | 谁负责渲染 | 用户回答如何返回 |
| --- | --- | --- | --- | --- |
| fenced YAML | assistant `content` | 新生成的通用 Inline Questionnaire | 前端解析消息内容 | 下一条 user 消息中的 `<questionnaire-response>` JSON |
| XML+JSON | assistant `content` | Runtime 恢复问卷与 Sage 历史会话 | 前端解析消息内容 | 与请求名称对应的 `*-questionnaire-response` JSON |
| `questionnaire_async` | assistant tool call + tool result | 让 Runtime 校验、标准化问卷并结束当前执行轮次 | 前端关联 tool call 与 result | 下一条 user 消息中的 `<questionnaire-response>` JSON |

## Inline Questionnaire

Inline Questionnaire 是 assistant 消息中的文本协议，不是工具调用。前端必须在普通 Markdown 渲染之前识别协议块，并保留协议块前后文本的原始顺序。

### 新消息的标准格式

新代码统一生成无产品前缀的 `questionnaire` fenced YAML。问卷前必须有非空的普通说明文字。

````markdown
已达到本轮最大循环次数（50），任务已暂停。

```questionnaire
title: 任务已暂停
questions:
  - type: single_choice
    text: 是否继续当前任务？
    options:
      - 继续
    default: 继续
```
````

协议边界：

- 标准开始围栏必须独占一行，名称精确为 `questionnaire`；Sage 历史兼容读取也接受 `sage-questionnaire`；
- 开始围栏至少三个反引号；
- 结束围栏必须独占一行，且不能短于开始围栏；
- 围栏内容必须是块状 YAML，不能是 JSON；
- 问卷内部不能嵌套其他代码围栏；
- fenced 问卷不能成为整条 assistant 消息的唯一内容。

位于普通 fenced code、行内 code span 或四空格缩进代码块中的问卷示例只按 Markdown 代码显示，不会激活交互问卷。

### fenced YAML 字段

顶层只允许：

```yaml
title: 非空字符串
questions: 非空数组
```

不允许在顶层增加 `id`、`ui_text`、`timeout_seconds`、`subtitle` 或字段描述。

每个问题必须包含 `type`、非空 `text` 和 `default`。

| `type` | `options` | `default` | `allow_other` |
| --- | --- | --- | --- |
| `single_choice` | 必填的非空字符串数组 | 必须等于一个选项 | 可选布尔值 |
| `multi_choice` | 必填的非空字符串数组 | 字符串数组，且每项都属于选项 | 可选布尔值 |
| `free_text` | 禁止 | 字符串，可以为空 | 禁止 |

严格 fenced YAML 不接受 `multiple_choice`、`text` 等题型别名，也不接受 `{value, label}` 选项对象。

### Inline 回答协议

请求使用 Markdown + YAML，回答仍使用 XML-style 标签包裹 JSON。无前缀请求对应无前缀回答：

```xml
<questionnaire-response>{"type":"questionnaire_response","questionnaire_id":"MESSAGE_ID_q1","status":"submitted","answers":[{"question_id":"q1","question":"是否继续当前任务？","type":"single_choice","answer":"继续","value":"继续","label":"继续"}]}</questionnaire-response>
```

前端需要生成可重复的问卷和题目 ID：

- 问卷 ID 建议由 `message_id`、协议块序号共同生成；
- fenced YAML 没有题目 `id`，前端按顺序生成 `q1`、`q2`；
- 同一消息重新渲染后 ID 必须保持不变；
- `status` 当前使用 `submitted`；
- 顶层 `answers` 必须是数组。

Sage Desktop 为单选题同时发送 `answer`、`value` 和 `label`；多选题发送 `answer`、`values` 和 `labels`；文本题发送字符串 `answer`。

### XML+JSON 与别名边界

Sage Runtime 的重复执行恢复问卷仍使用无前缀 XML+JSON，以保留稳定的题目 ID 和本地化显示文字：

```xml
<questionnaire>{"title":"执行路径正在重复","questions":[{"id":"loop_recovery_action","type":"free_text","text":"请说明你希望我接下来如何处理","default":""}]}</questionnaire>
```

Sage Desktop 与 Server Web 只渲染以下两个请求名称及对应的 `-response`：

| 名称 | Sage 前端状态 |
| --- | --- |
| `questionnaire` | 标准名称 |
| `sage-questionnaire` | Sage 命名空间兼容读取 |

`yiii-questionnaire`、`movo-questionnaire` 和 `ling-questionnaire` 在 Sage 前端中按普通 Markdown 显示，不作为可交互问卷解析。

Sage Self-check 仍读取以下五个注册名称：

| 名称 | 状态 |
| --- | --- |
| `questionnaire` | 新消息的标准名称 |
| `yiii-questionnaire` | 后端注册名称，供 Yiii 自身客户端使用 |
| `movo-questionnaire` | 后端注册名称，供 Movo 自身客户端使用 |
| `ling-questionnaire` | 后端注册名称，供 Ling 自身客户端使用 |
| `sage-questionnaire` | Sage 命名空间兼容读取 |

XML+JSON 示例：

```xml
<sage-questionnaire>{"title":"项目确认","questions":[{"type":"single_choice","text":"下一步如何处理？","options":["继续","调整"],"default":"继续"}]}</sage-questionnaire>
```

开始和结束标签必须同名。回答标签在请求名称后追加 `-response`，前后标签名称必须精确匹配。未知的 `foo-questionnaire`、`questionnaire-response-extra` 不属于注册协议。

后端注册名称不等于 Sage 前端兼容范围。其他产品前端可以参考 Sage 的解析和卡片实现，但应只注册该产品自己的命名空间和无前缀名称。

### Self-check

Self-check 检查当前用户消息之后最新的一条非空 assistant 回复：

- 合法 fenced YAML 和合法 XML+JSON 都会通过；
- 无效问卷会产生用户不可见的诊断，要求模型重新输出完整问卷；
- 修复时可以在同一注册名称下切换编码；
- Self-check 只验证协议，不保证目标前端已经实现交互卡片；
- Self-check 不从问号或自然语言推断是否应该使用问卷。

### 前端实现要求

1. 在 Markdown normalization 和 rendering 之前扫描协议块；
2. 安全解析 YAML，不启用自定义类型；
3. 按消息原始位置拆成 Markdown、问卷和回答片段；
4. 解析失败时保留并显示原始文本，不能静默丢弃；
5. 只允许最新、非只读 assistant 消息中的问卷提交；
6. 提交后锁定表单，并在用户消息中保留可读答案；
7. 不要根据产品名称改写 `questionnaire`；
8. 深色和浅色主题属于客户端表现层，不属于传输协议。

Sage Desktop 与 Server Web 的参考实现：

- 解析和回答构造：[inlineQuestionnaire.js](../../app/desktop/ui/src/utils/inlineQuestionnaire.js)
- 分段渲染：[InlineQuestionnaireRenderer.vue](../../app/desktop/ui/src/components/chat/InlineQuestionnaireRenderer.vue)
- 交互卡片：[InlineQuestionnaireCard.vue](../../app/desktop/ui/src/components/chat/InlineQuestionnaireCard.vue)
- 协议测试：[inlineQuestionnaire.spec.js](../../app/desktop/ui/src/utils/__tests__/inlineQuestionnaire.spec.js)

Server Web 在 `app/server/web` 下提供同名解析器、渲染器、卡片和协议测试；两端保持相同的问卷别名与严格校验规则。

## `questionnaire_async`

`questionnaire_async` 是一次立即返回的问卷参数校验工具。它不会等待用户提交，不会轮询后端，也不会创建独立的问卷提交会话。

### 调用参数

```json
{
  "title": "继续执行",
  "questions": [
    {
      "id": "action",
      "type": "single_choice",
      "text": "是否继续当前任务？",
      "options": [
        {"value": "continue", "label": "继续"}
      ],
      "default": "continue",
      "allow_other": false
    }
  ]
}
```

`title` 可选。`questions` 必须是非空数组。

| 输入字段 | 规则 |
| --- | --- |
| `id` | 可选；缺失时生成 `q1`、`q2`；不能重复 |
| `type` | `single_choice`、`multiple_choice`、`multi_choice`、`text`、`free_text` |
| `text` / `title` | 至少一个非空；标准化为 `text` |
| `options` | 选择题必填；支持字符串或 `{value, label}` 对象 |
| `default` | 可选；必须符合标准化后的选项值和题型 |
| `allow_other` | 可选布尔值 |

题型标准化：

- `multiple_choice` → `multi_choice`；
- `text` → `free_text`；
- 字符串选项 → `{value: text, label: text}`；
- 缺省默认值：单选和文本为空字符串，多选为空数组。

### 成功结果

```json
{
  "success": true,
  "status": "awaiting_user_input",
  "validation_passed": true,
  "title": "继续执行",
  "question_count": 1,
  "questions": [
    {
      "id": "action",
      "type": "single_choice",
      "text": "是否继续当前任务？",
      "options": [
        {"value": "continue", "label": "继续"}
      ],
      "default": "continue",
      "allow_other": false
    }
  ],
  "should_end": true,
  "message": "问卷已发起并等待用户回复，共 1 题。"
}
```

成功后 SimpleAgent 终止当前执行轮次。Sage 前端从 tool result 读取标准化后的 `title` 和 `questions`，渲染同一套问卷卡片，并将答案包装为无前缀 `<questionnaire-response>`；该 user 消息会开启新的执行轮次。

### 校验失败

校验失败返回标准工具错误：

```json
{
  "success": false,
  "status": "error",
  "error_code": "INVALID_ARGUMENT",
  "validation_passed": false,
  "errors": [
    {
      "code": "questionnaire.start.default_type_invalid",
      "path": "questions[1].default",
      "message": "本地化错误信息",
      "details": {}
    }
  ]
}
```

前端应关联 assistant tool call 的 `id` 与 tool result 的 `tool_call_id`。只有成功 result 中的标准化 `questions` 适合直接渲染；失败 result 应显示参数错误，不应打开可提交问卷。

### 回答边界

当前 Runtime 没有为 `questionnaire_async` 定义独立提交接口、轮询流程、超时或服务端强制回答信封。Sage Desktop 与 Server Web 固定发送通用 `<questionnaire-response>` JSON，同时通过 `displayContent` 展示可读答案；Runtime 将它作为下一条 user 消息处理。

参考实现：

- 工具参数和标准化：[questionnaire_tool.py](../../sagents/tool/impl/questionnaire_tool.py)
- 成功后停止当前轮次：[simple_agent.py](../../sagents/agent/simple_agent.py)
- 工具测试：[test_questionnaire_tool.py](../../tests/sagents/tool/impl/test_questionnaire_tool.py)

## 两种方式的选择

| 需求 | 建议方式 |
| --- | --- |
| 需要在 assistant 正文的指定位置展示问卷 | fenced YAML Inline Questionnaire |
| 需要读取 Sage 历史会话问卷 | 无前缀或 `sage-` XML+JSON 兼容读取 |
| 需要模型通过工具参数构造问卷并由 Runtime 统一校验 | `questionnaire_async` |
| 非 Sage 前端尚未实现 tool call 问卷渲染 | fenced YAML Inline Questionnaire |

不要把 Self-check 支持、工具参数校验和客户端渲染能力混为一件事：三者分别由 Self-check、`questionnaire_async` 和各前端负责。
