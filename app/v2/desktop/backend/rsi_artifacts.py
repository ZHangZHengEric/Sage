"""Human navigation for an isolated Desktop RSI experiment directory."""
from sagents.v2.optimization.evaluation_files import save_private


def write_directory_index(root):
    save_private(root / 'README.md', '''# 本次 RSI 优化实验

`round-000` 是基线，`round-001` 起是候选迭代。目录随对应阶段完成而生成。

- `evaluations/round-NNN/<case-key>/trial-NNN/<input-hash>/`：独立评估调用。
  - `conversation.json`：单次执行的消息、工具调用及结果；`context.json`：指令和评分依据。
  - `assessment.json`：评估角色通过文件工具写出的 JSON。
  - `validation.json`：框架检查结果及不合格原因。重评保留不同输入记录。
- `workspace/iterations/round-NNN/input/training-evidence/`：本轮调优读取的父版本分析。
- `workspace/iterations/round-NNN/editor/evidence/training-evidence/`：调优方的只读分析副本。
  - `index.json`：入口；`mixed/`、`failed/`、`passed/` 分别是有对有错、全部错误、全部正确。
  - 每题由 `index.json` 链接 `execution-NNN.json`、`assessment-NNN.json`，分别保存逐次对话和评分；成败对照为 `comparison.json`。
  - `experience.md`：本轮调优前先读的累计经验，入口在原有 `index.json`；仅包含此前尝试及训练证据。
- `workspace/iterations/round-NNN/editor/package/`：本轮可编辑的候选配置与资源。
  - `manifest.json`、`dependencies.json`、`files/prompts/`、`files/skills/`、`files/tools/`。
- `workspace/iterations/round-NNN/version/package/`：校验后封存并用于推理的候选包。
- `workspace/iterations/round-NNN/evaluation/training-evidence/`：该候选的训练执行和分类分析。
- `workspace/iterations/round-NNN/validation-scores.json`：宿主与人工审计使用的匿名 dev 得分，不进入调优方 evidence。
- `workspace/iterations/round-NNN/proposal.json`、`decision.json`：实际差异与采纳结论。
- `workspace/iterations/round-NNN/experience.md`：本轮结束后的累计经验快照；采纳状态与调优方假设分开记录。
- `human-test/`：仅供人查看的 test 执行、评估和分数，不提供给调优方。
- `audit*.jsonl`、`result.json`、`resume-context.json`：运行审计、完成结果、恢复上下文。

评估的输入目录只读；只有 assessment 输出可写。评估 JSON 不合格时重跑评估，不重跑目标执行。
若配置了自定义评分器，评估说明不能更改其数值分数。调优方只能修改本轮获准的 package 资源。
原始 Agent 保持不变，只有显式应用版本才更新。
''')
