# Sage v2 标准 SDK 接入验收

完整接口与注册示例见 [SDK 宿主开发手册](sagents-host-development.md)。

## Desktop 标准链路验收

Desktop 的产品模型、MCP/Studio 工具、Skill、上下文、自配置和续跑策略均作为能力注册，由运行配置选择。交互展示使用的 `sage-openui` 通过 Agent 的 `preload_skills` 交给标准 Skill loader；宿主不直接读取 Skill 内容注入模型，预加载遵守授权、字符预算与激活恢复规则。

Studio 工具以受理 Run 中的 Agent 身份、Session 和所属用户校验调用。已属于 Studio 的 Session 缺少 Studio 身份时，预检直接失败，不另建替代 Run。工作区初始化也使用 App 当前选择的注册能力，不沿用已经变更的初始化器。

标准内存绑定 `sage.execution.binding.ephemeral` 仅提供进程内的独立虚拟文件系统，不提供本机 Python、FFmpeg 或网络。配置使用 `workspace_root`，子任务仅支持独立工作区。同一 App 的挂起可保留内存内容；进程重启后原内存不可恢复，必须报告 `execution.configuration_incompatible`。长期任务和媒体工作使用默认的 `sage.execution.binding.local-workspace`。诊断中的 `recovery: same_process`、隔离级别及实际能力用于明确区分两者。

相关自动化入口：`tests/app/v2/desktop`；SDK 配置和恢复验证位于 `test_standard_execution_configuration.py`、`test_standard_capability_scopes.py`、`test_builder_nested_teams.py` 和 `test_ephemeral_execution_binding.py`。标准媒体参考宿主的开发环境与冻结发行版验证使用 `test_standard_host_reference.py`，不依赖 Desktop 或 Server 内部执行实现。

## Server 标准链路验收

Server 同样使用标准 App、Agent 加载及执行入口。运行能力从实际 `execution.environment` 和已受理的产品配置取得身份、工具授权及资源。产品目录身份与标准执行身份分别校验；子 Agent 的工具范围取自其声明，运行限制与授权不得因切换到依赖包而扩大。

宿主 Scheduler 通过注册声明与共享模型连接池的依赖，配置保留并发和排队参数；App 负责先停止执行及调度，再关闭依赖资源。协议适配器通过运行配置选择 `ag-ui`、`a2a` 等公开名称。相关测试入口为 `tests/app/v2/server`，包含两个协议入口、恢复、并发、授权、媒体文件及资源关闭。

## 2026-10-19 本机验证结果

在 macOS、Python 3.13 环境执行，包含自定义注册工厂、标准 Run、配置冻结与恢复、嵌套 Team、沙箱租约和资源生命周期。模型与 MCP 使用可重复的测试实现；媒体验收实际运行 Python/Pillow 和 FFmpeg。

| 范围 | 结果 |
| --- | --- |
| `tests/sagents/v2` | 3265 passed，55 skipped |
| Desktop、Server 与 CLI v2 入口联合回归 | 958 passed，1 skipped |
| `tests/app/clients/cli` 全目录 | 225 passed |
| 最新共享存储修复后的两个宿主装配、插件及生命周期专项 | 56 passed |
| 标准媒体参考宿主：开发环境与重新构建的冻结发行版 | 4 passed |
| Ruff 与 `git diff --check` | 通过 |

联合回归包含 `tests/app/v2/desktop`、`tests/app/v2/server`、`tests/app/clients/cli/test_v2_run.py`，与 CLI 全目录结果有重叠，不应相加。Server 的跳过项为未配置外部 MySQL 的实库用例。SDK 另有可选服务、平台及显式启用验收的跳过项；媒体参考宿主的四项测试已另外显式启用并通过。

本轮验证不包含 Yiii 修改或打包，不代表已完成 Yiii 产品迁移、Linux 冻结发行版或真实连续数天的运行验收。标准参考项目位于 `examples/sagents_v2_standard_host`。

## 多层暂停任务直接恢复子 Run

标准恢复允许祖先仍暂停时直接继续子 Run。Sage 在 loop 装配前恢复必要祖先的资源租约，并从原执行图选择实际子 Agent；不执行祖先模型、不重建任务、不套用最新配置。祖先资源未就绪与配置无法恢复分别报告可恢复状态和配置不兼容。

接口示例、租约归属、释放顺序及验证范围见[多层子 Run 标准恢复](sagents-v2-run-tree-recovery.md)。

合并远端更新后，Yiii 提供的 `video-asset-agent-pause-resume` 与 `video-asset-agent-host-restart` 原始验收命令均通过（2 passed），未修改 Yiii。两项验证祖先仍暂停时直接恢复叶子，随后按原 Run 逐层继续，并检查实际 Skill 上下文和产物。
