# AgentBench DB · Sage RSI

本目录将官方 DB 子任务接入标准 RSI：原始题库、MySQL 环境管理、SQL MCP、官方评分器和导入文件均已提供。

## 来源、范围与评分

- [官方 AgentBench](https://github.com/THUDM/AgentBench)，固定提交 `d1e4a10db08c87075c78972e48ecc182be03e2d5`；原件在 `vendor/`，许可证见 `vendor/LICENSE`，SHA256 见 `upstream.json`。这是该提交版本的 DBBench，不是 2023 论文版环境的逐项复刻。
- 官方 `standard.jsonl` **300 题**完整入库；另保留 `dev.jsonl` 60 题供追溯，不混入默认题库。
- 默认 300 题按表名家族整体划分，seed `20261023`：**234 training / 32 validation / 34 test**。同表的查询、INSERT、UPDATE 变体不跨 split；这是 Sage 内部划分，不是官方 dev/test。
- `execute_sql(query)` 执行 MySQL，保留官方 800 字符结果截断；`commit_final_answer(answers: list[str])` 首次提交即结束，最多 50 条 SQL。该动作预算与 Sage 编排区别于官方 max_round=15 的模型轮数。
- 官方 `_build_init_sql` 原样提取执行（所有初始列为 TEXT），官方 `DBResultProcessor` 原样加载。SELECT 使用其答案规范化与比较；INSERT/UPDATE/DELETE 使用实际表内容的官方哈希，提交的口头描述不决定成败。二元 0/1 分。
- 不加载上游 AgentRL/Redis 编排层。typing-only `interaction.Database` 使用接口占位，SQL 由同系列官方 mysql-connector-python 9.3.0 驱动真实 MySQL；不使用 SQLite 代替 MySQL。传给官方答案清洗器的目标答案始终为 list[str]，绕过其对任意字符串调用 eval 的分支。

## 安装并启动真实 MySQL

先安装并启动 Docker Desktop / Docker Engine，然后在仓库根目录：

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -e '.[desktop,test]' -r evaluation_datasets/agentbench_db/requirements.txt
.venv/bin/python -m pip check
.venv/bin/python -m evaluation_datasets.agentbench_db.manage start
.venv/bin/python -m evaluation_datasets.agentbench_db.manage status
```

首次 start 拉取 Docker Official Image `mysql:8.0.36`（固定 patch tag，实际 image ID 写入本机连接配置），初始化后运行真实建表/SQL 预检。不需要 GPU。容器限制为 1 GB RAM / 2 CPU，数据放在 512 MB tmpfs 中；端口只映射到 `127.0.0.1` 随机端口。相比上游 mysql:8 与大 buffer pool，这里固定了 patch 版本并降低资源配置。

容器使用专属标签 `sage.rsi.dataset=agentbench-db`，随机生成仅供这套临时基准使用的密码，gitignored `.runtime/connection.json` 权限 0600。不要改成生产数据库，也不要提交这个文件。每次重建任务新建数据库与仅有该库权限的临时用户，SQL 无 FILE/全局权限；结束即清理。为保证数据库名称稳定、查询结果可核对，重建操作以跨进程文件锁串行执行。目标 Agent 不接触管理凭据。

显式 start/stop 管理服务，评分器不会暗中启动 Docker。Docker 缺失、服务离线或连接中断时明确报错，不返回伪造零分。意外强行中断可能留下任务库；可 stop 后 start 清空整个专属容器。

```sh
.venv/bin/python -m evaluation_datasets.agentbench_db.manage stop
```

MCP 名称：**`AgentBenchDB`**，入口：`evaluation_datasets.agentbench_db.mcp_server`。

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
.venv/bin/python -m evaluation_datasets.agentbench_db.export_dataset
.venv/bin/python -m pytest -q tests/sagents/v2/test_world_rsi_datasets.py -k 'agentbench_db or db or mysql'
SAGE_TEST_DB_MYSQL=1 .venv/bin/python -m pytest -q tests/sagents/v2/test_world_rsi_datasets.py -k mysql
```

评分器导入时的两个自测覆盖无需 SQL 的官方 SELECT 正反例，**自测通过不代表 MySQL 已准备好**，必须另行完成 manage start/status。带环境变量的集成测试检查真实 INSERT/UPDATE 成功、未执行写入失败、重建隔离和全局表访问拒绝；默认没有 Docker 时明确 skip。

本次接入机器没有 Docker，因此已验证原始数据、官方比较器、评分器隔离进程与缺失服务报错，真实 MySQL 集成测试尚未在本机执行。请在具备 Docker 的环境运行上面那条集成测试后再做正式 RSI。每个工具调用会重建并重放此前 SQL，建议先小训练池、并发 1；包含随机/时间相关 SQL 的结果若不能稳定重放，会作为无效测量报错。
