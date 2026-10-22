"""Human navigation for an isolated Desktop RSI experiment directory."""
from sagents.v2.optimization.evaluation_files import save_private


def write_directory_index(root):
    save_private(root / 'README.md', '''# 本次 RSI 优化实验

`round-000` 是基线，`round-001` 起是候选迭代。目录随对应阶段完成而生成。

- `evaluations/round-NNN/<case-key>/trial-NNN/<input-hash>/`：独立评估调用。
  - `record.json`：精简的会话、实际工具参数与结果、该版本指令和评分依据。
  - `assessment.json`：评估角色通过文件工具写出的 JSON。
  - `validation.json`：框架检查结果及不合格原因。重评保留不同输入记录。
- `workspace/iterations/round-NNN/input/training-evidence/`：本轮调优读取的父版本分析。
- `workspace/iterations/round-NNN/editor/evidence/training-evidence/`：调优方的只读分析副本。
  - `index.json`：入口；`mixed/`、`failed/`、`passed/` 分别是有对有错、全部错误、全部正确。
  - 每题有 `analysis.md`、`assessment.json`、`execution.json`，包含各次执行和成败对照。
- `workspace/iterations/round-NNN/editor/package/`：本轮可编辑的候选配置与资源。
  - `manifest.json`、`dependencies.json`、`files/prompts/`、`files/skills/`、`files/tools/`。
- `workspace/iterations/round-NNN/version/package/`：校验后封存并用于推理的候选包。
- `workspace/iterations/round-NNN/evaluation/training-evidence/`：该候选的训练执行和分类分析。
- `workspace/iterations/round-NNN/validation-scores.json`：匿名 dev 得分。
- `workspace/iterations/round-NNN/proposal.json`、`decision.json`：实际差异与采纳结论。
- `human-test/`：仅供人查看的 test 执行、评估和分数，不提供给调优方。
- `audit*.jsonl`、`result.json`、`resume-context.json`：运行审计、完成结果、恢复上下文。

评估的输入目录只读；只有 assessment 输出可写。评估 JSON 不合格时重跑评估，不重跑目标执行。
若配置了自定义评分器，评估说明不能更改其数值分数。调优方只能修改本轮获准的 package 资源。
原始 Agent 保持不变，只有显式应用版本才更新。
''')
