---
layout: default
title: 宿主开发指南
parent: 架构
nav_order: 13
lang: zh
ref: v2-detail-sagents-host-development
---

{% include lang_switcher.html %}

# Sage v2 标准宿主接入

宿主通过 `builder.register(registration)` 注册实现，通过可序列化的 runtime
配置选择插件、scope 和参数。内置与自定义实现使用同一条执行流程：

```python
from sagents.v2 import SAgentBuilder

builder = SAgentBuilder()
for registration in host_registrations:
    builder.register(registration)
app = await builder.build(runtime=runtime_config, models=model_config)
try:
    agent = await app.load_agent(package, subagents=subagents)
    command = command.model_copy(update={
        "agent_id": agent.id,
        "resolved_spec_hash": agent.composition_hash,
    })
    stream = await app.entrypoint().run_stream(command, context, agent=agent)
    async for event in stream.events:
        handle_event(event)
    result = await stream.wait()
finally:
    await app.close()
```

`subagents` 将声明的直接成员名映射为已加载的 Agent；每个包一个 Agent，嵌套 Team
使用明确的包依赖。普通委派叶子不会获得父 Team 的成员列表或额外委派权限。

## 注册契约

`ExtensionRegistration` 包含 `ExtensionDescriptor`、能力工厂、可选的 start/stop
钩子、参数模型及所有权。Descriptor 声明插件版本、能力协议版本、参数 JSON Schema、
依赖、支持的作用域及默认作用域。工厂只实现相应能力，不重建 Driver、loop 或工具执行链。

```python
from sagents.v2.runtime.extensions import (
    CapabilityOffer, ExtensionDependency, ExtensionDescriptor,
    ExtensionRegistration, ExtensionScope,
)

builder.register(ExtensionRegistration(
    descriptor=ExtensionDescriptor(
        plugin_id="example.model", name="Example model", version="1.0.0",
        provides=(CapabilityOffer(capability="model.provider", api_version="2"),),
        dependencies=(ExtensionDependency(capability="session.store"),),
        supported_scopes=frozenset({ExtensionScope.RUN}),
        default_scope=ExtensionScope.RUN,
        config_schema={"type": "object", "additionalProperties": False},
    ),
    factory=lambda scope, deps: ExampleModel(
        run_id=scope.run_id, store=deps.require("session.store")),
    ownership="owned",
))
```

`ExampleModel` 实现标准模型协议。注册只决定可用实现，配置决定本次选择：

```yaml
capabilities:
  model.provider:
    plugin: example.model
    scope: run
    config: {}
```

已有对象同样通过工厂返回。`borrowed` 对象由创建者关闭，Sage 不转移关闭责任；
`owned` 对象由 Sage 在回滚或作用域结束时释放。借用注册不能同时声明 stop 钩子。
进程对象、数据库连接和锁不能写入 runtime；使用工厂和声明的依赖传递。
模型密钥使用 App 模型目录和正式凭据提供者。

process、tenant、agent、run 的身份和依赖生命周期参与校验。较长生命周期的消费者
不能捕获较短生命周期的依赖。Run 工厂在实际 Run ID 分配后创建；Agent/Run scope
可读取 SDK 已解析的 Agent 配置，process scope 不携带某个任意任务的身份。
缺失或重复注册、协议冲突、参数错误及 scope 不兼容应明确失败。
包中的插件声明不会自动授权导入任意代码。

使用 `builder.inventory()` 查询注册，用 `agent.resolved_plan` 查询最终选择、依赖、
版本和来源摘要。自定义源码插件的模块与声明由标准生命周期管理。

## 配置冻结与恢复

`app.update_runtime(runtime)`、`app.update_models(models)` 更新后续加载的 Agent
版本；已受理任务保留原 Agent、模型路由、插件选择和执行快照。store、queue、安全配置
是 App 的进程身份，改变时应创建另一个 App。多个 App 的配置互不替代。

```python
agent = await app.agent_for_run(run_id, context)
task = await app.entrypoint().continue_run(run_id, context, agent=agent)
result = await task
snapshot = await app.execution_configuration(run_id, context)
diagnostics = await app.execution_diagnostics(run_id, context)
configuration = await app.run_configuration(run_id, context)
```

查询会先授权，并返回独立副本。挂起任务先按正常交互契约回复，再继续执行。
进程重启仍使用归档版本；无法恢复所需配置或能力时应报告不兼容，不能替换为当前默认值。
外部副作用状态不确定时依照工具恢复契约协调，不能盲目重试。

## 本地媒体沙箱

选择 `sage.execution.binding.local-workspace`，在其 config 中指定：

| 配置 | 归属 |
| --- | --- |
| `workspace`、`private_workspace_root` | 共享根目录与共享根目录之外的私有子工作区 |
| `child_workspace_policy` | `shared_parent`、`private_child`、`read_only_parent` |
| `policy.filesystem` | 单文件大小、文件总量、允许操作 |
| `policy.process` | 可执行程序、Shell、允许的环境变量、执行时间和输出上限 |
| `policy.resources` | CPU、内存、磁盘、进程数及是否要求硬限制 |
| `policy.network` | 网络模式和私网访问策略 |
| `command_path`、`read_paths` | Agent Shell 搜索路径与额外只读运行时目录 |
| `isolation_python` | 隔离辅助程序使用的可信真实 CPython |

```yaml
capabilities:
  execution.binding:
    plugin: sage.execution.binding.local-workspace
    scope: process
    config:
      workspace: /absolute/workspace
      private_workspace_root: /absolute/private-workspaces
      child_workspace_policy: shared_parent
      isolation_python: /absolute/trusted/python3
      command_path: /absolute/media/bin:/usr/bin:/bin
      read_paths: [/absolute/media/runtime]
      policy:
        filesystem:
          max_file_bytes: 536870912
          allowed_operations: [read, list, write, create, delete, rename]
        process:
          enabled: true
          allow_shell: true
          allowed_executables: [bash, sh, python3, ffmpeg]
          max_wall_time_seconds: 7200
          max_output_bytes: 8388608
        resources:
          disk_mb: 32768
          require_hard_limits: false
        network:
          mode: none
          deny_private_networks: true
```

具体字段以 `LocalExecutionBindingConfig` 的 schema 为准。完整可校验的媒体配置见
[英文 SDK 接入文档](../../../sagents/v2/README.md)。
未单独指定更小的文件总量时，显式磁盘额度覆盖旧默认容量。子任务继承父任务已受理策略，
只能缩小授权。只读关系同时限制文件写入与进程写入。共享沙箱使用独立 Run 租约，释放
子任务不会销毁父任务仍使用的资源。

Sage 在受理时保存有效配置，在实际 Run ID 分配后创建沙箱。宿主不自行调用
`provision()`，不模拟隔离辅助程序的内部启动命令。

冻结宿主可分发独立真实 CPython。隔离辅助解释器和 Agent Shell 中的 Python 是两项
配置：后者由 `command_path` 决定。Sage 校验解释器、授权只读路径并负责启动。
诊断报告实际解释器、沙箱标识和限制能力；软计量不能报告为内核硬限制。

## 工具、Skill 和自治能力

工具插件声明 catalog/executor 配对能力；选择必须使用相同插件、名称、参数和作用域。
多个工具提供者使用 `tool.catalog` 列表。`grant_tools: true` 是可信 runtime 对动态
目录的显式授权，插件仍须按实际任务授权筛选；没有该授权时使用 Agent 和命令的工具范围。
Run 插件可声明 `execution.environment` 依赖，以读取真实命令、请求身份和沙箱。
Project/Session 归属不能取自模型提交的参数。

Skill 使用标准 catalog/source、可选 workspace、预加载和激活恢复。上下文处理和
`agent.continuation-policy` 使用相应能力插件；不替换 loop 属性或自行组装 reducer。
`execution.model-budget` 通过工厂注册；多个 App 可以借用同一个进程预算，由创建者
负责关闭。持久父子任务预算与传输超时是不同约束。

外部 MCP 调用默认 7,200 秒，可按服务器配置；超时作为工具结果返回给 Agent。
此设置不限制内部委派、Team 子任务或整个 Run 的工作时长。

## 参考项目和测试

[标准媒体宿主](../../../examples/v2/standard_host/README.md) 演示实际文件、Shell、
FFmpeg、Pillow、MCP、Skill、嵌套 Team 和恢复，并包含 PyInstaller 验证命令。
`examples/v2/host` 演示较小的自定义上下文插件宿主。
Desktop、Server 将产品差异放在对应能力插件中，Agent 执行由 SDK 负责。

SDK 测试位于 `tests/sagents/v2`，应用测试位于 `tests/app/v2`。原生隔离需要平台能力
及进程计量权限；冻结版验证结果必须来自当前源码。

## 设置页查询内置工具元数据

无需创建 App 或 Run，使用公开接口：

```python
from sagents.v2.tool import builtin_tool_definitions

catalog = [
    {"name": value.name, "description": value.description,
     "inputSchema": value.input_schema}
    for value in builtin_tool_definitions(agent_mode="all", language="en")
]
```

返回按名称排序、元数据已深拷贝的 `tuple[ToolDefinition, ...]`，与执行提供者复用同一份声明。查询不创建模型、coordinator、Driver、沙箱或连接，不需要注册执行组件或反射私有类。`language=None` 保留工具的原始文本；传入语言则使用标准本地化投影。`agent_mode` 支持 SDK 的 `AgentMode` 枚举或下表字符串，未知值明确报 `ValueError`，不回退到其他模式。

| agent_mode | 目录内容 |
| --- | --- |
| `simple`、`flow` | 官方基础工具和 `load_skill` |
| `team` | 基础、Skill 和 `sys_team_delegate_task` |
| `fibre` | 基础、Skill、`sys_spawn_agent` 和 `sys_delegate_task` |
| `all` | 上述模式的并集，无重复名称 |

静态目录用于设置与能力说明，不代表特定 Run 已获授权。宿主仍按自身 Agent 授权事实展示可用角色，运行时继续执行原有 Agent、调用边界和工具授权；普通委派叶子不会因目录中列出 Team/Fibre 工具而获得委派能力。MCP、自定义工具及可选宿主管理能力的元数据由对应提供者负责。`official_tool_definitions()` 继续保持仅返回基础工具的原有含义。

宿主的工具目录可用此结果替换基础工具加 Skill/Team 私有反射得到的列表，再合并原 MCP 元数据；保留现有 `agents` 授权展示筛选，不按静态目录重新授予权限。SDK 模式名称为 `simple`，产品的 Single 等名称应由宿主显式映射。

可直接运行 `python -m examples.v2.tool_catalog --agent-mode all --language zh`。验证入口为 `tests/sagents/v2/test_builtin_tool_metadata.py`，涵盖执行提供者 schema 一致性、标准 Simple/Team/Fibre Run 授权、元数据副本隔离和导入/查询无资源分配。

已有 Sage 验证记录：元数据、官方工具、模式、Skill 与导入边界集合 **175 passed**。

## 审批、暂停、取消与提交

状态控制使用公开 `app.runtime` 的 `reply_interaction`、`pause_run`、`cancel_run`、`resume_run` 命令。普通暂停先接受 `ResumeRun`，交互暂停先接受 `ReplyInteraction`，再按原 Run 加载 Agent 并继续。候选会话使用 `app.entrypoint()` 的 `propose_session_commit`、`publish_session_commit`、`reject_session_commit`，以保留原版本和发布后的记忆处理。

已在执行的重复 `continue_run` 只观察现有执行，终态返回现有结果。各宿主实际开放的控制、权限与生命周期边界见[Desktop / Server 控制接口核对](sagents-v2-host-controls.md)。
