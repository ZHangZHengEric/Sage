# RSI 数据集与评分器

每个数据集放在独立目录，保存数据、评分器、环境工具代码、依赖与来源信息。它们分别导入和配置；RSI 核心不枚举特定数据集。

## 可直接接入的题库

| 数据集 | 默认导入文件 | 环境与评分 | 使用说明 |
| --- | --- | --- | --- |
| τ-bench / tau2 零售 | `tau_bench/rsi.dataset.json` | 官方零售工具 MCP + 官方 reward | [README](tau_bench/README.md) |
| BFCL V4 多轮 | `bfcl/rsi.dataset.json`（base 200 题）；`bfcl/rsi.all.dataset.json`（三个类别 600 题） | 官方模拟工具 MCP + 官方逐轮状态／执行结果判定 | [README](bfcl/README.md) |
| ToolSandbox 离线基础场景 | `toolsandbox/rsi.dataset.json` | 官方工具 MCP + milestone／minefield 相似度 | [README](toolsandbox/README.md) |

各目录都保留固定版本的官方源码、数据、许可证、来源哈希、依赖、MCP 示例和独立评分器。先安装对应目录的 `requirements.txt` 并运行 `preflight()`，再在页面分别导入数据和 `scorer.py`。MCP 连接名称必须与数据集声明一致，并显式设置 `SAGE_RSI_CASE_PROTOCOL=sage.rsi.case/v1`。

BFCL、ToolSandbox 的内部 split、通用用户驱动和支持范围均在各自 README 中声明；适配器运行通过不等于完整官方榜单复现。默认建议固定训练题池（每轮新增 0），避免自动生成没有官方评分参考的新题。

新增三套环境：

| 数据集 | 题数（train / validation / test） | 系统依赖 | 说明 |
| --- | --- | --- | --- |
| ALFWorld 文字版 | 120 / 24 / 24 | TextWorld、C/C++ 构建工具 | [数据、环境、评分器与 README](alfworld/README.md) |
| ScienceWorld（已核验子集） | 75 / 27 / 23 | Java 17、py4j | [数据、环境、评分器与 README](scienceworld/README.md) |
| AgentBench DB | 234 / 32 / 34 | Docker、MySQL 8.0 | [数据、环境、评分器与 README](agentbench_db/README.md) |

以上各目录都有 `rsi.dataset.json`、`scorer.py`、`mcp.example.json`、`policy.md`、依赖和固定来源。文字环境已做真实模拟器测试；DB 的真实 MySQL 测试需要 Docker，详情见其 README。

## 运行设置

- 初始训练题数：1–100，默认 6。
- 每轮新增训练题数：0–100，默认 6；0 表示固定训练集。
- System 指令字符上限：默认 64,000。
- 单个 `SKILL.md` 字符上限：默认 32,000。
- Skill 数量上限：默认 16，包含包内 Skill 及目标 Agent 声明的 Skill。
- 校验失败修正次数：0–10，默认 3，表示首次提案之后最多追加多少次修正。

导入数据中的训练题按原顺序组成题池。初始轮取初始批次，后续轮保留旧题并追加下一批；不足一批时先使用剩余题，再让出题 Agent 补足新增批次。数据集本身不足初始批次时，使用其中已有训练题。新增题不回测历史版本。

候选版本超出字符或数量上限时，调优 Agent 收到具体的实际值、上限、失败原因和修正要求，在当前轮的同一工作目录继续修改。通过校验后才封存、审查和推理。超出修正次数时保留失败记录与原有最佳版本，不执行不合格候选。

## 数据集格式

页面的“导入数据集”接受 `sage.rsi.dataset/v1` JSON：

```json
{
  "format_version": "sage.rsi.dataset/v1",
  "name": "Arithmetic",
  "cases": [
    {"id": "train-1", "input": "6*7?", "rubric": "Answer 42", "reference_answer": "42", "split": "training"},
    {"id": "dev-1", "input": "40+2?", "rubric": "Answer 42", "reference_answer": "42", "split": "validation"},
    {"id": "test-1", "input": "21*2?", "rubric": "Answer 42", "reference_answer": "42", "split": "test"}
  ]
}
```

题目 ID 全局唯一，必须包含 training 和 validation，test 可选。标准答案交给评分器和 eval，目标 Agent 看不到；dev 仅向调优 Agent 披露匿名分数；test 仅供人观察。

## Python 评分器

页面“评分器”默认选择 **Agent 评分**；“导入评分器”单独接受 `.py` 文件，与数据集互不绑定。

导出同步或异步函数 `score(request: dict) -> dict`。request 包含协议版本、goal、case、observation 和 conversation。case 提供 input、rubric、reference_answer 等；observation 提供执行状态、输出、工具证据等。

返回值可以是：

```python
{"grade": {"score": 0.8, "passed": True, "rationale": "Matched reference"}, "details": {}}
```

也可直接返回 grade 字典。score 必须为有限的 0–1 数值，passed 为布尔值，rationale 非空。运行错误不会伪装成零分。使用外部评分器后，eval 仍负责训练执行诊断，评分器决定数字分数。

选用自定义评分器后，数字分数及通过状态只取评分器结果；eval 继续分析执行原因和建议，不重新评分。评分器中的规则检查、模型调用、判分与重试由评分器代码自己实现，RSI 不提供代评模型通道。如果某题返回 `not_applicable_reason`，该次测量明确失败，不回退到内部评分；新增挑战题也必须提供评分器支持的参考信息。超时、异常和无效返回同样不能变成内部评分或零分。

### 评分器直接使用 ModelProvider

只导入一个 `.py` 代码文件；所用第三方依赖安装到 Desktop 的 Python 环境。评分器通过 `get_model_provider()` 取得可用的 Sage ModelProvider 代理，无需 API 配置文件、供应商密钥或自行初始化 SDK。在异步 `score(request)` 内使用标准模型接口：

```python
import json
from sagents.v2.optimization.scorer_runtime import get_model_provider
from sagents.v2.model.contracts import ModelRequest, ModelMessage, ModelEventKind
from sagents.v2.contracts.items import TextBlock

async def score(request):
    model = get_model_provider()
    prompt = build_your_scoring_prompt(request)  # 在本文件实现自己的评分规则
    async for event in model.stream(ModelRequest(
        request_id="score-request", run_id="scorer", model_binding=model.model_binding,
        messages=(ModelMessage(role="user", content=(TextBlock(text=prompt),)),),
    )):
        if event.kind == ModelEventKind.COMPLETED:
            return {"grade": json.loads(event.response.text)}  # 自行约定并验证响应格式
    raise RuntimeError("Model returned no completed response")
```

代理使用标准 `ModelRequest`、`ModelResponse` 和 `capabilities()`。跨进程传输由框架处理，底层复用实验所选的 Sage ModelProvider、协议适配及并发预算；不会创建 Agent、添加额外提示词或解释模型回答。当前代理聚合响应后返回 COMPLETED 事件，能力声明不承诺逐 token 流式返回。标准请求的消息、温度、结构化输出等参数保留，模型绑定和输出预算由宿主约束。

内部通信凭证每次评分独立签发并在结束后失效，供应商密钥留在后端；评分器代码无需处理它。调用次数、耗时和 token 用量保存在该实验的 `scorer-model-calls.jsonl`，不记录提示词和回答，也不合入调优证据。临时模型故障保留可重试标记，不伪装成数值分数。

如需兼容已有 SDK 评分器，低层 `get_model_api()` 仍提供本机 OpenAI 兼容端点；它也转发到同一个 Sage ModelProvider，而非直连供应商。导入自测不提供真实模型连接，评分器用离线样例验证协议与判分；真实模型连通性在运行时验证。

评分器可在同一个文件导出 `SCORER_CONTRACT`，用不超过 16,000 字符说明输入要求、成功条件、部分分、空断言及聚合规则。导入时验证它，并随源码哈希冻结；题库审查会读取该契约，避免把权威评分器的固定条件误判成规则缺失。契约只描述判分，不替代代码，也不能指挥审查忽略真正的无效数据或越权要求。

模型评分器的自测可为每个条目提供 `model_responses`，保存 1–16 个标准 `ModelResponse` 字典（含 `response_id`、`text`、`finish_reason`）。导入时 `get_model_provider()` 返回只消费这些记录的离线 Provider；多调、漏调或预期分数不符都会失败，不使用真实 API 或模型额度。真实运行不会加载这些离线响应。τ-bench 的自测同时覆盖数据库正反例及自然语言断言正反例。

文件必须附带 `SCORER_TEST_CASES`，包含 1–10 个自测条目，每项具有完整的 `request`、`expected_score`、`expected_passed`。示例见 `examples/exact_answer.py`。

不适用的自测条目使用 `expected_applicable: False`，不包含预期分数，且必须返回明确原因。至少保留一个实际数值评分自测，全部拒绝评分的模块不能通过导入验证。

导入检查 Python 语法、顶层 score 入口，在独立 Python 子进程加载模块、验证函数参数并执行全部自测，检查返回协议及预期分数。整体验证超时 10 秒；只有全部通过才保存为可选评分器。错误原因返回页面。

通过自测证明模块符合调用协议及提供的样例，不代表评分逻辑对任意任务都正确。真实运行逐次验证返回值，每次调用默认超时 120 秒。代码按内容哈希冻结并按用户/Agent 隔离保存到 Desktop runtime 的 `rsi-scorers/`；恢复实验时验证哈希。修改源码后需重新导入。

Python 文件使用 Desktop 后端解释器及已安装依赖。评分器按用户授权执行本地代码，独立进程不等于操作系统沙箱。

## τ-bench

`tau_bench/` 保存固定版本的官方 tau2 源码、零售数据、MIT 许可证、来源哈希、业务工具 stdio MCP Server、标准 `rsi.dataset.json` 和独立 Python 评分器。

`scorer.py` 从标准数据集的参考答案读取官方判定条件，从原生执行记录读取实际对话和工具调用，调用固定版本的官方评分逻辑重新计算奖励，不依赖预填 `tau_reward`。模型判定由评分器内部调用官方实现。详见 [τ-bench 说明](tau_bench/README.md)。


## 独立模拟用户

模拟用户与数据集、评分器分开选择。单轮用例跳过此模块；多轮用例通过用户背景和可见对话
生成下一条消息或停止决定。RSI 内置默认实现，也支持单独上传 Python 并使用当前
ModelProvider。tau 专用实现位于 [`tau_bench/user_simulator.py`](tau_bench/user_simulator.py)，
单独上传并选中即可，评分器仍选择 `tau_bench/scorer.py`。
标准输入输出、自测、依赖冻结和接入说明见
[模拟用户 README](../sagents/v2/optimization/USER_SIMULATORS.md)。
