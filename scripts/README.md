# 仓库脚本

按版本归属组织脚本，版本由目录表达，文件名不再重复标注 `v1/v2`。
应用内部的构建和开发脚本仍保留在对应应用目录。

| 目录 | 内容 |
| --- | --- |
| [v1/](v1/README.md) | v1 开发启动、记忆检索验证、基准、诊断、数据清理及旧 Desktop 发布资源 |
| [v2/](v2/README.md) | v2 基准、OpenUI 探针与录屏处理、Desktop 打包和发布检查 |
| [shared/checks/](shared/checks/) | 跨版本架构检查、通用国际化检查、CLI/TUI 联合冒烟检查 |
| [shared/dev/](shared/dev/) | 仓库 Git hooks 设置 |

使用 Python 3.12+，从仓库根目录运行。导入项目模块的脚本推荐使用模块入口，
避免依赖当前 Python 是否已安装该仓库：

```bash
python scripts/shared/checks/check_architecture.py
python -m scripts.v1.memory_search_benchmark --noise-files 20 --top-k 3
python -m scripts.v2.benchmark_context --messages 20 --sessions 2
python scripts/v2/release/check_release.py
```

## 共用脚本

| 入口 | 用途与运行条件 |
| --- | --- |
| `shared/checks/check_architecture.py` | 只读检查 Python 导入、版本边界和独立 MCP 边界，不加载运行时；CI 使用同一入口 |
| `shared/checks/check-i18n-keys.mjs` | 检查 `--src` 下的静态国际化 key 是否同时出现在 `--zh`、`--en` 文件中；由 v1 两个 Web 工程的 `check:i18n` 调用 |
| `shared/checks/smoke_cli_tui.py` | 联合验证 v1/v2 CLI、TUI 和 APP 模型目录；默认使用本地模拟模型服务，需 POSIX PTY 和已构建的 Rust Terminal |
| `shared/dev/install-git-hooks.sh` | 将本地 Git 的 `core.hooksPath` 设置为 `.githooks`，会修改本地 Git 配置 |

CLI/TUI 冒烟检查：

```bash
cargo build --manifest-path app/clients/terminal/Cargo.toml
python scripts/shared/checks/smoke_cli_tui.py
```

`--app-model` 会通过 APP v2 当前用户的默认模型发出真实请求，可能产生模型费用。
默认目录为 `~/sage/runtime/desktop-catalog.json`；自定义 APP 数据目录时使用
`SAGE_DESKTOP_DATA_ROOT`。脚本使用临时任务存储，不修改保存的模型设置。

清理、开发启动、打包和真实模型探针都有各自的副作用，详见版本目录说明；
语法检查或 `--help` 成功不代表已完成真实发布、模型或系统沙箱验收。
