---
layout: default
title: 首次运行 RSI
parent: 应用入口
nav_order: 5
lang: zh
ref: v2-applications-FIRST_RSI_RUN
---

{% include lang_switcher.html %}

# 查看你的首次 RSI 运行

RSI 是 Recursive Self-Improvement（递归自我改进）的缩写。本教程展示 Sage 如何比较 Agent package 候选、拒绝较差的提案，并返回选定版本而不激活它。这里使用仓库现有的 Python 示例，不涉及 Desktop 应用。

**模型响应和评分均由脚本预设。** 工作流通过真实的 SAgents 运行时执行，但该示例不展示模型学会单位换算，也不衡量真实模型的改进。运行这个脚本示例不需要模型 API 密钥。

## 1. 准备 Python 环境

你需要 Git、**Python 3.12 或更新版本**，以及仓库的 Python 依赖。只完成[快速开始](GETTING_STARTED.md)中的“安装”部分，然后返回本页。无需设置该指南中的 API 密钥，也无需运行 `quickstart.py` 示例。

安装过程会下载依赖，可能需要一些时间。这不是免安装演示。这个 Python 示例不需要 Flutter、Desktop 安装包、MySQL 或模型服务账户。

如果已有配置好的源码目录，请在仓库根目录打开终端，并使用该目录对应的 Python 环境。

## 2. 运行现有示例

在仓库根目录，macOS/Linux 使用：

```bash
.venv/bin/python -m examples.v2.package_optimizer
```

Windows 用户按照快速开始创建环境后，运行：

```powershell
.venv\Scripts\python.exe -m examples.v2.package_optimizer
```

[示例源码](https://github.com/ZHangZHengEric/Sage/blob/main/examples/v2/package_optimizer.py)为目标 Agent、调优 Agent 和评测 Agent 提供 `ScriptedModelProvider`。这些 Agent 没有启用工具。示例写入临时 Session 数据，并在程序正常退出时移除临时目录；它打印 JSON 摘要，不保存永久报告，也不激活 Agent。

## 3. 阅读比较结果

脚本预先定义了以下响应和评分。下表解释源码中定义的指导文本变化；命令输出的是选择摘要，不是 package 差异：

| 阶段 | 预设指导文本 | 预设评分 | 应观察到的选择 |
| --- | --- | --- | --- |
| 基线 | 无新增指导文本 | 0.4 | 起点 |
| 第 1 轮 | Verify units | 0.6 | 接受 |
| 第 2 轮 | Be brief | 0.5 | 拒绝 |
| 第 3 轮 | Verify units and arithmetic | 0.8 | 接受 |

关键在第 2 轮：新提案不会自动替换保留的最佳候选。它的预设评分低于第 1 轮，因此比较过程应拒绝它，保留更好的版本。


### 当前输出合同

修正后的示例应输出 `baseline_score: 0.4`、`selected_score: 0.8`、`goal_verified: false`，三轮接受结果为 `true`、`false`、`true`。第二轮原因为 `Insufficient validation improvement`。保留改进候选不等于已收敛：默认目标为 0.95 且要求稳定通过，本次脚本演示未达到该目标。

示例从每次调优请求读取保留版本的哈希及已测训练证据来声明实验；修复重试复用同轮提案与训练证据，不关闭生产实验校验。

### 历史输出（不是当前字段合同）

以下保留的输出来自 2026-10-12 版本，不是当前命令输出：

```json
{
  "baseline_score": 0.4,
  "selected_score": 0.8,
  "final_passed": true,
  "rounds": [
    {
      "round": 1,
      "accepted": true,
      "reason": "Non-saturated splits improved; no case regressions"
    },
    {
      "round": 2,
      "accepted": false,
      "reason": "Regression on case: km"
    },
    {
      "round": 3,
      "accepted": true,
      "reason": "Non-saturated splits improved; no case regressions"
    }
  ]
}
```

在你得到的 JSON 输出中，检查：

- `baseline_score` 和 `selected_score`：脚本预设的验证评分，预期分别为 `0.4` 和 `0.8`。
- `rounds`：三个条目的 `accepted` 预期依次为 `true`、`false`、`true`；同时阅读每项的 `reason`。
- `original_hash` 和 `candidate_hash`：原始 package 与选定 package 的标识。由于候选的指导文本发生变化，两者应不同。
- `goal_verified`：预期为 `false`。候选有改进，但尚未达到收敛目标；`final_passed` 仅存在于上面的历史样本。两者均不代表真实模型效果。

单位换算问题只是工作流的测试样例；脚本目标返回的是指导文本标签，而非计算得到的换算答案。测试集审查和语义审查的批准结果也由脚本预设。

**当你能够找到被拒绝的一轮，并识别选定候选时，就完成了本教程。** 你的日常 Agent 配置没有被应用任何修改。

### 历史验证范围

这段输出于 2026-10-12 采集，使用 Linux 上的 Python 3.12.14，源码来自[提交 `296cc3d`](https://github.com/ZHangZHengEric/Sage/blob/296cc3dec8f7ea11fa58a079df9b18709305fa89/examples/sagents_v2_package_optimizer.py)。未经修改的示例在已准备好的 Python 环境中成功退出，环境没有 API 凭据。Python 层测试防护没有报告网络或子进程操作尝试。该检查覆盖示例本身，不覆盖全新完整安装、Windows/macOS 执行或真实模型质量。

### 当前示例修正的验证

2026-11-19，在基于 `1d3d1dd65857a4903ceaedf3ccaea81f1c3666f9` 的独立 macOS 快照中，使用 Python 3.12.13 与已有依赖测试修正后的示例。文档模块命令在无 API 凭据、阻止网络和子进程的防护下退出 0，产生上述当前输出。这是基于该提交的 fixture 修正验证，不表示未经修正的基线可以运行，也不覆盖全新安装或 Windows。离线回归测试还覆盖一次同轮强制修复重试。

## 无法运行时

- Python 版本错误：确认虚拟环境使用 Python 3.12 或更新版本创建。
- `No module named examples...`：请在包含 `examples/` 的仓库根目录运行。
- 导入或依赖缺失错误：安装和运行应使用同一个虚拟环境；重新查看[快速开始](GETTING_STARTED.md)中的“安装”部分。

寻求帮助时，请保留准确的错误信息和源码版本。不要通过添加 API 密钥来排查这个脚本示例。

## 下一步：使用自己的 Agent 和评测

如需使用真实模型，请阅读 [RSI 工作流指南](RSI.md)和[优化器 API 参考](https://github.com/ZHangZHengEric/Sage/blob/main/sagents/v2/optimization/README.md)。这些文档介绍宿主绑定、授权的可编辑范围、测试集、候选证据和失败处理。真实模型运行可能产生服务费用；本演示的预设评分不能作为它们的基准。

## 可选：提交你的第一个 Sage PR

如果你想在没有模型 API 密钥的情况下参与贡献，完善文档或补充离线测试都是非常有价值的贡献。你可以先浏览[开放的 good first issues](https://github.com/ZHangZHengEric/Sage/issues?q=is%3Aissue+is%3Aopen+label%3A%22good+first+issue%22)，并在动手前阅读[贡献指南](https://github.com/ZHangZHengEric/Sage/blob/main/CONTRIBUTING.md)。

认领 issue 前，请先查看该 issue 下的评论和关联的 Pull Request——未指派负责人的 issue 也可能已经有活跃的 PR 在推进。如果你希望尽早获得反馈，欢迎在 issue 中留言或提交草稿 PR（draft PR）。
