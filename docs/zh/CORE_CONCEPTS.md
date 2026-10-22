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
| Session | 保存一段对话的历史，以及其中各次任务的状态、检查点和待处理交互。 |
| Run | Session 中的一次执行，可能完成、失败、取消，或暂停等待继续。 |
| Context | 这一次实际发给模型的内容，由指令、选取的历史、工具说明和相关记忆组成。 |
| Interaction | 持久化的审批或用户输入请求。 |
| Host | Desktop、Server 或自建应用，负责身份、凭据、界面和会话索引。 |

## RSI 的职责划分

| 角色 | 职责 |
| --- | --- |
| Designer | 设计固定 dev 与训练题集，后续根据当前版本扩展训练挑战。 |
| Runner | 在新的 Session 中执行目标版本，保留实际输出与工具证据。 |
| Evaluator | 在独立 Session 中按 rubric 逐题评分；所需评测完成后才汇总训练反馈。 |
| Tuner | 根据训练证据与匿名 dev 分数，提出授权范围内的 Package 补丁。 |
| Reviewer | 分别审查题集一致性与候选目标、权限边界；不代替执行评测。 |

基线覆盖初始题集。后续默认补测新增 train，已有案例沿用对应版本的评测证据；候选按相同累计 train 与固定 dev 对比。内部角色名称表示职责，评测和优化使用独立 Session；默认复用的模型或 Package 不代表共享对话上下文。

RSI 不训练模型权重，也不自动应用候选。[流程与支持范围](applications/RSI.md)。

## 执行过程

`StartRun → 组装上下文 → 模型调用 → 授权工具执行 → 后续步骤 → 完成或暂停`。

例如，在同一段对话中先让 Agent 读取文件，再发一个请求让它修改文件，通常对应同一个 Session 中的两次 Run。第二次 Run 如果需要审批，会暂停等待用户决定；审批请求和执行进度保存在 Session 中。

事件用于报告已经发生的状态变化。断开事件流只停止接收通知，不会取消任务。要恢复、取消或回复审批，必须发送对应命令。暂停不等于完成。

摘要、记忆或诊断失败不能改写权威 Session 历史。无法确认结果的工具副作用需要核对，不能盲目重放。

[Python API](api/API_REFERENCE.md) · [架构](architecture/README.md)
