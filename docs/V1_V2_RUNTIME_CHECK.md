# v1 / v2 重构验证报告

## 2026-10-11 CLI / TUI 共享 APP 模型配置

- 默认 v2 CLI 与 TUI 在后端启动时读取 `~/sage/runtime/desktop-catalog.json`，按当前用户选择 APP 默认模型；没有默认标记时沿用 APP 的首个模型回退。模型协议、上下文长度、输出限制、采样参数、能力声明及仍有效的兼容性配置随路由加载。
- APP 保存的密钥只通过进程内凭据引用传给 Runtime，不写入任务 manifest。配置读取不启动 Desktop，也不修改目录中的模型记录。
- `--package` 优先；显式 endpoint/key 环境配置保留原行为；仅覆盖模型名称时复用 APP 默认模型的协议、地址与密钥。自定义 APP 数据目录使用 `SAGE_DESKTOP_DATA_ROOT`；用户选择使用 CLI 的 `--user-id` / `SAGE_CLI_USER_ID` / `SAGE_DESKTOP_USER_ID`。v1 保留旧 Provider 配置。
- 新增共享目录/路由测试，覆盖默认模型切换、用户隔离、覆盖优先级、缺失密钥、损坏文件及密钥不进入 manifest。完整 CLI 回归在允许原生沙箱进程的环境 221 项通过；本地模型验证的四条 v1/v2 链路及四条 APP 配置/协议链路通过。
- 使用临时 APP 格式模型目录中的已配置真实 `deepseek-v4-flash`：默认 CLI 与 TUI 都正确计算 19 × 23，并完成任务，TUI 正常退出。未修改 APP 默认设置。
- 原 APP 默认 `DeepSeek-V4-Flash-Vision-Exp`（Responses）两次真实任务请求均遇到 HTTP 502；绕过 CLI 直接请求其 Responses 接口的非流式与流式请求也返回 502。
- 经用户确认，已将本地 APP 当前用户的默认模型切换为已配置的 `DeepSeek / deepseek-v4-flash`（Chat Completions）。原模型仍保留在配置中；本地模型目录不进入 Git。
- 切换后运行 `.venv/bin/python scripts/checks/smoke_cli_tui.py --app-model`，不传入模型名称、地址或密钥覆盖，默认 CLI 与 TUI 自动读取实际 APP 目录，均返回 `SAGE_LIVE_437` 并完成任务；TUI 正常退出。默认 v2 的真实模型验收通过。

## 2026-10-11 已配置真实模型验证

- 本地 Desktop v2 的 `~/sage/runtime/desktop-catalog.json` 有 7 个模型配置。CLI 环境配置未保存密钥，尚不自动读取 Desktop 模型目录；本次在隔离临时环境中加载其中的 DeepSeek 配置，未修改用户保存的模型或默认值。
- 使用真实 `deepseek-v4-flash` 模型执行“计算 19 × 23，并返回带前缀的答案”。输入未包含正确答案，四条链路均返回 `SAGE_LIVE_437`。

| 客户端 | Runtime | 结果 | 总耗时（含启动，v1 含 Provider 创建） |
| --- | --- | --- | --- |
| CLI | v1 | 完成 | 4.10 秒 |
| CLI | v2（默认入口） | completed | 1.48 秒 |
| TUI（PTY） | v1 | 完成且正常退出 | 6.61 秒 |
| TUI（PTY） | v2（默认入口） | 完成且正常退出 | 2.80 秒 |

- 真实验证发现并修复：v1 可选上下文长度为 `None` 时 `int(None)` 报错；TUI 收到会话信息时把仍在执行的任务错误显示为 ready。
- 验证脚本拼接 v1 流式回复片段，TUI 必须出现明确 completed 记录才退出，并持续读取退出时的 PTY 输出。
- Python 上下文压缩回归测试：45 通过；Rust Terminal：332 通过；拆分流式片段的本地模型四条任务回归也通过。
- 验证范围为真实模型推理与客户端任务完成流程。Desktop 默认模型使用 Responses 协议，本次未验证该模型，也未覆盖复杂工具任务或其他平台。

## 2026-10-11 CLI / TUI 验证

- CLI 默认使用 v2：`sage run`、`sage chat`、`sage sessions`；显式 v1 使用 `sage v1 ...`。
- TUI 默认使用 v2；`sage tui --runtime v1` 保留旧版入口。
- 原来的 35 个 V2 CLI 失败由测试环境缺少已声明的 `psutil` 引起；补齐后全部 84 个 V2 运行测试通过。
- 修复 v1 CLI 丢失环境变量模型密钥、Python 包缺少 `argon2-cffi`、TUI 忽略用户配置，启动任务被遗留重启标志中断，以及源码启动器未查找 Cargo 构建产物的问题。
- `.venv/bin/python -m pytest tests/app/clients/cli -q`：212 通过。
- `cargo test --offline --manifest-path app/clients/terminal/Cargo.toml`：331 通过。
- `.venv/bin/python scripts/checks/smoke_cli_tui.py`：CLI→v1、CLI→v2、TUI→v1、TUI→v2 均完成实际任务；TUI 使用 PTY，完成后正常退出。
- 实际任务使用本地确定性模型与临时存储，不调用外部模型。原生沙箱测试需允许 macOS Seatbelt 创建进程；外层限制中的嵌套沙箱会导致进程执行假失败。
- Python 导入检查通过；完整架构脚本仍报告五个本地已有旧目录残留。本次未重新验证桌面端或其他平台。

以下为 2026-09-28 的历史验证记录。

日期：2026-09-28。分支：`codex/organize-v1`，迁移前基线：`49544f9f`。

当前结论：最终目录结构下，四个后端实际启动通过，三个 Web 前端和 macOS
Desktop v2 构建通过；已修复发现的路径、历史脚本加载和打包源码遗漏问题。
**不能宣称全部测试或所有平台均正常**：原有沙箱、Flutter Timer 和日志测试失败仍存在。

## 最终结构

- Agent 引擎：`sagents/v1`、`sagents/v2`。
- 应用实现：`app/v1/{cli,desktop,server,common,chrome-extension}`、`app/v2/{cli,desktop,server}`。
- 用户入口：`app/clients/cli`、`app/clients/terminal`；公共入口按所选版本分发，v2 CLI 不导入 v1。
- AnyTool：`mcp_servers/anytool` 独立 MCP，不导入 `app`、`common` 或 `sagents`。
- 内置技能唯一源码：`app/skills`。原根目录 `skills` 为本地未入库内容，包含同名不同版本，
  已完整归档到 `.sage/organization-backup/root-skills`，22 个文件/链接经内容或目标校验。
- 脚本：`scripts/{checks,dev,maintenance,release,v1,v2}`，详见 [脚本目录说明](../scripts/README.md)。

## 测试与实际执行证据

各 Python 套件分别启动进程，避免旧版全局配置互相污染。使用项目 Python 3.13.3，
测试数据放在临时目录，原生沙箱测试在允许创建进程的环境执行。
启动与后端测试通过 `/tmp/run_sage_runtime_checks.py` 补充加载
`/tmp/sage-runtime-check-deps` 中的 AG-UI、Prometheus、A2A 等依赖。
当前项目 `.venv` 并未完整安装这些依赖；直接启动相关后端前仍须安装项目声明的依赖
及需要的 Server v2 extra。测试启动成功不等于当前裸虚拟环境已准备完整。

| 范围 | 结果 |
| --- | --- |
| SAgents v1 与公共引擎入口 | 1,519 通过、7 跳过；另 41 子测试通过 |
| SAgents v2 | 2,311 通过、12 失败、20 跳过 |
| v1 Desktop/Server、v2 Desktop、MCP、部署与架构 | 334 通过 |
| v1 应用服务 | 236 通过、1 失败 |
| v2 Server（清理 Web dist 后） | 219 通过 |
| CLI、双向导入隔离与架构回归 | 207 通过 |
| Rust Terminal | 330 通过 |
| v1 Desktop Web | 58 通过 |
| v1 Server Web | 78 通过 |
| Flutter 全量 | 109 通过、123 失败 |
| 新增 Windows 构建输入检查及部署/架构复查 | 12 通过 |

四个后端均使用隔离数据、真实 Uvicorn 进程及 loopback HTTP 请求验证，结束后关闭：

- Desktop v1、Server v1：健康检查、OpenAPI、异步初始化后再次检查均返回 200。
- Desktop v2：正式 sidecar 模块入口、认证健康检查、Agent 列表与设置返回 200。
- Server v2：健康检查、注册、登录与 Agent 列表返回 200；使用 SQLite/测试模型宿主。

三个 Web 前端构建通过。Flutter macOS Debug 应用构建通过；清除旧目录缓存后
再次完整构建通过，未重新生成旧 `app/desktop_v2` 目录。CLI 安装入口、Terminal
分发启动、Wheel 构建与隔离目录导入也已验证。

本轮脚本验证包括三个缩小规模的 v2 benchmark、v1 流合并、内存搜索、五个旧版
离线诊断和模拟流脚本；维护/发布脚本检查帮助入口，Shell 脚本做语法检查。
`memory_search_validate.py` 全流程通过。未运行实际删除历史会话、安装 Git hooks
或启动开发服务的管理脚本。

主要本机日志（不入库）：

- `/tmp/sage-deep-v1.log`、`/tmp/sage-deep-v2.log`、`/tmp/sage-deep-apps.log`
- `/tmp/sage-deep-common.log`、`/tmp/sage-deep-server-clean.log`
- `/tmp/sage-split-cli-final.log`、`/tmp/sage-split-terminal-tests.log`
- `/tmp/sage-deep-desktop-ui.log`、`/tmp/sage-deep-server-ui.log`、`/tmp/sage-deep-flutter.log`
- `/tmp/sage-deep-flutter-clean-build.log`、`/tmp/sage-deep-http-check-results.json`
- `/tmp/sage-script-smoke/`、`/tmp/sage-memory-validation.log`

## 修复与剩余问题

已修复：

1. 迁移后的源码、测试、CLI 分发、构建发布与资源路径引用。
2. 历史 ledger benchmark 的 Git 对象路径不应随当前目录迁移；加载旧代码时仅适配旧 import。
3. 内存验证脚本改用隔离临时数据，不再向开发者真实 `~/.sage` 写测试内容。
4. Flutter Windows 必需的 `runner.exe.manifest` 曾被通用 `*.manifest` 规则忽略；
   已明确允许入库并加验证，防止干净检出缺少构建输入。

剩余问题：

- 12 个 v2 本机沙箱测试无法读取项目虚拟环境的 `pyvenv.cfg`，子进程报
  `Fatal Python error: init_import_site`。此前已在迁移前基线复现，未放宽安全策略。
- 123 个 Flutter 测试遗留 Studio 周期 Timer；此前基线结果同为 109 通过、123 失败。
- 日志队列测试的一秒同步等待超时，基线也可复现。
- Server v2 的 `/studio` 测试依赖本地构建状态：存在 Web dist 时实际返回 SPA 200，
  测试仍期待 404；清理 dist 后本轮全部 219 项通过。这是测试隔离问题。

未验证真实付费模型、生产 MySQL/RustFS、Windows/Linux 原生构建、完整旧 Desktop
安装包以及所有界面人工操作。上述结果不代表生产或跨平台全功能保证。

## 本地清理

删除范围是 Git 忽略的缓存、构建产物、旧 sidecar、依赖目录、临时日志和空残留目录；
删除前后对全部当前非忽略源码文件逐一校验内容，未使用 `git clean` 删除未提交源码。
保留 `.venv`、`.sage`、`.sage-terminal-state`、`app/agent_workspace`、签名证书及 IDE 配置。
清理记录在 `/tmp/sage-ignored-cleanup*.json`。

前端依赖需重新 `npm ci`，Flutter 需 `flutter pub get`；Rust 与安装包需重新构建。
缓存和日志在以后运行时可能重新生成。已更新的 Python `sage` 入口仍可直接使用。
