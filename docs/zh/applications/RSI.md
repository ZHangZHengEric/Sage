---
layout: default
title: Agent Package 优化（RSI）
parent: 应用入口
nav_order: 4
lang: zh
ref: v2-applications-RSI
---

{% include lang_switcher.html %}

# Agent Package 优化（RSI）

RSI 按设定轮数对输入的 Agent package 进行评测和调优，使用已有模型及宿主绑定的能力，不训练模型权重，也不会自动替换原 Agent。可以使用独立 Python API，或从 Desktop 的 Agent 配置启动后台任务。

## 运行流程

1. 提供 package、授权目标、优化范围和测试集。未提供测试集时，可由测试设计 Agent 生成。支持单轮任务与设有轮数上限的多轮对话。
2. 独立生成并固定验证题，默认 24 道，可配置数量；训练题独立生成，并在每轮继续补充挑战当前 Agent。测试集审查 Agent 检查目标、评分标准、权限和执行条件的一致性，不判断题目泄露或背题。
3. 目标 Agent 使用新 Session 执行基线测试。每个案例由独立的评测 Session 根据评分标准和实际执行证据判断。
4. 调优 Agent 根据训练反馈和匿名验证分数提出范围内的修改。独立 Session 的语义审查 Agent 在执行候选前检查目标漂移及权限漂移。原始指令保持不变，可编辑的指令指导作为额外部分追加。
5. 在同一套累计训练题和固定验证题上比较候选与当前版本。整体分为训练均分与验证均分各占 50%；达到最小整体增益即可采纳，允许局部退步。退步训练题持续反馈给调优 Agent，从更好的版本继续修复；验证仍只提供匿名分数。
6. 达标后完整复测确认稳定；也可因停滞、轮数或时限退出。即使尚未稳定达标，也保留整体更好的候选和完整历史，但不标记推荐，不自动应用。人看的 test 观察独立于这些判断，不作为收敛门槛。

桌面默认另设 12 道只给人看的 test；可设置 0–100 道。test 在基线及每轮保留版本上测量，展示三条分数曲线和逐题点阵。它使用独立会话、单独存储，既不进入任何调优请求，也不参与接受、选版和退出；测试故障显示为测量错误。

每次内部 Agent 调用使用新 Session。调优反馈包含验证汇总与稳定匿名编号的逐题分数，不包含验证题目、原始编号、答案或评分理由。反复用于选择的验证分数不能证明未见任务质量；标准基准可在 RSI 外冻结候选后独立测量，参见 [τ-bench 实验说明](TAU_BENCH.md)。显式 `validation_case_count=None` 仅为旧 SDK 客户端保留历史固定题和可选终测路径。

## Python API 与可优化范围

参见[完整 API 与示例](https://github.com/ZHangZHengEric/Sage/blob/main/sagents/v2/optimization/README.md)。`AgentPackageTestGenerator` 也可独立生成可审查的问题集合；用户可以直接提供 `OptimizationSuite` 与 `OptimizationFinalSuite`。

`optimize(..., rounds=10, optimization_scope=("skills",), constraints=...)` 限制本次允许修改的部分。支持 `instructions`、`skills`、`tools`、`budgets`、`resources`，可以组合。范围选择不会授予文件或能力权限：constraints 仍需分别允许可编辑文件、新建路径、Tool/Skill 候选和预算字段。新增 Tool/Skill 名称需要宿主提供可用且授权的绑定。工具源码实现、模型路由、凭据、策略和执行流程仍受保护。

设置 `suite_reviewer=OptimizationAgent(...)` 可使用专门的审查 package 和模型路由；默认使用评测 package 加宿主审查原则，并单独创建 Session。有阻断问题时，在目标或调优调用前抛出 `OptimizationSuiteReviewRejected`，其 `review` 和 `call` 保留审查证据。成功报告保留 `suite_review`。

`result.iterations` 包含原版与每个有效候选的完整 package、修改、审查和已有测试记录。无效提案留在报告中，但不产生可执行 package。可选的 `journal_path` 持续保存进度和失败前的证据；中止时没有正常结果，也不会自动重放调用。提供给模型的反馈限制诊断片段和历史提案数量，调用方可见的完整记录仍保留。宿主还应配置 token、资源预算和超时；片段截断不等于完整提示词预算。

## Desktop 历史与应用确认

Agent 配置提供独立的 **RSI** 和 **版本历史** 入口。RSI 页面显示后台运行历史及每轮候选；Agent 层级的版本历史显示人工保存和确认应用的配置版本。尚未应用的 RSI 候选保留在对应运行记录中。

离开页面不会停止 sidecar 中的后台任务。重新进入可以查看持久化进度、测试回答和审查问题。sidecar 退出后，未完成任务标为 interrupted，未知结果的模型或工具调用不会自动重放。

调优不改变当前配置。用户需预览版本，点击“使用此版本”，再明确确认。后端检查当前配置指纹，拒绝覆盖已变化的配置，也拒绝未完成或语义审查不通过的候选。用户选择其他已完成迭代时，可以看到该版本是否接受了最终测试。

Desktop 当前支持 simple Agent、原生工具、临时工作区和宿主沙箱限制。Shell 测试绑定、MCP 与非 simple Agent 尚不支持。任务由单个 sidecar 持久化，不提供分布式接管或自动断点续跑。参见[Desktop 实现指南](https://github.com/ZHangZHengEric/Sage/blob/main/app/v2/desktop/README.md#rsi-与-agent-版本)。

## 真实模型实验

显式启用的[垂类实验脚本](https://github.com/ZHangZHengEric/Sage/blob/main/examples/v2/optimizer_domains.py) 通过 `--catalog` 显式读取 JSON 模型目录中的 `openai-responses` 提供者，产生真实模型费用。它导出原始 package、每轮 package、测试集、模型调用与 Session 证据、评测、审查和对比摘要。凭据只在内存中解析，输出目录必须是新目录，不会激活生产 Agent。

2026-10-12 的只优化 Skill 与工具选择实验分别达到最终测试 3/3。联合范围也达到 3/3，但只修改了 Skill，尚未验证指令与 Skill 同时修改。三组均执行四轮提案，第一轮接受后，后续轮次没有新修改。Skill/工具组复用了以前实验的最终题目，只能作为回归验证；明确精度约定后的联合组使用新封存题目。评估结果时应保留失败记录和审查拒绝，不能将这些小样本结果作为 RSI 普遍可靠性的证明。
