# ScienceWorld · Sage RSI

本目录包含官方 Java 模拟器 JAR、Python 包装层、原始 goldpath ZIP、已核验的 125 题默认子集、MCP 和独立评分器。运行时无需克隆上游、下载题库或使用模型服务来判分。

## 来源、数据与评分

- [官方仓库](https://github.com/allenai/ScienceWorld)，固定提交 `e8216d6044e8e39be9fcb185e3b2dfb602584b52`；`vendor/LICENSE` 为上游许可证，`upstream.json` 固定全部源码、JAR 与原始数据的 SHA256。
- 来源 `vendor/goldpaths/goldpaths-all.zip`：其中包含 29 类任务的轨迹，缺少索引 5；本适配器不声称覆盖全部 30 类。
- 先按每类官方 **3 train / 1 dev / 1 test** 选出 145 个候选；每个 fold 按参考路径长度、variationIdx 排序取前几条。
- 逐题启动任务、检查官方 fold 并执行历史参考路径后，125 条在固定 JAR 上达到 100 分；20 条历史路径未满分，因此从默认导入中排除，不据此断言任务本身不可解。默认覆盖 28 类，共 **75 training / 27 validation / 23 test**。各类覆盖不均，偏向短路径且筛选了已验证任务，不能与官方全量榜单比较。
- `data/validation.json` 保留全部核验结果、被排除 ID 与 JAR 哈希。19 处历史题面与当前 JAR 存在拼写或单位差异（如 green house/greenhouse、degrees celsius），导出题面按 JAR 的实际描述修正。
- `data/tasks.json` 保留 145 个候选的 task/variation/fold/题面、原始题面和评测端参考动作；导出的题目只包含题面和 task ID，参考动作不传给目标 Agent。
- 使用原版 JVM，无 simplification、不生成 gold path。`observe` 返回观察、look 和 inventory，`step(action)` 交互，最多 200 个目标动作；官方 reset 自带的一次 look-around 不占这 200 次。
- 评分为官方 Python API 的累计 `info['score']` 截到 `[0,100]` 再除以 100，保留部分分；100 分才 passed。不是最后一步的 delta reward。失败负分归零。完成后不再接受动作。

## 安装、配置 Java 与真实环境预检

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -e '.[desktop,test]' -r evaluation_datasets/scienceworld/requirements.txt
.venv/bin/python -m pip check
.venv/bin/python -m evaluation_datasets.scienceworld.configure --java-home /absolute/path/to/jdk-or-jre-17
.venv/bin/python -m evaluation_datasets.scienceworld.runtime
```

需要自行安装 Java 17 JRE/JDK，不需要 GPU 或 Docker。macOS `/usr/bin/java` 可能只是没有运行时的占位程序，必须实际执行 `java -version` 成功。预检会启动官方 JVM 并 reset 一道任务。

`configure` 将本机 JRE 路径保存在 gitignored `.runtime/java.json`，同时供 MCP 和独立评分器使用；换电脑重新运行。若 Desktop 启动时 PATH 已包含可用的 Java，也可省略 configure。**只在 MCP 配置中设置 JAVA_HOME 不够**：独立评分器会清理环境变量，只保留 PATH 等少量字段。工具和评分器都必须能启动 Java。JVM 使用 py4j 的本机 loopback 网关，需允许本地进程通信，无外部网络请求。

上游 Git 不包含打包时生成的 `scienceworld/version.py`，适配器使用 namespace 导入其未改动的模拟器子模块，JAR 和 Python 运行逻辑保持原样。

MCP 名称：**`ScienceWorld`**，入口：`evaluation_datasets.scienceworld.mcp_server`。

## 在 Desktop 中使用

1. 在仓库根目录建 Python 3.12 虚拟环境，安装 Sage 和本目录依赖（命令见上文）。已有 `.venv` 时只需补装依赖。源码版 Desktop 后端使用 `.venv/bin/python`，评分器依赖必须也装在这里。
2. 按 `mcp.example.json` 添加 stdio MCP。替换所有 `/absolute/path/Sage`、状态文件绝对路径；连接名称必须使用本文指定名称，设置 `SAGE_RSI_CASE_PROTOCOL=sage.rsi.case/v1`。目标 Agent 的 system 可使用 `policy.md`，只启用这套 MCP。
3. 在 RSI 页导入 `rsi.dataset.json`，再单独导入 `scorer.py`，等待正反例自测通过并选中评分器。
4. 首次建议初始训练 6 题、每轮新增 0、优化 1 轮、并发 1、重复 1 次。为目标 Agent 留足工具调用与运行时间预算；正式实验再增加题数。固定题池可避免自动出题产生没有官方环境的新任务。

题目 ID 只在 `environment_context` 中绑定官方世界。每道题、候选版本和重复试验使用 RSI 分配的独立状态目录。SQLite 保存调用日志，stdio 重连后从官方初态重放，因此连接结束不会丢失状态。普通状态路径只用于命令格式兼容；激活 RSI case 时实际状态由其独立目录接管。未激活 case 只能发现工具，不能执行任务。

评分器从 canonical `final_items` 提取实际完成的工具调用，在全新环境重放并核对原生工具结果。权限拒绝、环境依赖缺失和结果不一致会明确报测量错误，不伪装为 Agent 零分。MCP 不提供评分、参考答案、重置或数据集查询工具。避免给目标 Agent 额外的文件读取/Shell 权限，否则它可以读取仓库中的隐藏参考；这些文件只供可信评测端使用。

这是 Sage 的固定 RSI 实验范围，不等于完整官方榜单复现，也不包含已完成的模型优化效果实验。导入后 train 用于优化，validation 用于候选选择，test 应保持独立。新增自然语言题目不能凭空获得官方环境或参考，当前评分器只接受已收录的 task ID。

## 再生成与验证

```sh
.venv/bin/python -m evaluation_datasets.scienceworld.prepare_data
.venv/bin/python -m evaluation_datasets.scienceworld.export_dataset
.venv/bin/python -m pytest -q tests/sagents/v2/test_world_rsi_datasets.py -k 'scienceworld or exports'
```

`verify_reference_paths` 可重新运行全部 145 条核验（无需模型，需 Java）；修改核验结果后重新执行 prepare_data 和 export_dataset。默认导出仅保留核验满分 ID。

原始 ZIP 解压后是约 463 MB 的单个 JSON。再生成脚本用 ijson 流式读取，日常运行只读取小型固定清单，不展开全量文件。自测正例由实际 JVM 跑通的官方参考路径生成，截到首次完成；反例为未执行任务。

stdio 重连时从任务初态重放动作，因此每次调用会启动短生命周期 JVM，长轨迹较慢。当前实现适合先以并发 1、小训练池跑通 RSI；不是高吞吐常驻环境池。关闭后显式回收 Java 子进程。
## 单轮循环保护

`native-v2` 可评分具有完整原生工具收据的单轮循环保护终点，保留真实 Run 的
`suspended` 状态。分数仍由固定官方环境重放后的累计奖励决定，未经确认的工具
效果或截断轨迹不视为有效测量。参见
[RSI 执行边界](../../sagents/v2/optimization/NATIVE_EPISODES.md)。
