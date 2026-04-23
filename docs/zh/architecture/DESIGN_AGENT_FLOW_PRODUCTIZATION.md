---
layout: default
title: AgentFlow 产品化设计提案
parent: 架构
nav_order: 99
description: "把 AgentFlow 升级为「真正的 Agent Flow」：所有 AI 节点都是 Agent，静态图可保存可重置"
lang: zh
ref: design-agent-flow-productization
---

{% include lang_switcher.html %}

# AgentFlow 产品化设计提案

> 状态：**设计稿（未实施）**  
> 作者：Eric ZZ  
> 目标读者：Sage 内核与产品团队

---

## 0. TL;DR

1. **理念**：所有出现 LLM 调用的地方都必须以「**Agent**」承载，包括「分类/路由/抽取」这些过去藏在 Python 函数里的判断步骤。**整条 Flow 中的每一个 AI 节点 = 一个 Agent 实例**。
2. **新增「Agent 模板」概念**：Agent 不再只有一种形态。引入 `BusinessAgent`、`RouterAgent`（必要时再加 `JudgeAgent`、`ExtractorAgent`）等模板。**每个 Router 节点都是一个基于 `RouterAgent` 模板创建的 Agent 实例**，有自己的 ID、名字、模型、提示词、标签集合，可在多个 Flow 中复用。
3. **AgentFlow 升级为一等资源**：拥有 `id / version / nodes / edges / inputs`，**可保存为静态 JSON 图**；引擎可由该 JSON 完全重建并执行。
4. **数据平面**：在 `audit_status` 内划出保留子树 `flow_state.{input, vars, steps}`，作为 v1 的 Flow 变量存储后端；对外只暴露点路径命名空间，**用户不接触内核字段**。
5. **分支判据**：`Switch / Decision` 通过点路径读取 `flow_state.steps.<router_step_id>.output.label` 等字段；`RouterAgent` 通过专属虚拟工具 `__set_router_state__` 强约束输出，结果落盘到 `flow_state`。

---

## 1. 背景与动机

### 1.1 当前现状（事实）
- `sagents/flow/` 已有完整的声明式编排：`AgentNode / SequenceNode / ParallelNode / IfNode / SwitchNode / LoopNode`；`FlowExecutor` 递归执行。
- `SAgent._build_default_flow` 内置 hybrid 流程；`SAgent.run_stream(custom_flow=...)` 已支持自定义 Flow 注入。
- `IfNode.condition` 走 `ConditionRegistry`（Python 装饰器注册的内置条件）。
- `SwitchNode.variable` 直接读 `session_context.audit_status[...]`，再 fallback 到 `system_context`；**字段名硬编码、平铺、无命名空间**。
- `AgentNode.agent_config` 字段在 schema 中存在，**但 `FlowExecutor` 没把它透传**（代码内有 TODO 注释）。
- `_agent_registry` 是写死在 `session_runtime.py` 里的字典：`simple / task_analysis / task_planning / task_executor / ...` 等内核阶段。**没有「用户创建的 Agent」一等公民概念能被 Flow 节点引用**。

### 1.2 用户实际在做的事
不少用户在用「多个 Agent 自己拼成一条流水线」。今天他们只能：
- 多次调用 API 在外部串接；或
- 用一个大 Agent 在 prompt 里假装走流程。

### 1.3 我们要解决的问题
- 让用户**在产品里把多个 Agent 组成一条可保存、可重置、可复用的 Flow**。
- Flow **必须支持分支**（线性流不够用）。
- 分支判据**必须以 Agent 形式存在**——不能再是「运维去注册一个 Python 条件」。
- Flow 必须能 **以 JSON 持久化**，并能从 JSON 完全重建运行。

---

## 2. 设计原则

1. **Everything is an Agent**：流程中所有调用模型的步骤一律用 Agent 承载；不存在「Router 是某种特殊的非 Agent 节点」。
2. **Agent 是模板 + 实例的二级结构**：模板决定能力边界，实例是用户配置的具体值。**Flow 节点只引用实例的 `agent_id`**。
3. **静态图先于动态图**：固定 AgentFlow 与 Fibre 互补——AgentFlow 强约束、可预测、可审计；Fibre 高灵活、动态委托。两者并存，**用户按场景选**。
4. **变量来源收敛到 4 个命名空间**：`flow.input.*` / `vars.*` / `steps.<id>.output.*` / `system.*`；UI 上用统一的「变量选择器」选择，禁止用户写自由表达式访问 `audit_status`。
5. **保存即校验**：图保存时做 DAG 序、引用存在性、类型匹配、Switch 覆盖性检查；运行时少惊喜。
6. **可观测优先**：每次执行高亮真实路径、记录每步输入/输出快照、变量时间线，便于排错「为什么走了这条分支」。

---

## 3. Agent 模板体系（Agent Type System）

### 3.1 总体模型

```
AgentTemplate（内核侧）
├── id: "router"
├── 配置 schema（哪些字段必填/选填、UI 怎么渲染）
├── 编译器：把实例配置 → 可执行的 Agent 对象（注入 prompt / 工具 / 模型）
└── 执行器钩子：如何写 flow_state、如何上报 trace 事件

AgentInstance（用户侧；当前 Agent 表的扩展）
├── id, name, owner_id, version
├── template_id ← 必填，指向某个模板
├── model: ModelConfig
├── config: 取决于模板（router 模板下是 labels/instruction/policy；business 模板下是 system_prompt/tools/skills/...）
└── 元数据：tags, description
```

**关键点**：
- 模板由内核定义，**用户不能新增模板**（v1 阶段）。
- 实例由用户在产品里创建，**模板决定它的可编辑字段**。
- Flow 节点只持有 `agent_id`，**不重复存配置**——这样 Agent 升级时所有引用它的 Flow 自动跟随（带版本控制策略，见 §8.2）。

### 3.2 内置模板（v1 范围）

| 模板 | 用途 | 输出形态 | 是否多轮 |
|------|------|----------|----------|
| `business` | 现有「Agent」，业务对话/工具循环 | 自然语言 + 副作用 | 是 |
| `router` | 分类 / 路由 / 状态判定 | 严格 JSON（标签或自定义 schema） | 否（单轮强约束） |

**v2/v3 候选**（不在本文档实施范围）：
- `extractor`：从消息中抽取结构化字段（更通用的 router）
- `judge`：对前序产物做合规/质量评分
- `summarizer`：固定输出摘要

### 3.3 `RouterAgent` 模板规格（核心）

#### 3.3.1 实例配置 schema

```jsonc
{
  "template_id": "router",
  "name": "意图分类器",
  "model": {                       // 单独模型，建议小模型
    "provider_id": "...",
    "model": "gpt-4o-mini",
    "temperature": 0
  },
  "config": {
    "instruction": "根据对话判断用户意图。",
    "input": {
      "include_history": "last_user",   // none | last_user | last_n:N | full
      "extra_vars": []                  // 注入的额外 flow 变量列表
    },
    "output": {
      "mode": "labels",                 // labels | schema
      "labels": [
        { "value": "refund",       "desc": "退款相关" },
        { "value": "tech_support", "desc": "技术问题" },
        { "value": "sales",        "desc": "售前咨询" }
      ],
      "include_confidence": true,
      "include_reason": true
      // —— 或 schema 模式 ——
      // "mode": "schema",
      // "schema": { "type": "object", ... JSON Schema ... }
    },
    "policy": {
      "min_confidence": 0.6,
      "on_low_confidence": "default",   // default | fail | passthrough
      "default_label": "tech_support",
      "retry": 1,
      "timeout_ms": 8000
    }
  }
}
```

#### 3.3.2 编译期行为
内核把 RouterAgent 实例编译成可执行 Agent 时：
1. 自动拼装 system prompt：`instruction` + 标签列表（含 desc）+ 输出契约说明。
2. 注册一个**实例专属的虚拟工具** `__set_router_state__(payload)`，其参数 schema 由 `output.labels` / `output.schema` 推导得出。
3. 在 prompt 末尾追加硬约束：「**完成判断后必须调用 `__set_router_state__` 提交结果，不要输出其他内容**」。
4. （能力允许时）模型调用同时打开 `response_format=json_schema` 或 `tool_choice="required"`，进一步缩小失败面。

#### 3.3.3 运行期行为
- 单轮、单工具调用即结束；不进入多轮 tool-loop。
- 工具被调用时，引擎拦截 payload：
  - 校验 schema、置信度、是否在标签集合内；
  - 不通过 → 按 `policy.on_low_confidence` 处理（走 default / 失败 / 透传上一节点输出）；
  - 通过 → 写入 `flow_state.steps.<step_id>.output`（**`step_id` 来自 Flow 节点，不是 Agent 实例 id**，见 §4.2）。
- 不并入主消息历史（默认 `isolate_messages=true`），避免污染对话上下文。

#### 3.3.4 与「业务 Agent」的隔离
- RouterAgent 实例**不会**出现在「Chat 选择 Agent」的下拉里。
- 在 Agent 列表 UI 中以独立 tab 或筛选项展示（type=router）。
- API 层强制：调用 `/chat` 等会话接口时，`agent_id` 必须指向 `business` 模板的实例；指向 `router` 实例直接报错。

### 3.4 与现有 `_agent_registry` 的关系

今天 `session_runtime._agent_registry` 是「字符串 → Agent 类」的固定字典，承载内核阶段（`task_router`、`task_planning` 等）。改造后：

- 内核阶段保留在该字典里，作为 **隐式系统 Agent**，仅供内置 `_build_default_flow` 引用。
- 用户编排的 Flow 节点引用 `agent_id`（实例 ID），由 `FlowExecutor` 在执行前 **从 Agent 实例服务加载 → 走模板编译器 → 得到运行时 Agent 对象**。
- `AgentNode` schema 拆为两个互斥字段：
  - `agent_key: str`：内核阶段引用（向后兼容）；
  - `agent_id: str`：用户实例引用（新）。

---

## 4. 静态图配置（AgentFlow Graph Spec）

### 4.1 顶层结构

```jsonc
{
  "schema_version": "1.0",
  "id": "flow_01HXYZ...",
  "name": "客服自动分流 v3",
  "description": "...",
  "version": 7,                       // 该 flow 的修订号
  "owner_id": "user_xxx",
  "tenant_id": "tenant_xxx",
  "created_at": "...",
  "updated_at": "...",
  "tags": ["customer-service"],

  "inputs": [                         // 启动 Flow 时必须 / 可选传入的参数
    { "name": "customer_tier", "type": "string", "required": true,  "enum": ["std","vip"] },
    { "name": "language",      "type": "string", "required": false, "default": "zh" }
  ],

  "model_defaults": {                 // 可选：图级缺省模型，节点未指定时使用
    "provider_id": "...",
    "model": "..."
  },

  "graph": {                          // 节点+边（DAG），不再嵌套树
    "nodes": [ ... ],
    "edges": [ ... ]
  },

  "ui": {                             // UI 布局信息，引擎忽略
    "layout": { "node_xxx": { "x": 120, "y": 80 } }
  }
}
```

> **重要变更**：从今天的「**嵌套树**（root → SequenceNode → ...）」改为「**节点 + 边的 DAG**」表示。  
> 原因：嵌套树在产品 UI 上画不出真实图；而且 `Switch` 多分支用嵌套表达后，节点没有稳定 ID，**无法被外部引用**（这正是「`steps.<id>.output`」依赖的前提）。  
> 兼容：内部仍可由 DAG 推导出等价的递归执行序，旧的内置 hybrid Flow 转写为 DAG 即可。

### 4.2 节点 ID 与引用

- **每个节点必须有 `id`**（图内唯一，字符串，建议 `snake_case`）。
- **`step_id`** 是节点在 `flow_state` 写入路径里的别名；默认等于 `node.id`，可单独覆盖以便重命名。
- 节点之间通过 `edges` 连接：`{ "from": "<node_id>", "to": "<node_id>", "condition": null }`；条件性边由 `Switch` 节点出边的 `case` 字段决定（见下）。

### 4.3 节点类型清单

| `type` | 说明 | 关键字段 |
|--------|------|----------|
| `agent` | 调用一个 Agent 实例（business 或 router） | `agent_id`, `agent_config_override?`, `isolate_messages?` |
| `switch` | 按变量值多路分发 | `variable`(点路径), `cases`, `default` |
| `decision` | 单条件分支（If 的产品化版本） | `variable`, `predicate`, `literal`, `true_to`, `false_to` |
| `loop` | 子图循环 + 退出条件 | `body_subgraph_id`, `condition_var`, `condition_predicate`, `max_loops`, `timeout_ms` |
| `parallel` | 并行扇出 + 汇合 | `branches[]`, `join`(all\|any\|n_of_m), `max_concurrency` |
| `set_var` | 显式写 `flow_state.vars.*` | `target`(`vars.xxx`), `value_from`(变量) 或 `value_literal` |
| `start` / `end` | 入口与出口标记，可有多个 end | — |

> **没有独立的 RouterNode**：路由步本身就是一个 `agent` 节点，`agent_id` 指向某个 `template=router` 的实例。这就是「整条流里所有 AI 节点都是 Agent」的体现。

### 4.4 节点字段细则

#### 4.4.1 `agent` 节点
```jsonc
{
  "id": "intent",
  "type": "agent",
  "agent_id": "agt_router_intent_xxx",
  "agent_config_override": null,        // 可选；不为空时合并到实例 config 之上
  "isolate_messages": true,             // router 默认 true，business 默认 false
  "output_schema_override": null,       // 仅对 router 有意义；不填用实例自身 output 配置
  "on_error": { "policy": "fail" }      // fail | retry:N | skip | goto:<node_id>
}
```

#### 4.4.2 `switch` 节点
```jsonc
{
  "id": "by_intent",
  "type": "switch",
  "variable": "flow_state.steps.intent.output.label",
  "cases": {
    "refund":       "refund_handler",
    "tech_support": "tech_handler",
    "sales":        "sales_handler"
  },
  "default": "human_handoff",           // 强制必填或显式 "fail"
  "default_action": "goto"              // goto | fail | end
}
```

#### 4.4.3 `decision` 节点
```jsonc
{
  "id": "is_vip",
  "type": "decision",
  "variable": "flow_state.input.customer_tier",
  "predicate": "equals",                // equals | not_equals | in | not_in | contains | regex | gte | lte | is_empty | is_truthy
  "literal":   "vip",
  "true_to":   "vip_path",
  "false_to":  "std_path"
}
```

#### 4.4.4 `loop` 节点
```jsonc
{
  "id": "review_loop",
  "type": "loop",
  "body_subgraph_id": "sg_review",      // 引用图内子图
  "exit_when": {
    "variable": "flow_state.vars.approved",
    "predicate": "is_truthy"
  },
  "max_loops": 5,
  "timeout_ms": 120000
}
```

### 4.5 完整示例（最小可运行）

```jsonc
{
  "schema_version": "1.0",
  "id": "flow_demo",
  "name": "客服分流 demo",
  "version": 1,
  "inputs": [
    { "name": "language", "type": "string", "required": false, "default": "zh" }
  ],
  "graph": {
    "nodes": [
      { "id": "start",  "type": "start" },
      { "id": "intent", "type": "agent", "agent_id": "agt_router_intent",
        "isolate_messages": true },
      { "id": "by_intent", "type": "switch",
        "variable": "flow_state.steps.intent.output.label",
        "cases": {
          "refund":       "refund_agent",
          "tech_support": "tech_agent",
          "sales":        "sales_agent"
        },
        "default": "fallback_agent",
        "default_action": "goto" },
      { "id": "refund_agent", "type": "agent", "agent_id": "agt_business_refund" },
      { "id": "tech_agent",   "type": "agent", "agent_id": "agt_business_tech" },
      { "id": "sales_agent",  "type": "agent", "agent_id": "agt_business_sales" },
      { "id": "fallback_agent","type":"agent", "agent_id": "agt_business_human" },
      { "id": "end",    "type": "end" }
    ],
    "edges": [
      { "from": "start",          "to": "intent" },
      { "from": "intent",         "to": "by_intent" },
      { "from": "refund_agent",   "to": "end" },
      { "from": "tech_agent",     "to": "end" },
      { "from": "sales_agent",    "to": "end" },
      { "from": "fallback_agent", "to": "end" }
    ]
  }
}
```

---

## 5. 数据平面（flow_state）

### 5.1 命名空间

对外（用户在 UI 看到、在变量选择器里选到）只有：

```
flow_state.input.<name>           # 启动时传入的入参（只读）
flow_state.vars.<name>            # set_var 节点写
flow_state.steps.<step_id>.output.<field>   # router/agent 节点的产物
system.<name>                     # 引擎内建（last_error, elapsed_ms, loop_count 等）
```

### 5.2 与 `audit_status` 的关系（v1 实现策略）

为最小化改动：
- v1 **物理上**寄存于 `session_context.audit_status["flow_state"]` 子树；
- `SwitchNode/Decision/Loop` 内部统一通过一个 **路径解析器** 取值，路径以 `flow_state.` 或 `system.` 开头；
- 老的 `IfNode.condition` + `ConditionRegistry` 保留作为 **`system.<condition_name>` 的内部封装**，平滑兼容。

未来（v2+）可把 `flow_state` 提升为 `SessionContext` 的一等字段，对外 API 不变，仅内部字段重命名。

### 5.3 写入约束

- `flow_state.input.*`：只允许 Flow 启动时由 runtime 一次性写入；执行过程中不可变。
- `flow_state.steps.<step_id>.output`：**只允许该 `step_id` 所属节点写**；引擎在工具拦截 / Agent 完成回调里强制此约束。
- `flow_state.vars.*`：仅 `set_var` 节点可写（或显式开放 business agent 通过 `__set_var__` 工具写，可选项）。

### 5.4 路径解析器（伪代码）
```python
def resolve_path(ctx, path: str):
    # path 形如 "flow_state.steps.intent.output.label" / "system.last_error"
    if path.startswith("system."):
        return resolve_system_var(ctx, path[7:])
    if path.startswith("flow_state."):
        node = ctx.audit_status.get("flow_state", {})
        for part in path.split(".")[1:]:
            if not isinstance(node, dict): return None
            node = node.get(part)
        return node
    raise ValueError(f"Unsupported variable path: {path}")
```

---

## 6. 分支机制（再小结一遍，与 §3、§4 形成闭环）

### 6.1 路由的标准范式
1. 在「Agent 实例」页面创建一个 `template=router` 的 Agent，配置标签集合（如 refund / tech_support / sales）。
2. 在 Flow 编辑器里拖一个 `agent` 节点，`agent_id` 选这个 router 实例。
3. 在它后面接一个 `switch` 节点，`variable` 选 `flow_state.steps.<那个agent节点的id>.output.label`，配置 cases。
4. 各 case 连到对应的业务 `agent` 节点。

### 6.2 Decision vs Switch
- 二选一 → 用 `decision`（更轻、UI 更简单、可写 `gte/contains/regex` 等谓词）。
- 多选一（标签型）→ 用 `switch`（必有 default）。

### 6.3 失败与降级（节点级，不全局一刀切）
- 每个节点可配 `on_error: { policy: "fail|retry:N|skip|goto:<id>" }`。
- Router 节点额外有 `policy.on_low_confidence`，用于「模型给出标签但没把握」的特殊降级。
- `system.last_error` 自动维护，可作为下游 Decision 的判据（例如「上一步失败 → 走人工」）。

---

## 7. 执行语义

### 7.1 `FlowExecutor` 改造点
- 新增 DAG 解析器：把 `nodes + edges` 转为「就绪队列 + 依赖关系」；保持单线程主循环 + 并行节点 fork。
- `AgentNode` 执行入口拆为两条：
  - `agent_key` 路径 → 走老的 `_get_agent`（内核阶段）；
  - `agent_id` 路径 → 走新的 `AgentInstanceLoader.load(agent_id) → TemplateCompiler.compile(instance) → 返回 AgentBase 子类实例`。
- 透传 `agent_config_override`：合并到实例 config 之上，再做 schema 校验（**这是接通 Router 多实例不同标签的前提**）。
- 路径解析器统一用于 `Switch / Decision / Loop / Set Variable`。

### 7.2 RouterAgent 执行细节
1. 编译：实例 config + 节点 override → prompt + 虚拟工具 schema。
2. 调模型：单轮，`tool_choice="required"`（或对应等价物）。
3. 工具回调拦截：
   - 校验 payload；
   - 写 `flow_state.steps.<step_id>.output = payload`；
   - 终止本节点循环（不进入下一轮 tool-loop）。
4. trace 事件：`router_decided`，包含 input 截断、原始模型输出、parsed payload、最终 label、置信度、走的分支。

### 7.3 子作用域 / 消息隔离
- `agent` 节点上有 `isolate_messages` 开关：
  - `false`（默认 business）：messages 并入主历史，业务对话连续。
  - `true`（默认 router）：本节点产生的 messages 只用于该节点内部，不并入主历史。
- 并行 `parallel` 节点的子分支强制 `isolate=true`，避免多分支同时写 history 造成 race。
- 子作用域结束时，仅显式声明的 `output.*` 才能被外部引用。

---

## 8. 持久化与重置

### 8.1 存储模型（建议）

| 表/集合 | 字段 |
|---------|------|
| `agent_template` | `id, name, version, schema, prompt_template, runtime_handler` —— 内置，不让用户写 |
| `agent_instance` | `id, name, owner_id, tenant_id, template_id, model, config(JSON), version, created_at, updated_at` |
| `flow` | `id, name, owner_id, tenant_id, latest_version` |
| `flow_version` | `id, flow_id, version, graph_json, schema_version, created_at, created_by, status(draft/published)` |
| `flow_run` | `id, flow_id, flow_version_id, session_id, started_at, finished_at, status, input_snapshot, output_snapshot` |

### 8.2 版本与引用一致性
- Flow 每次 publish 生成一个不可变 `flow_version` 行；执行严格按 `flow_version_id` 跑，**便于复现 / A-B**。
- Agent Instance 引用策略（v1 提供两档，flow 级别选择）：
  - **`pin_agent_version`**：Flow 保存时把每个引用的 agent 版本号一并固化，Agent 升级不影响 Flow——稳，但要主动升级。
  - **`follow_latest`**：Flow 总是取该 agent 当前 latest published 版本——便利，但 Agent 改坏会连带 Flow 出错。
- 默认 `follow_latest`，提供一键切换为 `pin_agent_version` 的开关。

### 8.3 重置（恢复）流程
给定一个 `flow_version.graph_json`，引擎重建过程：

```
1. validate_schema(graph_json) → 通过 schema_version 路由到对应解析器
2. resolve_references():
   - 检查所有 agent_id 存在、未被删除
   - 检查 input declared types 与传入参数一致
   - 检查所有 edges 的 from/to 节点存在
   - DAG 检查：无环 / 至少一个 start / 至少一个 end
   - 静态校验：变量路径合法、Switch case 完备、Loop 有 max_loops
3. compile_runtime_graph(): 节点 → 就绪队列结构
4. attach_session(session_id, flow_state.input = inputs)
5. FlowExecutor.run(runtime_graph) → 流式 yield messages
```

**「重置」的语义**：
- **完整重置**：清空 `flow_state`，从 `start` 重新执行（用于失败重试或 demo）。
- **从断点恢复**（v2 候选）：保留 `flow_state.steps.*`，从指定 `node_id` 继续；要求节点幂等或显式声明可重入。

---

## 9. 产品 / UI 表面

### 9.1 Agent 列表
- 增加「类型」筛选：业务 / 路由（/ 未来的 judge / extractor）。
- 创建 Agent 时第一步选模板，选完才进入对应字段编辑器。
- Router Agent 编辑器**不显示**「工具 / 技能 / 知识库」等业务字段，仅展示 `instruction / labels(or schema) / model / policy`。

### 9.2 Flow 列表 + 编辑器
- 独立顶层菜单 `Flows`，与 `Agents` 平级。
- 编辑器主体：左侧节点抽屉（agent / switch / decision / loop / parallel / set_var / start / end），中央 DAG 画布，右侧 Inspector。
- **统一变量选择器**（在所有「填变量」处复用）：
  ```
  来源 ▾  入参 / 节点输出 / 流程变量 / 系统
  路径 ▾  flow_state.steps.intent.output.label
  类型     string（自动推断）
  ```
- 保存动作：`Save Draft`（不校验）/ `Validate & Publish`（强校验）。
- Flow 详情页带「试运行」面板：填入参 → 流式看路径高亮 + 每节点 input/output。

### 9.3 与 Chat 集成（v2）
- 在 Chat 选择「会话载体」时，可选 Agent 实例 **或** Flow 实例。
- 选 Flow 时，按 `inputs` 弹一个轻量参数表单后发起会话。

---

## 10. 开放接口

### 10.1 HTTP API（草案）
```
# Flow CRUD
POST   /api/flow                     创建 flow（含初始 graph）
GET    /api/flow/:id                 获取 flow（含最新 published version）
GET    /api/flow/:id/versions        列出版本
POST   /api/flow/:id/versions        新增版本（publish）
GET    /api/flow/:id/versions/:ver   读取某版本 graph_json
DELETE /api/flow/:id

# 校验
POST   /api/flow/validate            传入 graph_json，返回校验报告

# 执行
POST   /api/flow/:id/run             以 latest published 跑
POST   /api/flow/:id/versions/:ver/run   指定版本跑
GET    /api/flow_run/:id             查询运行状态 + flow_state 快照

# Agent Templates
GET    /api/agent_template           列出可用模板（router / business / ...）
GET    /api/agent_template/:id       拿到 schema，前端据此渲染编辑器
```

### 10.2 SDK 侧
`SAgent.run_stream(...)` 增加 `flow_id` / `flow_version_id` 参数，与 `custom_flow` 互斥；内部走「**从仓库加载 graph_json → 重建 → 执行**」。

---

## 11. 实施路线（建议分阶段）

### Phase 1：让「Router 也是 Agent」最小闭环（约 1～2 周）
内核侧：
- [ ] `AgentNode.agent_config` override 在 `FlowExecutor` 中真正生效。
- [ ] 给 `AgentNode` 增加可选 `step_id`（默认等于 node id）。
- [ ] 引入 `AgentTemplate` 抽象 + `RouterAgent` 模板（含编译器、虚拟工具拦截、`flow_state` 写入）。
- [ ] `audit_status["flow_state"]` 子树落地 + 路径解析器；`SwitchNode.variable` 支持点路径。

验证方式：
- 手写一个 graph_json（不上 UI），通过 `custom_flow=...` 跑通「router → switch → 三个 business agent」。

### Phase 2：静态图与持久化（约 2～3 周）
- [ ] 定义 `schema_version=1.0` 的 graph JSON Schema（节点+边 DAG）。
- [ ] `flow / flow_version` 存储 + CRUD API。
- [ ] 静态校验器（DAG / 引用 / 类型 / Switch 覆盖性）。
- [ ] `FlowExecutor` 增加 DAG 模式（保留旧的嵌套模式做向后兼容）。

### Phase 3：UI 一期（约 3～4 周）
- [ ] Agent 创建分模板；Router Agent 专属编辑器。
- [ ] Flow 列表、画布编辑器、变量选择器、试运行面板。
- [ ] 运行历史 / 路径回放（轻量版）。

### Phase 4：加深与并行能力（视需求）
- [ ] `parallel` 节点真正并发执行 + join。
- [ ] `loop` 节点完整版（含子图）。
- [ ] Approval/Wait 节点（接你们已有的 INTERRUPTED + 续跑机制）。
- [ ] Agent 引用「pin 版本」开关。
- [ ] `extractor` / `judge` 模板。

---

## 12. 兼容性与影响面

- 旧的 `_build_default_flow` **保持不变**，作为内置 hybrid，仍以「嵌套树 + agent_key」形式存在；新引擎对两种表达都能跑。
- 旧的 `IfNode + ConditionRegistry` 视作 `system.<name>` 的封装；用户层不再暴露注册新 Python 条件这个口子。
- 现有 `availableWorkflows`（Agent 配置里那套字符串步骤说明）**和本设计无关**，保持原状，避免命名冲突；产品上注意文案区分（「Workflow / 工作流提示」 vs「Flow / 流程编排」）。

---

## 13. 待决问题（需要后续 Eric 拍板）

1. **`step_id` 与 `node.id` 是否允许独立**？v1 我倾向**强制一致**（一个 ID，少出错）；如果未来要支持「同一节点跑两次写两份输出」，再放开。
2. **Agent 实例的引用方式**：v1 默认 `follow_latest`，是否需要在租户级配置「全局强制 pin」？
3. **`set_var` 节点是否暴露给 UI**？还是只允许 router 写 `steps.*` 输出？后者更收敛，前者灵活。倾向：v1 暴露但仅作为「逃生通道」，UI 上以「高级节点」收起。
4. **Flow 是否能被另一个 Flow 引用**（subflow 节点）？长远很有价值，v1 不做，但 schema_version 预留 `subflow` 节点 type。
5. **Router 输出强约束实现**：优先级 = `__set_router_state__` 虚拟工具 > `response_format=json_schema` > 事后 JSON 解析。三档自动降级还是只走第一档？建议默认只走第一档，不支持的模型直接拒绝绑定到 Router Agent。
6. **多节点同时写 `flow_state.vars.*`** 的并发安全：v1 单线程主循环天然没问题；引入 `parallel` 后需要文档化「并行分支不应写同名 var，否则结果未定义」。

---

## 附录 A：核心代码改动点速查

| 文件 | 改动 |
|------|------|
| `sagents/flow/schema.py` | 引入 graph DAG 模型；保留旧嵌套模型；`AgentNode` 增加 `agent_id / step_id / agent_config_override / isolate_messages / on_error` |
| `sagents/flow/executor.py` | DAG 调度器；接通 `agent_config` override；统一路径解析器；Router 工具拦截 |
| `sagents/flow/conditions.py` | 重定位为 `system.*` 内置变量提供方 |
| `sagents/agent/templates/` （新建） | `AgentTemplate` 抽象 + `RouterAgent` 实现 |
| `sagents/session_runtime.py` | `_get_agent` 增加 `agent_id` 路径；引入 `AgentInstanceLoader` |
| `sagents/context/session_context.py` | 在 `audit_status` 上规范 `flow_state` 子树访问器 |
| `app/server/...` | flow CRUD API、agent_template API、agent_instance template_id 字段 |
| `app/server/web/...` | Agent 模板分流编辑器；Flow 列表与画布编辑器；变量选择器组件 |
| `docs/zh/ARCHITECTURE_SAGENTS_AGENT_FLOW.md` | 实施后同步更新架构文档 |

---

## 附录 B：术语对照

| 术语 | 含义 |
|------|------|
| Agent Template | 内核定义的 Agent 形态（business / router / ...） |
| Agent Instance | 用户在产品里基于模板创建的 Agent，有自己的 ID |
| AgentFlow（本设计） | 静态图 + DAG，由 `flow_version.graph_json` 持久化 |
| Step ID | Flow 节点写入 `flow_state.steps.*` 的命名空间键 |
| flow_state | Flow 运行期的变量平面，物理上寄存于 `audit_status.flow_state`（v1） |
| Router Node | 一个 `agent` 节点 + `agent_id` 指向 `template=router` 的实例（**不是**独立节点类型） |
