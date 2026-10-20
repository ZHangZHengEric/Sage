# v1 脚本

这些脚本服务于 `sagents.v1`、`app.v1`。从仓库根目录运行，使用当前项目的 Python 3.12+ 环境。
导入项目模块的脚本使用 `python -m scripts.v1.<模块>`；也可在文件入口前设置 `PYTHONPATH=.`。

| 入口 | 用途与副作用 |
| --- | --- |
| [dev-up.sh](dev-up.sh) | 启动 v1 开发服务，可能安装依赖、创建 `.env` 和写日志；不会启动 Server v2 |
| [memory_search_validate.py](memory_search_validate.py) | 在临时数据目录执行记忆检索检查和基准，不操作用户实际记忆目录 |
| [memory_search_benchmark.py](memory_search_benchmark.py) | 用临时合成文件评估 v1 文件记忆检索 |
| [benchmark_stream_message_merge.py](benchmark_stream_message_merge.py) | 离线比较流式消息合并，可选择本地历史消息或旧实现作为输入 |
| [diagnostics/](diagnostics/) | 离线流式延迟、快照、发现与目录访问等诊断；部分会启动本地沙箱或子进程 |
| [maintenance/](maintenance/) | 清理 v1 Session 的 `llm_request` 日志目录，默认 dry-run；传 `--apply` 才删除 |
| [release/](release/) | Tauri 更新清单生成器及旧 Desktop 工作流参考文件 |

```bash
python -m scripts.v1.memory_search_validate --noise-files 20 --top-k 3
python -m scripts.v1.benchmark_stream_message_merge --chunks 20
python -m scripts.v1.diagnostics.mock_stream_latency --requests 1 --chunks 20
python scripts/v1/maintenance/cleanup_llm_request_dirs.py --help
sh scripts/v1/maintenance/cleanup_llm_request_dirs.sh --help
python scripts/v1/release/generate_tauri_updater_manifest.py --help
```

`maintenance/` 中 Python 与 Shell 脚本均只匹配单数 `llm_request`，不能用于 v2 的
Run 存储维护。使用时应通过 `--sessions-root` 明确指定 v1 数据目录。

`diagnostics/benchmark_ledger_copy.py` 从本地 Git 提取提交 `284abc7f` 的历史实现；
浅克隆可能没有该对象。`benchmark_latency_algorithms.py` 使用测试目录内冻结的旧算法 fixture。
这些历史基线仍用于对比当前 v1 实现，不代表当前 v2 的性能。

`release/release-desktop.yml` 保留在脚本目录作为旧发布流程参考，位于 `.github/workflows/` 之外，
不会自动运行。更新清单生成器仍由 v1 自动化测试检查，不会在验证时发布资产。
