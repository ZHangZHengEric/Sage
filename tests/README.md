# 测试目录说明

`tests/` 集中存放 v1、v2 的 Python 引擎和应用后端测试，按源码归属区分版本。
Web、Flutter、Rust 和文档检查测试使用各自的运行工具，部分位于应用或文档目录内。
收集成功、测试通过和真实环境验收应分别判断；测试文件数量不代表业务已完整覆盖。

## Python 测试分布

以下路径相对于 `tests/`：

| 目录或文件 | 用途 |
| --- | --- |
| [sagents/v1/](sagents/v1/) | v1 引擎：Agent、Flow、工具、消息、上下文及解析器等 |
| [sagents/v2/](sagents/v2/) | v2 引擎：公开 SDK、运行状态、SessionStore、插件、沙箱、并发及恢复等 |
| [sagents/v2/live/](sagents/v2/live/) | 显式启用的真实模型验收 |
| [sagents/test_architecture.py](sagents/test_architecture.py) | 验证架构检查器对导入边界的检查行为 |
| [sagents/test_versioned_layout.py](sagents/test_versioned_layout.py) | 跨版本公开导入及 v1 示例入口检查 |
| [app/v1/common/](app/v1/common/) | v1 应用服务、模型等 |
| [app/v1/server/](app/v1/server/) | v1 Server 后端 |
| [app/v1/desktop/](app/v1/desktop/) | v1 Desktop 后端 |
| [app/v2/server/](app/v2/server/) | v2 Server 后端 |
| [app/v2/desktop/](app/v2/desktop/) | v2 Desktop Python 宿主 |
| [app/clients/cli/](app/clients/cli/) | 统一 CLI 入口、版本分发、TUI 启动和命令契约 |
| [mcp_servers/](mcp_servers/) | 独立 MCP 服务及其集成 |

引擎测试分别对应 `sagents/v1/` 和 `sagents/v2/`，跨版本检查留在 `tests/sagents/`。
当前可运行的框架示例见 [examples/v1/](../examples/v1/) 和 [examples/v2/](../examples/v2/)。

## 本地运行 Python 测试

使用 Python 3.12+，从仓库根目录执行。v1、v2 使用独立虚拟环境，依赖分别由
[app/v1/requirements-test.txt](../app/v1/requirements-test.txt) 和
[pyproject.toml](../pyproject.toml) 定义。Linux 沙箱测试需要工作正常的 bubblewrap。

```bash
# v2：不安装 v1 依赖。
python3.12 -m venv .venv-v2
source .venv-v2/bin/activate
python -m pip install -e '.[server,desktop,otel,test]'
python -m pip check
python -m pytest tests/sagents/v2 tests/app/v2 -m 'not live' -q
# 只收集测试也会导入测试模块及其依赖。
python -m pytest --collect-only -q tests/sagents/v2
deactivate

# v1：独立使用旧版依赖清单。
python3.12 -m venv .venv-v1
source .venv-v1/bin/activate
python -m pip install -r app/v1/requirements-test.txt
python -m pip check
python -m pytest tests/sagents/v1 tests/app/v1 tests/mcp_servers -m 'not live' -q

# 跨版本入口检查：显式组合两个版本的依赖。
python -m pip install -e '.[server,desktop,otel,test]'
python -m pytest tests/app/clients tests/sagents --ignore=tests/sagents/v1 --ignore=tests/sagents/v2 -m 'not live' -q
python scripts/shared/checks/check_architecture.py
```

Windows 使用对应环境的 `Scripts\Activate.ps1` 激活。

直接运行 `python -m pytest` 时，[pytest.ini](../pytest.ini) 默认收集 `tests/`；
它不会自动执行 Web、Flutter、Rust 或 `docs/scripts/` 的测试。
真实模型、外部数据库、原生沙箱等测试是否执行，还取决于各测试的启用条件及环境依赖。

[pytest.ini](../pytest.ini) 的 `pythonpath = .` 将仓库根目录加入测试导入路径。
pytest 默认给每个测试设置 30 秒的超时保护，这是防止挂起的上限，不是性能指标。
需要更长时间的用例使用 `@pytest.mark.timeout(seconds)`；性能要求应另写明确的耗时断言。

## CI 覆盖范围

[ci-tests.yml](../.github/workflows/ci-tests.yml) 先检查源码架构，再执行六个 Python 套件：

| 套件 | 测试路径 | 安装环境 |
| --- | --- | --- |
| app-v1 | `tests/app/v1` | v1 requirements-test |
| sagents-v1 | `tests/sagents/v1` | v1 requirements-test |
| app-v2 | `tests/app/v2` | v2 Server/Desktop/OTel/test extras |
| sagents-v2 | `tests/sagents/v2` | v2 Server/Desktop/OTel/test extras |
| mcp | `tests/mcp_servers` | v1 requirements-test，包含旧版 MCP 集成依赖 |
| cross-version | `tests/app/clients`、`tests/sagents` 根级测试 | 显式组合 v1 和 v2 依赖，排除版本内测试 |

每个套件独立安装后运行 `pip check`，并排除标记为 `live` 的真实模型用例。

该工作流还运行 v1 Server Web 的 Vitest 和国际化检查、v1 Desktop UI 的国际化检查、
v2 Server Web 的构建，以及 v2 Desktop 的 `flutter analyze` 和 `flutter test`。
v1 Desktop UI 的 Vitest、v2 Server Web 的 `npm test`、Rust 测试和 Flutter
`integration_test/` 不在该工作流的默认执行步骤中。

[文档工作流](../.github/workflows/docs.yml) 单独执行文档源检查和站点构建，
没有执行 `docs/scripts/` 下的检查器单元测试。
CI 结果应按具体工作流和套件理解，不能等同于所有技术栈、平台和真实服务均已验收。

## `tests/` 之外的测试入口

先在对应目录安装依赖，再执行下列命令。表中工作目录相对于仓库根目录：

| 范围 | 工作目录 | 命令 |
| --- | --- | --- |
| v1 Server Web | `app/v1/server/web/` | `npm test -- --run`、`npm run check:i18n` |
| v1 Desktop UI | `app/v1/desktop/ui/` | `npm test -- --run`、`npm run check:i18n` |
| v2 Server Web | `app/v2/server/web/` | `npm test`、`npm run build` |
| v2 Desktop 界面 | `app/v2/desktop/` | `flutter analyze`、`flutter test` |
| Desktop OpenUI 运行时 | `app/v2/desktop/backend/openui_runtime/` | `npm test` |
| Rust Terminal | `app/clients/terminal/` | `cargo test` |
| 文档检查器单元测试 | 仓库根目录 | `python -m unittest discover -s docs/scripts -p 'test_*.py'` |
| 文档源检查 | 仓库根目录 | `python docs/scripts/check_docs.py` |

Flutter 原生集成脚本位于 `app/v2/desktop/integration_test/`，需要单独选择设备、准备配置并运行。
真实模型 RSI 验收的启用方式见 [Desktop README](../app/v2/desktop/README.md)。

## 需要显式准备环境的验收

- `tests/sagents/v2/live/` 使用真实模型。未配置 `SAGE_V2_LIVE_API_KEY` 时跳过；
  `SAGE_V2_LIVE_BASE_URL`、`SAGE_V2_LIVE_MODEL` 可指定端点和模型。启用会产生真实请求，
  应先确认服务及费用。普通本地回归可用 `-m 'not live'` 排除这些用例。
- [test_standard_host_reference.py](sagents/v2/test_standard_host_reference.py) 的原生验收
  需设置 `SAGE_V2_NATIVE_HOST_ACCEPTANCE=1`，并准备 FFmpeg、Pillow 和原生沙箱环境。
  冻结程序场景还需 `SAGE_V2_FROZEN_HOST`；构建边界见
  [标准宿主说明](../examples/v2/standard_host/README.md)。
- 外部存储和其他服务集成的准备条件以对应测试与 fixture 为准。
  缺少依赖导致的收集错误、条件不满足导致的跳过，都不代表相关行为通过验证。
