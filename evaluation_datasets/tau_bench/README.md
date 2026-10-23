# τ-bench / tau2 零售数据集

来源：Sierra Research `tau2-bench`，固定提交 `fc0055dc4e0a316c3f83133267fbd6faaa770992`。官方 Python 源码、零售数据库、政策、题目、split、共享用户模拟说明及 MIT 许可证保存在本目录。`upstream.json` 记录逐文件 SHA256；业务规则与评分逻辑未修改。

官方 split：train 74 题、test 40 题。RSI 的 dev 从官方 train 独立划出；官方 test 不进入调优。`vendor/` 是官方代码，`scorer.py`、`mcp_server.py` 与 `runtime.py` 是 Sage 接入代码。

## 换电脑后从零运行（macOS Desktop）

本目录包含运行所需的官方源码和数据，不依赖原机器的 `/tmp` 文件或单独下载的 tau2 仓库。需要 Python 3.12/3.13、Flutter 和 Xcode 的 macOS 构建环境，以及能够调用 GPT-6.1 Sol 的模型网关。仓库不包含模型凭证、已配置的 Desktop Agent 或历史实验数据库。

### 1. 安装并预检

在新电脑克隆仓库，进入仓库根目录；已有 checkout 则先同步最新 `main`。推荐单独的虚拟环境，避免其他项目的 pandas、MCP 等依赖冲突：

```sh
git clone git@github.com:ZHangZHengEric/Sage.git
cd Sage
python3.13 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e '.[desktop,tau-bench,test]' -r evaluation_datasets/tau_bench/requirements.txt
.venv/bin/python -m pip check
.venv/bin/python -c 'from evaluation_datasets.tau_bench.runtime import preflight; print(preflight())'
```

也可将 `python3.13` 换成 `python3.12`。预检应报告 16 个业务工具、114 道任务，官方 train 74 / test 40。依赖中的 MCP 版本与 Sage 主项目统一为 1.28.1。依赖包含 `httpx[socks]`，支持系统环境里的 SOCKS 代理。不要在这个环境中另外安装上游完整 voice/streamlit 开发环境。

离线验收（无需模型密钥，但 stdio / 评分器测试需要本地进程和 loopback 端口）：

```sh
.venv/bin/python -m pytest -q tests/sagents/v2/test_tau_repository_runtime.py tests/sagents/v2/test_tau_standard_dataset.py tests/sagents/v2/test_tau_mcp_isolation.py tests/sagents/v2/test_tau_standard_scorer.py
```

### 2. 启动 Desktop，配置模型和业务 MCP

```sh
cd app/v2/desktop
flutter pub get
flutter run -d macos
```

源码版 Desktop 优先使用仓库根目录的 `.venv/bin/python`。在“模型”中配置自己的网关地址、凭证、协议和模型标识 `gpt-6.1-sol`，先验证普通对话可用；凭证在新电脑本地配置，不放进仓库。

在“MCP”中添加 stdio 连接 `TauRetail`，按下面字段填写。所有 `/absolute/path` 都必须替换为**新电脑**的实际绝对路径；参数中的 `~` 不依赖 shell 展开。

```json
{
  "mcpServers": {
    "TauRetail": {
      "command": "/absolute/path/Sage/.venv/bin/python",
      "args": ["-m", "evaluation_datasets.tau_bench.mcp_server", "--state", "/absolute/path/sage/runtime/tau-retail.sqlite3"],
      "env": {
        "PYTHONPATH": "/absolute/path/Sage",
        "SAGE_RSI_CASE_PROTOCOL": "sage.rsi.case/v1"
      }
    }
  }
}
```

Desktop 弹窗中选择 `stdio`：名称填 `TauRetail`，命令只填 Python 解释器的绝对路径；“参数（JSON）”粘贴上述 `args` 数组，“环境变量（JSON）”粘贴上述 `env` 对象。参数、环境变量留空分别表示 `[]`、`{}`。不要将整条 shell 命令填进“命令”字段，也不要把整个 `mcpServers` 对象粘贴进参数框。点击“连接”后，Desktop 自动启动 stdio 子进程，无需手动常驻启动服务器。 已保存的外部 MCP 可选中后点击右上角“编辑”，修改命令、参数或环境变量并保存；连接名称保持不变，保存后重新发现工具，原启停状态保留。

连接并刷新工具列表，确认出现 16 个 `mcp_TauRetail_*` 业务工具。此连接只提供业务环境；评分器另外导入，不需要 `scorer_mcp` 或 `evaluate_simulation` MCP 工具。

### 3. 先配置列表里的基线 Agent

新建一个用于零售实验的 Agent，主模型选择刚配置的 GPT-6.1 Sol；若配置快速模型，也选择同一模型。system 填入简短角色说明及本目录 `data/tau2/domains/retail/policy.md` 的**完整原文**。在工具选择中启用上述 16 个业务工具，保存后再进入进化页。官方 `calculate` 应保留；没有网络搜索工具要求。

若要复现实验中允许本地辅助能力的基线，同时显式启用 Sage 的 `file_read`、`grep`、`glob`、`list_dir`、`file_write`、`file_update`、`apply_patch`、`execute_shell_command`、`await_shell`、`kill_shell`、`todo_write`、`todo_read`、`turn_status` 和 `load_skill`。这些是 Sage 能力，不属于官方零售工具；必须在基线列表里预先可见，不能靠 RSI 隐式补入。初始 Skills 留空。工具可用性、执行权限和 shell 授权按页面实际配置检查；对比实验需保持一致。

### 4. 在进化页导入并运行

1. “导入数据集”选择本目录 `rsi.dataset.json`。
2. “导入评分器”选择本目录 `scorer.py`，等待自测通过后选择它。它通过 Python import 使用当前 checkout 的接入模块和 vendor；只拷贝这个文件到没有安装本仓库的机器不够。
3. 设置优化目标、训练初始题量、每轮增量、轮数、并发和重复次数；内部模型使用目标模型。
4. 点击“开始进化”。检查运行设置快照与题量，再观察基线轮和后续轮次。运行记录持久化到当前电脑，重新打开 Desktop 可查看。

建议先用小规模验证链路，再运行完整实验：

| 参数 | 快速流程检查 | 效果实验配置 |
| --- | ---: | ---: |
| 训练初始题量 | 3 | 24 |
| 每轮增加训练题 | 1 | 4 |
| 优化轮数上限 | 1 | 8 |
| 并行上限 | 3 | 10 |
| train/dev 每题重复次数 | 1 | 2 |
| System 字符上限 | 20000 | 20000 |
| 单个 SKILL.md 字符上限 | 15000 | 15000 |
| Skill 数量上限 | 2 | 2 |

**导入数据集后，其显式 split 决定实际 dev/test 题数**：当前文件固定 train 池 62、dev 12、test 40；生成题量的默认值不会把它改成 dev 24 / test 12。初始训练数量和增量控制从 train 池取题，旧训练题继续参与后续轮次；退化时暂停扩增。池用完后才由出题流程补充训练题。快速检查若要缩小 dev/test，需另存一个标准数据集并保留各 split；不要覆盖正式文件，也不要将小样本成绩称为完整 test 成绩。

test 只供人观察，不能把题目、对话、分数或诊断交给调优，也不能用它选择候选。最终 0.95 目标应由预先固定的全部 40 题平均分证明；流程测试通过不等于已达到该目标。评分器负责权威分数，诊断仍运行并保存；默认 Agent 评分不能替代已选择的官方评分器。

### 5. 迁移范围与恢复边界

- **从零开始新实验**：克隆代码、安装依赖、重建模型/MCP/基线配置、导入数据集和评分器即可，不需要旧机器运行目录。
- **保留旧实验历史**：退出所有 Sage Desktop 客户端并确认后台与实验停止后，将整个 `~/sage` 私下备份到新机器。它含模型凭证、catalog、SQLite 数据库、会话、实验目录和 Skills，不能提交 Git；不要只复制 `rsi.sqlite3`，也不要在后台写入时直接拷贝 SQLite 文件。
- 新电脑重新配置 MCP 的解释器、`PYTHONPATH`、状态路径和其他工作区绝对路径。不迁移 `.venv`、构建缓存、旧 sidecar 注册文件/锁；Python 环境重新安装，运行时注册由新后台生成。
- **跨机器续跑未完成实验不是已验证的无条件能力**。恢复会校验冻结配置、模型、引擎、资源和执行记录；历史包/检查点可能绑定旧绝对路径。不要批量改写实验 JSON 或绕过摘要校验。能否恢复应以恢复接口实际校验为准；路径或配置不一致时保留旧成果，在新电脑启动新实验。
- 单次传输故障局部重试，不重跑已完成的执行/评分；错误耗尽预算会保留检查点并明确报告。已完成实验若只缺人工测试，使用页面“继续测试”，不要重新开始调优。

源码版 macOS 是这里的验证范围；其他系统需另外验证 Flutter 构建和本地 MCP 进程启动。本机自动化测试不能替代新电脑实际的网关连通性和凭证验证。

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
