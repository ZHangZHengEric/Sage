# BFCL V4 多轮数据集（Sage RSI）

本目录与 `tau_bench/` 使用同一套标准 RSI 导入方式：题库 JSON + 独立 Python 评分器 + 按题隔离的 stdio MCP。数据和运行源码均已入库，换电脑不依赖原机器 `/tmp` 或另行克隆上游。

## 来源与范围

- 官方来源：<https://github.com/ShishirPatil/gorilla/tree/main/berkeley-function-call-leaderboard>。
- 固定提交：`6ea57973c7a6097fd7c5915698c54c17c5b1b6c8`。
- `vendor/` 保存官方多轮数据、参考调用、函数说明、模拟环境和评分代码；未修改上游文件。`upstream.json` 记录 SHA256；`vendor/LICENSE` 为上游 Apache-2.0 许可证。
- 默认 `rsi.dataset.json`：`multi_turn_base` 共 200 题，training 160 / validation 20 / test 20。
- `rsi.all.dataset.json`：base、miss_param、long_context 共 600 题，training 480 / validation 60 / test 60。
- seed `20261023` 按任务编号划分。同一编号在三个类别中的变体必须属于同一 split；这是 Sage 的内部实验划分，不是官方 train/dev/test。
- 官方 miss_func 原始数据也保留在 vendor 中，**暂不导出为可运行 RSI 题库**。该类别需要按轮动态注入缺失函数；当前适配器没有实现这项官方编排语义。

## 1. 安装与离线预检

在仓库根目录，使用 Python 3.12。已有 Sage `.venv` 时直接安装该数据集依赖；新电脑先建立环境：

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -e '.[desktop,test]' -r evaluation_datasets/bfcl/requirements.txt
.venv/bin/python -m pip check
.venv/bin/python -c 'from evaluation_datasets.bfcl.runtime import preflight; print(preflight())'
```

预检验证官方文件哈希，加载 600 题、工具定义和各类模拟后端，不调用模型。不要执行 `pip install vendor/`，上游完整的模型供应商 SDK 不属于本适配器所需依赖。

源码版 Desktop 后端使用仓库根目录 `.venv/bin/python`；评分器依赖必须安装在这个解释器中。独立 MCP 解释器不能替代评分器所在环境的依赖。

## 2. 配置 MCP 和基线 Agent

`mcp.example.json` 提供完整示例。将 `/absolute/path/Sage` 替换为实际仓库路径，将普通状态文件路径替换为本机运行目录：

```json
{
  "mcpServers": {
    "BFCL": {
      "command": "/absolute/path/Sage/.venv/bin/python",
      "args": ["-m", "evaluation_datasets.bfcl.mcp_server", "--state", "/absolute/path/sage/runtime/bfcl.sqlite3"],
      "env": {
        "PYTHONPATH": "/absolute/path/Sage",
        "SAGE_RSI_CASE_PROTOCOL": "sage.rsi.case/v1"
      }
    }
  }
}
```

在 Desktop 的 MCP 页面选择 stdio：名称必须是 `BFCL`，命令填写 Python 路径，参数填写 `args` 数组，环境变量填写 `env` 对象。连接后会发现 `mcp_BFCL_*` 工具。未激活 RSI 题目时只支持发现工具，直接执行会明确报错。

新建基线 Agent，system 可使用 `policy.md`，启用该 MCP 工具集合。每道题运行时只暴露该题可用的官方函数；参数 schema 中的 `dict` / `float` 被转换成 MCP 的 `object` / `number`，不改变工具行为。无需额外启用文件、Shell 或联网工具。

MCP 仅暴露业务工具，不提供答案、评分、重置和题库查询。每题、候选版本、重复试验由 RSI 分配独立 `state_directory`；SQLite 保存实际调用日志，重连时在官方模拟后端重放，保持状态。这里的文件系统、交易和旅行操作都是官方本地模拟。

## 3. 导入并运行

1. 在 Agent 进化页导入 `rsi.dataset.json`；需要扩展类别时改用 `rsi.all.dataset.json`。
2. 单独导入 `scorer.py`，等待正反例自测通过后选中它。
3. 建议首次设置：初始训练 6 题、每轮新增 0、优化 1 轮、并发 2、重复 1 次。验证后再增加训练题量与轮数。
4. 保持测试集独立，不把 test 题目、轨迹或评分反馈给调优 Agent。

每轮新增设为 0 可固定题池；增量运行时不要超过剩余官方训练题量。当前评分器只接受已支持的官方 task ID，自由生成的新题没有对应官方参考，不会被静默代评分。

默认 dev/test 题数由导入文件的 split 决定。若需要更小的流程检查题库，另存一个文件并同时保留 training / validation / test，不能用少量题的结果冒充完整 test 成绩。

## 评分与复现边界

`scorer.py` 从 canonical `final_items` 读取实际工具调用，按原生对话轮次重放，调用固定版本的官方 `multi_turn_checker` 和 `multi_turn_irrelevance_checker`。判分检查每轮状态和累计工具执行结果，分数为 0 或 1，不使用预填分数，也不让模型自行判断成功。

重放会核对原生工具结果的成功／失败状态。被权限或传输层拒绝的调用不能在重放时变成成功操作；不一致会使测量明确失败。

BFCL 用户消息是固定脚本。导出的 `user_context` 要求 Sage 通用用户驱动逐条原文发送；评分器会检查实际轮数与消息。脚本漂移返回 `not_applicable_reason`，作为无效测量处理，不能记为目标 Agent 零分。当前未修改 RSI 核心增加专用确定性用户驱动，因此这不是官方完整编排器的复现，也不能直接报告为 BFCL V4 总榜分数。

参考调用和初始状态从固定官方文件读取，仅 task ID 放入标准参考。它们不能提供给目标 Agent 或用户模拟器；基线只启用业务 MCP，避免授予目标读取题库文件的额外权限。

## 再生成与验证

```sh
.venv/bin/python -m evaluation_datasets.bfcl.export_dataset
.venv/bin/python -m evaluation_datasets.bfcl.export_dataset --categories base miss_param long_context --output evaluation_datasets/bfcl/rsi.all.dataset.json
.venv/bin/python -m pytest -q tests/sagents/v2/test_bfcl_rsi_dataset.py tests/sagents/v2/test_agent_dataset_mcp_isolation.py
```

测试覆盖可再生成的题库、类别变体隔离、官方正确／失败判分、脚本漂移、缺失工具结果、独立评分器进程，以及真实 stdio 的状态持久化和候选隔离。离线测试通过不等于已经完成真实模型 RSI 效果实验。更换机器需重建模型配置、Python 依赖及绝对路径；只复制 `scorer.py` 到没有安装本仓库的环境不够。
