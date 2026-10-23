# ToolSandbox 离线场景数据集（Sage RSI）

本目录提供与 `tau_bench/` 一致的标准导入方式：数据集 JSON、Python 评分器、stdio MCP、依赖和离线测试。官方场景由 Python 定义，源码本身就是题库；导出的 `rsi.dataset.json` 可直接在 Desktop 进化页导入。

## 来源与范围

- 官方来源：<https://github.com/apple-aiml-research/ToolSandbox>。
- 固定提交：`c8571d7854316d2e1c5f288e59fe1e34e53f6dd1`。
- `vendor/` 保存未修改的官方源码、场景、里程碑／雷区评分逻辑、README、依赖定义、`LICENSE` 和 `ACKNOWLEDGEMENTS`。保留 Apple 原许可证，不能将 vendor 内容视为 Sage 的 MIT 代码。
- `upstream.json` 记录所有官方文件的 SHA256，运行前检查。
- 导出范围为**不含 RapidAPI 搜索工具的基础场景**，覆盖单工具、多工具、多轮用户交互和信息不足；不包含工具扰动／干扰工具变体，也不需要 RapidAPI 凭证。
- 当前 `rsi.dataset.json` 共 95 题：training 79 / validation 10 / test 6；按家族划分，题数不要求等比例。
- 使用 seed `20261023`，按任务家族划分 training / validation / test。相同任务的设备状态、多轮、alt、implicit、信息不足等相关变体放在同一 split。这是内部 RSI 实验划分，不是官方榜单划分。

## 1. 安装与预检

推荐 Python 3.12。上游包含旧版模型 SDK 的完整锁定依赖，不应直接装入 Sage；本目录的 `requirements.txt` 是实际工具／场景／评分所需依赖。

在仓库根目录：

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -e '.[desktop,test]' -r evaluation_datasets/toolsandbox/requirements.txt
.venv/bin/python -m pip check
.venv/bin/python -c 'from evaluation_datasets.toolsandbox.runtime import preflight; print(preflight())'
```

已有 `.venv` 时省略创建步骤。源码 Desktop 使用仓库根目录 `.venv/bin/python`；评分器和 MCP 都需要这些依赖。

依赖适配保留官方源码不变：NumPy 1.26.4 与 SciPy 1.13.1 匹配旧版 Pint／Polars；`ccy` 使用兼容 Python 3.12 的 1.5.0，`langchain-core` 使用可与 Sage 的 tenacity 9 共存且仍提供上游兼容 API 的版本。无需安装上游 Anthropic、Vertex、Transformers 模型客户端。建议在专门用于本项目的虚拟环境中使用，不与其他项目共用依赖。

预检不调用模型或外部搜索，打印可用题数、工具数、固定提交和冻结时间。它不自动更改 Desktop 配置，也不启动付费模型实验。

## 2. 配置 MCP 和基线 Agent

`mcp.example.json` 提供可复制示例；替换全部绝对路径：

```json
{
  "mcpServers": {
    "ToolSandbox": {
      "command": "/absolute/path/Sage/.venv/bin/python",
      "args": ["-m", "evaluation_datasets.toolsandbox.mcp_server", "--state", "/absolute/path/sage/runtime/toolsandbox.sqlite3"],
      "env": {
        "PYTHONPATH": "/absolute/path/Sage",
        "SAGE_RSI_CASE_PROTOCOL": "sage.rsi.case/v1"
      }
    }
  }
}
```

在 Desktop MCP 页面选择 stdio：名称 `ToolSandbox`，命令填写 Python 路径，参数填写 `args` 数组，环境变量填写 `env` 对象。连接后发现 `mcp_ToolSandbox_*` 工具。发现阶段展示工具全集；运行阶段只展示当前场景允许的 Agent 工具。

基线 system 使用 `policy.md`，内容取自官方场景的 Agent 指令。启用 ToolSandbox MCP 工具，不额外启用 Shell、文件读取或外部搜索。用户结束对话、重置、评分、数据库管理均不作为目标工具。

每题和每个候选使用 RSI 提供的独立状态目录。SQLite 事务保存 JSON 世界状态及历史快照；stdio 重连会恢复同一题状态，不共享其他题的数据。不加载来自执行记录的 pickle／dill 控制台对象。

## 3. 导入并运行

1. 进化页导入 `rsi.dataset.json`。
2. 单独导入并选择 `scorer.py`，等待自测通过。
3. 首次建议：初始训练 6、每轮新增 0、优化 1 轮、并发 2、重复 1。
4. 确认工具调用、评分、状态隔离正常后，再增加题量与轮数。

导入文件的 split 决定实际 dev/test 数量。需要缩小流程检查集时另存文件，保留独立的 training、validation 和 test；test 不用于优化或选择版本。

评分器只接受已导出的官方离线场景。建议先固定题池；增加训练题时不要用完池后继续生成没有官方里程碑的新题。新增题不能靠 Agent 自评冒充官方分数。

## 评分与复现边界

评分器不读取预填 `similarity`、外部轨迹路径或 Agent 自报结果。它从标准原生 `final_items` 重放实际工具调用及用户／助手消息，使用官方执行角色和 `Evaluation.evaluate()`，重建数据库历史并按官方 milestone DAG、minefield 判分。分数保留 0–1 的相似度；Sage 的 `passed` 约定为相似度等于 1，这个通过阈值不应与其他基准的成功率混淆。

场景构造、工具执行和评分统一冻结在 `2024-05-17 12:00:00 UTC`，避免日期、提醒、消息时间随运行日期漂移。官方源码和里程碑未修改；冻结时间属于本实验环境设置。

时钟适配只作用于 ToolSandbox 模块，不替换 Sage、SDK 或进程全局的 datetime。重放还会核对原生工具成功／失败状态，不能把被拒绝的调用重放成成功写入；不一致作为无效测量报告。

用户由 Sage 通用用户驱动根据官方用户指令继续对话；官方 `end_conversation` 语义适配为用户驱动结束信号。Sage 的轮数与工具调度预算也不同于上游。因此这些成绩应命名为 **ToolSandbox offline base / Sage RSI**，不能宣称复现完整 1032 场景的官方榜单。工具调用的分组按原生记录重建；MCP 实际调度与上游并行排列检查可能不同，完整协议一致性不在此适配范围内。

## 再生成与离线验证

```sh
.venv/bin/python -m evaluation_datasets.toolsandbox.export_dataset
.venv/bin/python -m pytest -q tests/sagents/v2/test_toolsandbox_rsi_dataset.py tests/sagents/v2/test_agent_dataset_mcp_isolation.py
```

测试覆盖题库再生成、家族分离、官方状态和里程碑正确／失败判分、虚假成功声明、JSON 状态恢复、评分器独立进程和真实 stdio。测试不调用模型；通过不代表已证实 RSI 涨分。换电脑需重建依赖和 MCP 绝对路径，仓库不包含网关凭证和历史实验。
