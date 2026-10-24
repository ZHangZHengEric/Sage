# ALFWorld 文字版 · Sage RSI

数据集、官方文字环境源码、独立评分器及 MCP 均在本目录，普通运行不下载模型、轨迹包或 THOR 视觉环境。

## 来源、数据与评分

- [官方仓库](https://github.com/alfworld/alfworld)，固定提交 `aaba6870f86c5be6a08a491f32a50b906227bc3e`；原样源码在 `vendor/`，许可证见 `vendor/LICENSE`，来源与 SHA256 在 `upstream.json`。
- 官方 release `0.4.2` 的 `json_2.1.3_tw-pddl.zip` 包含完整、自包含的 TextWorld PDDL 游戏。下载来源及 ZIP SHA256 见 `resources.json`。已将所选 168 个原始游戏原样入库，无需再次下载。
- `data/tasks.json` 固定选择清单：6 类任务各 20 train + 4 valid_seen + 4 valid_unseen，共 **120 training / 24 validation / 24 test**。先按固定 seed `20261023` 抽取，清单固定后以清单为准；同一问题只取一个 trial，只收录 solvable、非 movable、非 sliced 任务。
- validation 来自官方 seen，test 来自官方 unseen；这是方便 RSI 的小子集，不是官方完整 seen/unseen 结果。`rsi.dataset.json` 可直接导入。
- 环境用 TextWorld 1.7.0 加官方 `AlfredDemangler`，对象名称不随机打乱；无专家提示。`observe` 返回观察与可用动作，`step(action)` 执行动作，最多 200 次。
- 评分重放官方 PDDL 环境，以 **`state['won']`** 判定，分数 0/1；模型口头说完成没有分数。官方 `walkthrough` 保留在游戏原件中，只供评测端自测，不进入题目上下文或工具结果。

## 安装与真实环境预检

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -e '.[desktop,test]' -r evaluation_datasets/alfworld/requirements.txt
.venv/bin/python -m pip check
.venv/bin/python -m evaluation_datasets.alfworld.runtime
```

TextWorld/fast-downward 包含 C/C++ 构建组件，首次安装需要编译工具（macOS Command Line Tools，Linux 对应编译工具链）。不需要 GPU、Java、Docker、AI2-THOR 或联网服务。不要安装 vendor 上游的完整训练依赖。预检会验证源文件/游戏哈希并实际 reset 一道官方任务，不调用模型。

MCP 名称：**`ALFWorld`**，入口：`evaluation_datasets.alfworld.mcp_server`。

## 在 Desktop 中使用

1. 在仓库根目录建 Python 3.12 虚拟环境，安装 Sage 和本目录依赖（命令见上文）。已有 `.venv` 时只需补装依赖。源码版 Desktop 后端使用 `.venv/bin/python`，评分器依赖必须也装在这里。
2. 按 `mcp.example.json` 添加 stdio MCP。替换所有 `/absolute/path/Sage`、状态文件绝对路径；连接名称必须使用本文指定名称，设置 `SAGE_RSI_CASE_PROTOCOL=sage.rsi.case/v1`。目标 Agent 的 system 可使用 `policy.md`，只启用这套 MCP。
3. 在 RSI 页导入 `rsi.dataset.json`，再单独导入 `scorer.py`，等待正反例自测通过并选中评分器。
4. 首次建议初始训练 6 题、每轮新增 0、优化 1 轮、并发 1、重复 1 次。为目标 Agent 留足工具调用与运行时间预算；正式实验再增加题数。固定题池可避免自动出题产生没有官方环境的新任务。

题目 ID 只在 `environment_context` 中绑定官方世界。每道题、候选版本和重复试验使用 RSI 分配的独立状态目录。SQLite 保存调用日志，stdio 重连后从官方初态重放，因此连接结束不会丢失状态。普通状态路径只用于命令格式兼容；激活 RSI case 时实际状态由其独立目录接管。未激活 case 只能发现工具，不能执行任务。

评分器从 canonical `final_items` 提取实际完成的工具调用，在全新环境重放并核对原生工具结果。权限拒绝、环境依赖缺失和结果不一致会明确报测量错误，不伪装为 Agent 零分。MCP 不提供评分、参考答案、重置或数据集查询工具。避免给目标 Agent 额外的文件读取/Shell 权限，否则它可以读取仓库中的隐藏参考；这些文件只供可信评测端使用。

RSI 可优化提示词及 Skill。框架内置 `load_skill` 仅加载当前启用的指导，成功且绑定到原生
执行回执、内容哈希与 Skill 名称的调用可作为辅助读取；不计入环境动作，不提供奖励。
拒绝、伪造或缺少原生回执的加载，以及其他非环境工具，仍是无效测量。
评分器 v2 加入这一兼容性；旧实验的评分器与依赖绑定保持冻结，应新建关联实验后重新评分。

这是 Sage 的固定 RSI 实验范围，不等于完整官方榜单复现，也不包含已完成的模型优化效果实验。导入后 train 用于优化，validation 用于候选选择，test 应保持独立。新增自然语言题目不能凭空获得官方环境或参考，当前评分器只接受已收录的 task ID。

## 再生成与验证

```sh
.venv/bin/python -m evaluation_datasets.alfworld.export_dataset
.venv/bin/python -m pytest -q tests/sagents/v2/test_world_rsi_datasets.py -k 'alfworld or exports'
```

`prepare_data.py --archive /path/json_2.1.3_tw-pddl.zip` 可按固定清单恢复全部游戏，会先核验 ZIP 和每个游戏 SHA256。无需下载即可重新导出 RSI JSON。评分器正例来自真实环境运行的官方 walkthrough，另含未行动的零分反例；测试还检查拒绝调用、篡改观察、独立评分器进程和真实 stdio 状态隔离。

重放实现优先保证短连接正确性，每次 MCP 调用会从初态重放已有动作，较长轨迹会增加耗时，建议先用并发 1 跑小规模实验。

## 机制实验与长任务预算

ALFWorld 使用普通 RSI 的机制实验协议：eval 指定下一步验证，tuner 为有改动的候选提交
一个主要机制及事前证伪条件；新增官方训练题先测保留版本，再决定是否编辑。无需把
ALFWorld 的对象、动作或通关路径写入框架。禁止把官方 walkthrough 转成目标提示词。

真实环境准备可以使用独立虚拟环境，避免修改其他运行使用的环境。MCP command 必须
指向安装了本目录依赖的 Python；独立 Python 评分器也必须由同一依赖齐备的宿主运行。
完整子集为 120 train / 24 dev / 24 test。按初始训练题数逐步取用官方池时，报告应明确
已测训练数量；不能把只测部分训练的结果描述为全题测量。

多动作任务可在 RSI start API 设置 `call_timeout_seconds`（默认 240 秒），训练和人看的
test 同步使用。Model Provider 的逐次请求时限、Agent 步数预算及官方 200 动作预算仍
分别生效。判断通关始终使用官方环境 `won`，不能将过程跑通等同于分数提高。

### Official environment termination

The exported environment binding sets `terminal_on_done: true`. A successful,
nontruncated result from this case's MCP server with the JSON boolean `done=true`
ends the native target run before another model request. An assistant's text or
user-supplied JSON cannot trigger this boundary. Termination does not imply
success: the scorer still reconstructs the official environment and checks `won`.

Concurrent MCP calls carry a per-case effect sequence committed with the state
in the same SQLite transaction. Native receipt projection uses this sequence
when present, so response-delivery latency cannot reverse environment actions.
The official scorer still validates every returned snapshot; sequence metadata
alone never establishes success.

If the model already dispatched sibling actions in the same tool batch, the
terminal world is absorbing: those calls receive the unchanged terminal snapshot
and do not advance TextWorld. The 200-action request limit remains enforced.
Both model calls and the environment boundary remain visible in native evidence.
Reaching the 200th environment action also reports `done=true`; an unsolved task
then receives official `won=false` (score 0), rather than an invalid 201st action.
The scorer verifies every absorbed sibling result against the same terminal
snapshot, without counting it as another environment action. Direct environment
replay requests still have a strict 200-action limit; a forged terminal snapshot
or changed sibling outcome fails measurement validation.

`native-v3` 还支持单轮执行被原生循环保护停止的情况：只有完整、成功且绑定到
原生调用的工具收据才能封闭评测 episode。Run 仍保留 `suspended`，官方环境
重放动作后计算 `won`；封闭本身不会赋分，也不会向 Agent 追加提示或重跑。
详情见 [RSI 执行边界](../../sagents/v2/optimization/NATIVE_EPISODES.md)。
