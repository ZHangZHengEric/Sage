# v1 / v2 重构验证报告

日期：2026-09-28。分支：`codex/organize-v1`，迁移前基线：`49544f9f`。

当前结论：最终目录结构下，四个后端实际启动通过，三个 Web 前端和 macOS
Desktop v2 构建通过；已修复发现的路径、历史脚本加载和打包源码遗漏问题。
**不能宣称全部测试或所有平台均正常**：原有沙箱、Flutter Timer 和日志测试失败仍存在。

## 最终结构

- Agent 引擎：`sagents/v1`、`sagents/v2`。
- 应用实现：`app/v1/{cli,desktop,server,common,chrome-extension}`、`app/v2/{cli,desktop,server}`。
- 用户入口：`clients/cli`、`clients/terminal`；`sage` 命令兼容原用法，v2 CLI 不导入 v1。
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
