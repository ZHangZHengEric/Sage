# Sage v2 代码阅读指南

基于 sagents 开发新项目，请先看[统一开发入口、配置与调试规范](sagents-host-development.md)。

[English](../../en/architecture/code-reading-guide.md)

Sage 分为可嵌入的 sagents 运行时，以及 desktop、server 两个产品宿主。
建议先追踪一次 Run，不必从最大的文件开始，也不需要先理解 `app/v1`。

## 第一次阅读

1. 从 [Python 示例](../../../examples/sagents_v2_quickstart.py) 开始，沿着
   `build → entrypoint → run_stream → wait → close` 阅读。
2. 阅读 [命令](../../../sagents/v2/contracts/commands.py)、
   [Run 状态](../../../sagents/v2/contracts/run_state.py)和
   [事件](../../../sagents/v2/contracts/events.py)，先明确输入、状态和输出。
3. [Builder](../../../sagents/v2/builder.py) 是公开配置入口；
   [Application](../../../sagents/v2/application.py) 定义装配和应用生命周期。
4. [SAgent](../../../sagents/v2/sagent.py) 管执行任务与观察流；
   [Kernel](../../../sagents/v2/runtime/kernel.py) 管持久化命令。
   观察流断开不代表取消运行。
5. 最后阅读 [AgentLoopEngine](../../../sagents/v2/agent/engine.py) 中的模型步骤、
   工具执行、检查点和恢复。此次装配重构没有重写这里的状态机。

## 按修改目的找代码

| 想修改什么 | 从哪里开始 | 对应测试 |
| --- | --- | --- |
| 应用装配、插件选择 | [装配目录说明](../../../sagents/v2/composition/README.md) | `tests/sagents/v2/test_builder_matrix.py` |
| Run 资源归属、失败清理 | `sagents/v2/application.py`、`composition/resources.py` | `test_run_composition_lifecycle.py` |
| 工具执行、未知副作用恢复 | `sagents/v2/agent/engine.py`、`runtime/execution/lifecycle.py` | recovery、execution binding 相关测试 |
| Session 持久化 | `runtime/session/contracts.py`，再看 `state.py` | session store、事务和 fencing 测试 |
| 模型、工具、存储插件 | 对应领域契约，再读一个 `plugins/` 实现 | 插件测试和 `test_source_boundary_matrix.py` |
| Server 授权与受理 | `app/v2/server/conversations/admission.py`、`identity/` | `tests/app/v2/server` |
| Desktop 后端行为 | `app/v2/desktop/backend/service.py`、`run_service.py` | `tests/app/v2/desktop` |
| Desktop 状态与显示 | `lib/src/state/workspace_controller.dart`、`ui/` | `app/v2/desktop/test` |

## 装配代码怎么读

`SAgentBuilder` 只收集明确的 `BuildOptions`，交给 `ApplicationAssembler`：
解析配置、创建进程服务、装配 Agent/Flow、校验能力、启动 dispatcher。
`AgentMaterializer` 在已有应用上提供有租户、Agent、Run 作用域的组件。
两条路径通过 `providers.py` 使用 ExtensionHost 创建选定的插件。

继续阅读时，按职责看三个具体入口：

- `composition/agent_components.py`：Agent 组件的依赖图和具名结果，替代位置元组；作用域仍由应用管理。
- `composition/bound_tools.py`：已校验的执行绑定如何接入工作区、工具和运行服务；获取、回滚与恢复仍由驱动负责。
- `agent/factory.py`：所有宿主调用 `create_loop()`，通过参数选择提示顺序、完成门控和上下文预算，共用授权与历史装配规则。

`application.compose_run()` 是两端共同的运行装配与资源所有权入口。
回调只注册新创建且归本次运行所有的资源；装配失败时回滚，成功时把清理责任
交给调用方。它不创建 Run、不执行工具，也不代替调度器或恢复状态机。

服务资源先于其依赖关闭，例如先关闭作用域服务，再关闭沙箱。正常关闭时，
服务关闭失败会保留沙箱；重试只处理失败的资源。装配失败的清理沿用原有
回滚规则，残余失败资源由应用保留，以便关闭时再次清理。

## 两端调用链

**Server**：`bootstrap.py` 创建进程服务；会话 admission 冻结本次运行的配置与
授权；`runtime/loop.py` 调用 `application.compose_run()`；
`packages/builder.py` 通过 `with_shared_runtime()` 借用进程服务；
`runtime/driver.py` 中的 `CatalogRunDriver` 驱动并关闭本次 Package 应用。
Skill 的目录和工作区适配器仍留在 `skills/runtime.py`，不再混放运行驱动。

**Desktop**：`backend/service.py` 持有进程服务；`run_service.py` 受理和观察运行；
`run_composition.py::_build_loop` 使用相同的 `application.compose_run()`，
通过 `materialize_agent()` 获取作用域组件，保留桌面特有的审批和工作区接线；
`run_lifecycle.py` 处理挂起、延后释放与沙箱生命周期。

Desktop 的 `component_plan.py` 只负责将已确定的设置快照转换为组件选择、锁定配置和缓存身份；
`model_providers.py` 只负责模型路由转换和进程级缓存，共用宿主的并发预算。
`run_composition.py` 负责连接这些对象与运行策略，不再重复模型路由或上下文预算算法。
成员上下文仍使用根 Agent 的预算，提示顺序与 plan/goal 完成门控保持原样。

宿主装配仍包含一定规模的产品接线，本次没有为了缩短文件而强行合并两端策略，
也没有把所有大方法拆完。

## 修改时需要保持的边界

- sagents 不导入应用，desktop 与 server 不互相导入。
- 插件实现独立，可以重复代码，不导入兄弟插件实现。
- 恢复使用已受理的配置身份与授权范围，不能从实时配置悄悄扩大权限。
- Session 状态、事件与检查点保留统一的原子提交边界。
- 外部副作用结果未知时挂起或核对，不因重构清理流程而自动重试工具。
- 关闭某个 Run 的应用不能关闭借用的进程级服务。
- 内存资源清理不等于持久化沙箱释放或 reconciliation。

## 验证入口

在仓库根目录使用 Python 3.12+ 虚拟环境：

```bash
.venv/bin/pytest -q tests/sagents/v2/test_builder_matrix.py tests/sagents/v2/test_run_composition_lifecycle.py tests/sagents/v2/test_source_boundary_matrix.py tests/sagents/v2/test_composition_source_boundaries.py
.venv/bin/pytest -q tests/app/v2/server tests/app/v2/desktop
```

真实模型、数据库和外部沙箱测试需要各自的环境。单机测试通过不等于已经验证
分布式部署能力。


当前统一入口：`builder.build()` → `app.load_agent()` → `app.entrypoint().run_stream(..., agent=agent)` → `app.close()`.

加载、版本发布和恢复快照分别在 `sagents/v2/composition/loaded_agents.py`、`inputs.py`、`revision_store.py`；`defaults.py` 由 SDK 与 Desktop 共用组件默认值。


统一入口的阅读顺序：`sagents/v2/builder.py` 创建 App，
`composition/loaded_agents.py` 管理版本和生命周期，`composition/agent_graph.py`
绑定独立子 Package，`agent/management/loading.py` 加载持久化的依赖树。
CLI 的实际装配在 `app/v2/cli/host.py`，TUI 通过 CLI v2 协议复用它。
