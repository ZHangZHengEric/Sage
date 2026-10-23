# τ-bench / tau2 零售数据集

来源：Sierra Research `tau2-bench`，固定提交 `fc0055dc4e0a316c3f83133267fbd6faaa770992`。官方 Python 源码、零售数据库、政策、题目、split、共享用户模拟说明及 MIT 许可证保存在本目录。`upstream.json` 记录逐文件 SHA256；业务规则与评分逻辑未修改。

官方 split：train 74 题、test 40 题。RSI 的 dev 从官方 train 独立划出；官方 test 不进入调优。`vendor/` 是官方代码，`scorer.py`、`mcp_server.py` 与 `runtime.py` 是 Sage 接入代码。

## 依赖与预检

使用 Python 3.12 或 3.13，安装 Sage 和本目录 `requirements.txt`。业务 MCP 与评分器均需要固定官方源码的文字评测依赖。Voice 二进制资产和语音依赖不参与文字零售评测。

从 Sage 仓库根目录执行：

```sh
python -c 'from evaluation_datasets.tau_bench.runtime import preflight; print(preflight())'
```

预检验证固定文件、加载 16 个业务工具和 114 道任务，并读取官方用户模拟说明，不发起模型请求。正式实验启动前会执行该预检。

## 业务工具 MCP

Desktop 的 MCP 连接使用 `stdio`：

```sh
python -m evaluation_datasets.tau_bench.mcp_server --state /absolute/path/tau-retail.sqlite3
```

将连接环境中的 `PYTHONPATH` 设为 Sage 仓库绝对路径。连接名为 `TauRetail` 时，Agent 选择 `mcp_TauRetail_*` 工具。16 个业务函数均来自官方环境，`calculate` 也是官方工具；没有评分、测试题查询或管理员重置工具。数据库保存在给定 SQLite 文件内，跨短暂的 stdio 连接保留状态。

普通对话使用配置的 SQLite 文件。标准 RSI 数据集通过 `sage.rsi.case/v1` 为每个题目和候选版本建立独立状态目录；MCP 配置须显式设置 `SAGE_RSI_CASE_PROTOCOL=sage.rsi.case/v1`。MCP 从上下文文件加载任务初始状态，不能读取评分标准答案。

## 数据集与页面运行

页面“导入数据集”选择 `rsi.dataset.json`，格式为 `sage.rsi.dataset/v1`，包含问题、模拟用户上下文、参考答案和独立环境初始状态。固定 seed 20261021 将官方 train 划为 62 道训练题及 12 道 dev；40 道官方 test 保持独立。初始输入使用普通问候，完整场景指令只放入 `user_context`，由模拟用户逐步披露；标准字段 `dialogue_completion=user` 要求继续到模拟用户结束，不能因为中途数据库状态已匹配就提前终止。不能把 `reason_for_call` 中的对话安排直接发给目标。标准答案包括官方 `evaluation_criteria` 与 `initial_state`，不传给目标或模拟用户。

基线 Agent 预先配置官方政策与业务 MCP 工具。页面选择该 Agent、导入数据集及评分器后，使用通用 RSI 流程，无专用实验宿主。建议先用少量题目验证流程。该流程的模拟用户使用通用 RSI 实现，与官方编排器不同；评分逻辑对齐不等于已复现官方完整榜单设置。

## 独立 Python 评分器

页面“导入评分器”选择 `scorer.py`。它导出 `score(request)` 和 `SCORER_TEST_CASES`，四项自测验证官方数据库重放的正反例，以及使用离线 ModelProvider 响应的官方自然语言断言正反例，导入不调用付费模型。

评分器读取原生 `final_items` 中的对话、工具参数及结果，将业务工具名称映射回官方函数，调用固定版本的官方 `evaluate_simulation` 重新计算奖励。不读取预填的 `tau_reward`，不调用评分 MCP，也不请求 RSI 内部模型代评。

官方按任务的 `reward_basis` 合成结果：数据库检查比较实际工具重放与标准动作执行后的状态；自然语言断言使用官方模型判定提示词和解析规则。动作与沟通检查是否计入总分取决于任务声明，不能因一个参考动作未匹配就擅自改分。

评分器通过 `from sagents.v2.optimization.scorer_runtime import get_model_provider` 直接获得可用的 ModelProvider 代理，使用 Sage 标准消息和请求类型。无需 API 参数、手工 `config` 或初始化 SDK；页面仍只导入 `scorer.py`。框架复用所选模型的 Sage ModelProvider、协议适配与并发预算，不提供判分提示词、判分函数或 eval 代评。官方判分代码只适配模型调用部分，提示词、断言解析、数据库重放、reward_basis 与奖励合成保留固定版本官方实现。

底层协议由 Sage ModelProvider 处理。真实 GPT-6.1 Sol 的官方自然语言断言正反样例已经分别得到 1 和 0。官方默认模型是 `gpt-4.1-2025-04-14`，本实验按要求改用 GPT-6.1 Sol，报告必须披露此差异。若 Responses 网关明确拒绝官方温度参数，评分器只对该明确错误移除温度并重试，在 `details.model_calls[].transport_adjustments` 记录，不改官方断言、提示词、解析或奖励规则。其他错误不转换为成功或内部评分。

eval 仍对成功、失败和重复执行不稳定的轨迹做诊断、整理原因与建议；其输出不改变分数或通过状态。train 诊断交给调优，dev 仅匿名分数，test 证据仅供人查看。

当前自动化覆盖协议调用、真实 stdio 状态隔离、真实官方数据库评分及自然语言判分逻辑；另已用 GPT-6.1 Sol 验证评分器直接调用真实模型 API。尚不能把这些测试视为真实模型的完整页面运行或效果提升证明。
