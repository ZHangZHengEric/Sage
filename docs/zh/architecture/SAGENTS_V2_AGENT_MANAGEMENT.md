---
layout: default
title: Agent 包管理
parent: 架构
nav_order: 3
lang: zh
ref: v2-detail-SAGENTS_V2_AGENT_MANAGEMENT
---

{% include lang_switcher.html %}

# v2 Agent 包管理

Agent 包把提示词、模型选择、工具、Skills 和流程放在一起，保存为可复用的版本。`AgentManagementService` 负责校验、保存、选用版本和启动任务；用户身份、密钥和允许使用的资源仍由接入它的应用（宿主）决定。

例如，保存新版本后，可以先单独测试，再把它设为活动版本。已经开始的任务继续使用原版本，不会在执行中途切换配置。本文面向需要接入这套管理能力的开发者；通过 Web 使用时先看 [Server Agent 平台](SERVER_V2_AGENT_PLATFORM.md)。

## 定义与公共接口

`AgentManagementService` 使用原生 `SageManifest` 创建、验证、保存并运行 Agent 包，不另造简化配置。包可以配置 Simple / Fibre / Team、成员、Flow、工具、Skill、记忆、模型、预算和指令文件；具体能力仍需要宿主绑定 provider。创建出的 Agent 只有获得管理工具及宿主授权，才能继续创建其他 Agent。它不改变 Fibre 轻量 `sys_spawn_agent` 的叶子工作者语义。

从 `sagents.v2` 导入：

- `AgentPackageBundle`：`manifest: SageManifest` 和 `files: dict[str, str]`。
- `AgentManagementService`：验证、保存、读取、分叉、激活版本和 Native Run 执行。
- `AgentPackageStore`：默认 SQLite 版本库存与调用索引；Server 使用自己的 MySQL 仓储。

配置与文件内容产生不可变 ref。运行绑定确切 ref；活动指针变化不会修改已经运行的任务。保存和激活不是专业能力通过评测的证明，也不包含自动评分或学习晋升闭环。

## 管理工具

通过 `SAgentBuilder.with_agent_management(service)` 注入服务，在 Agent 的 `tools` 中显式选择工具；注入本身不授予所有 Agent 权限。

| 工具 | 作用 |
| --- | --- |
| `agent_package_schema` | 完整 bundle Schema 与宿主插件目录 |
| `agent_package_list` | 分页版本库存及活动标记 |
| `agent_package_get` | 读取完整定义和文件 |
| `agent_package_validate` | Schema、引用、装配与可选资源就绪检查 |
| `agent_package_save` | 保存不可变版本 |
| `agent_package_fork` | 复制为新的包 ID / 版本 |
| `agent_package_activate` | expected_ref 比较切换或回退活动版本 |
| `agent_package_run` | 启动任务或续接该版本的 Session |
| `agent_package_status` | 状态、结果与待处理交互 |
| `agent_package_reply` | 携 interaction_id 回答 user_input / elicitation，不能代答宿主审批或凭据交互 |
| `agent_package_cancel` | 通过 Native Runtime 取消 |

## 宿主接入与生命周期

```python
service = AgentManagementService(
    root="runtime/managed-agents",
    builder_factory=build_managed_agent,
    authorize=authorize_package,
    inventory=plugin_inventory,
    max_applications=32,
    max_concurrent_builds=4,
    auto_release_idle_seconds=300,
)
```

这是接入片段，回调由宿主实现。异步 `authorize(action, bundle, context)` 成功返回 None，拒绝时抛错。它检查模型、凭据引用、插件、工具、预算、路径与外部连接，在加载插件前及后续运行、控制和激活时执行。授权不等于每次人工询问；交互仍由 ToolPolicy 决定。

`builder_factory(bundle, session_root, context)` 同步或异步返回一个新的 Builder：使用按用户/包/Agent 划分的持久 session_root，注入模型、记忆、工具及真实 Run 沙箱绑定，注册已准入插件。Skill 接入使用 `with_skill_provider(catalog, source, workspace)`，并要求 Agent 的 Skill 选择、load_skill 授权与调用者的 `skill.load` scope。允许进一步创建 Agent 时，显式注入管理服务和管理工具。

服务调用 `builder.build(..., agent_id=...)`。不要共享可变 Builder 或所有权不明的客户端。验证在独立临时目录装配；关闭失败保留 Application 与目录，进入 draining 并拒绝新操作，以便再次 close 清理。

服务由宿主持有和关闭，不能被某个子 Application 关闭。`max_applications` 限制驻留实例及构建占位，`max_concurrent_builds` 默认 4，验证资源关闭后才释放构建名额。容量满时默认尝试回收闲置 300 秒、可持久恢复且无非终态任务的实例；设 `auto_release_idle_seconds=None` 关闭。没有后台定时回收。详见[资源管理](SAGENTS_V2_RESOURCE_MANAGEMENT.md)。

## 插件与 Flow

标准 [ExtensionRegistration](https://github.com/ZHangZHengEric/Sage/blob/main/sagents/v2/runtime/extensions/contracts.py) 声明 ID、版本、API、配置 Schema、依赖、作用域、factory 与生命周期 hooks。通过 `sage.extensions` 显式发现，或 `builder.register(registration)` 注册。缺失声明、版本冲突、无效配置及未绑定节点明确失败。

`runtime.capabilities["flow.node"]` 选择标准节点，或用 `with_flow_tool_nodes` 绑定宿主 `RunnableNode`。接口为 `RunnableNode.run(FlowNodeContext) -> FlowNodeResult`。Builder 支持 process / tenant / agent scope 的节点，Run scope 需要专用 driver。Agent 的 `entrypoint.type: flow` 接入 FlowRuntime。

Flow agent 节点使用 Native 子 Run，前序输出作为后续任务数据；嵌套流程用 subflow。Builder 拒绝递归 Flow agent 和未实现的自定义 loop。interaction 节点可选择 user_input，默认 approval，两者权限边界不同。完成输出写入 `flow.completed.output`，管理服务以 `flow_results` 返回。

源码插件放在 `files["extensions/<plugin_id>.py"]`，必须在 manifest.plugins 显式声明，并导出名为 registration 的标准对象（API version 2）。源码参与版本哈希，不得冒充 built-in 或覆盖宿主注册项。宿主必须设置 `allow_source_plugins=True`，并批准 `authorize("load_source_plugin", bundle, context)`；built_in_only 策略拒绝加载。

源码在宿主 Python 进程执行，验证与模块初始化也会执行代码。语法和接口检查不是隔离；不提供自动依赖安装、隔离构建或非可信代码沙箱。模块由 Application 持有，插件关闭后移除；失败加载会清理。

## 版本、幂等与恢复

- 库存按 tenant ID 与 principal ID 隔离，不接受用户文件路径作为包定位器。
- 相同 ID / version 只能保存相同内容。普通重复保存返回 `reused=True`，重新检查授权但复用验证；严格 `require_readiness=True` 模式会重新验证宿主资源。
- activate 要求 expected_ref 匹配，首次激活传空值。run 的 operation key 在调用者范围唯一；重试须保持 ref、agent、输入与 Session 相同。
- 先持久记录调用意图，再 Native 幂等接纳；中断后使用相同 operation 重试。续接仅限同一调用者、ref、Agent 的 Session，不隐式跨版本迁移。
- 暂停返回交互，不冒充终态。reply 必须传 interaction_id；相同 ID、decision、payload 可幂等重试，不将旧回答用于新问题。revision 冲突后的未接受回复可重新读取 revision 重试。
- 保存与验证对输入取快照，文件和提示词保留首尾空白。bundle 最多 256 个文本文件、合计序列化大小 4 MiB；拒绝绝对路径、路径穿越、反斜杠和覆盖 sage.yaml。
- 已归档终态可在不构建 Application 的情况下读取，仍检查当前 read_run 授权。内置文件存储支持只读冷恢复；未终态和不支持离线读取的存储仍需恢复装配。

当前是单进程执行管理。SQLite 或 MySQL 事务不等于分布式 worker 调度；跨租户共享、跨版本会话迁移和业务质量验收仍由宿主设计。

## 示例与验证

在 Python 3.12+ 项目环境运行：

```bash
python -m examples.sagents_v2_agent_management
python -m examples.sagents_v2_source_plugin
python -m pytest tests/sagents/v2/test_agent_management_matrix.py
```

示例使用脚本化模型，经过工具调用、保存、Builder 装配与 Native Run，不访问模型 API，也不证明模型质量。测试覆盖版本冲突、隔离、幂等、续接、Flow、Skill、交互和失败清理；原生平台及真实模型测试仍需独立执行。

Server 的 `/studio` 和 `/api/agent-packages` 接入完整包平台；Desktop 普通 Agent 编辑与多成员 Studio 不等于完整包版本管理。

实现入口：[service.py](https://github.com/ZHangZHengEric/Sage/blob/main/sagents/v2/agent/management/service.py)。
