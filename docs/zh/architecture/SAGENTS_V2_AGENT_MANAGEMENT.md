---
layout: default
title: Agent 包管理
parent: 架构
nav_order: 3
lang: zh
ref: v2-detail-SAGENTS_V2_AGENT_MANAGEMENT
---

{% include lang_switcher.html %}

# SAgents V2：Agent 自定义 Agent 的实现与接入

更新：2026-09-13。本文描述本次新增的运行时能力；它是 RSI 的能力建设基础，不包含自动评分、学习策略搜索或监督晋升闭环。

## 1. 本次实现

新增 `AgentManagementService` 和模型可调用的 Agent Package 工具。创建对象直接使用现有 `SageManifest`，不另造一份简化 Agent 配置。

这条链路已经贯通：

```text
读取完整 schema / 插件目录
  → 保存完整配置与随包文件
  → 验证各 Agent 的装配
  → 得到不可变内容引用 ref
  → 启动指定 Agent
  → 查询结果 / 回答提问 / 继续同一会话
  → 保存新版本 / 分叉 / 切换与回退活动版本
```

被创建的 Agent 如果也获得管理工具及宿主授权，可以继续创建其他 Agent。该机制独立于 Fibre 的轻量 `sys_spawn_agent`，不改变旧委派接口的叶子工作者语义。

### 可以自定义的范围

| 配置 | 创建与运行行为 |
| --- | --- |
| 指令与指令文件 | 支持 inline 或随包 `files` 中的 path；不从任意宿主路径读取指令 |
| 模型路由、采样参数和模型限制 | 使用现有 models / request / limits schema，由 Builder 装配；宿主可注入模型提供者 |
| Simple / Fibre / Team | 使用现有模式实现，成员关系由包配置定义 |
| 工具、技能、记忆与预算 | 保存完整配置，并沿用现有授权和预算执行机制；具体能力需要宿主绑定 provider |
| Flow 入口 | Builder 现在将 Agent 的 `entrypoint.type: flow` 接到 FlowRuntime |
| 工具插件 | 通过现有 ExtensionRegistration、声明版本和配置选择已提供的插件 |
| 自定义 Flow 节点 | 通过 `runtime.capabilities["flow.node"]` 选择标准插件，或由宿主注入 RunnableNode |
| 新版本与跨会话复用 | 包存储独立于会话；使用确切 ref 调用，跨重启读取和续接 |

宿主拥有的凭据、沙箱、资源额度和插件准入不由新包自行扩大。授权检查由宿主回调执行，不等于每次必须向用户提问；宿主仍按现有 ToolPolicy 决定交互方式。

## 2. 公共接口与工具

从 `sagents.v2` 可以导入：

- `AgentPackageBundle`：`manifest: SageManifest` 和 `files: dict[str, str]`。
- `AgentManagementService`：验证、保存、读取、分叉、活动版本切换和 Native Run 执行。
- `AgentPackageStore`：SQLite 库存、不可变版本和调用索引。

通过 `SAgentBuilder.with_agent_management(service)` 注入工具，再在对应 agent 的 `tools` 字段中显式选择要开放的名称。仅注入服务不会自动给所有 agent 授权。

| 工具 | 用途 |
| --- | --- |
| `agent_package_schema` | 获取完整 bundle JSON Schema 和宿主提供的插件目录 |
| `agent_package_list` | 分页读取当前用户的版本库存和活动标记 |
| `agent_package_get` | 读取一个版本的完整配置和文件 |
| `agent_package_validate` | 检查 schema、引用及各 Agent 的 provider 初始化 |
| `agent_package_save` | 创建版本；修改已有配置时使用新的版本号 |
| `agent_package_fork` | 从已存在版本复制到指定包 ID / 版本 |
| `agent_package_activate` | CAS 切换活动版本；也可回退到旧 ref |
| `agent_package_run` | 异步启动任务，或续接该版本的已有 Session |
| `agent_package_status` | 查询状态、最终结果和待处理交互 |
| `agent_package_reply` | 携带 status 中的 interaction_id 回答 user_input / elicitation；宿主审批与凭据交互不在此处代答 |
| `agent_package_cancel` | 通过 Native Runtime 取消任务 |

保存或激活只表示配置与装配可用，不表示专业能力已经通过评测。运行使用确切 ref，不随活动指针变化而偷偷换版。

## 3. 宿主接入约定

`AgentManagementService` 接收两个必需的宿主回调：

```python
service = AgentManagementService(
    root="runtime/managed-agents",
    builder_factory=build_managed_agent,
    authorize=authorize_package,
    inventory=plugin_inventory,
    max_applications=32,
)
```

`authorize(action, bundle, context)` 是异步函数，成功返回 None，拒绝则抛出异常。必须检查该用户可使用的模型路由、凭据引用、插件、工具、资源与预算，以及插件配置中的路径和外部连接。检查发生在插件加载前，并在运行、控制及版本激活时再次执行。不要在生产中用无条件允许的回调代替宿主授权。

`builder_factory(bundle, session_root, context)` 返回一个新的 `SAgentBuilder`，也可以异步返回。它应：

1. 用传入的 `session_root` 配置持久 Session 存储；该路径已经按用户、包内容和 Agent 区分。
2. 注入或配置该用户的模型、记忆、工具和真实 Run 沙箱绑定。
3. 注册已经准入的标准插件；让包中的 plugin 配置参与正常装配。
4. 需要技能时调用 `with_skill_provider(catalog, source, workspace)`；技能遵循每个 Agent 的 skills 列表和 `load_skill` 工具授权，调用者还需 `skill.load` scope。
5. 允许下一层创建能力时注入同一个管理服务，并只向获得相应授权的 Agent 开放管理工具。

服务负责调用 `builder.build(..., agent_id=...)`。工厂不能返回共享的可变 Builder 或共享所有者不明的客户端。验证会在独立临时目录中装配，避免碰到正在运行的版本存储。

管理服务由宿主统一持有和关闭，不能由它创建的某个子 Application 关闭。先收拢或取消运行中的任务，再关闭宿主 Application 和管理服务。关闭失败的 Application 会被保留，以便重试清理。

当前实现面向单进程宿主；SQLite 版本写入有事务与冲突检查，但不因此宣称整个执行层具备分布式 worker 调度能力。`max_applications` 是同时驻留的版本/Agent 装配数上限，可由宿主调整；目前没有自动空闲淘汰。`max_concurrent_builds` 默认 4，统一限制本服务的验证与运行初始化并发，验证资源关闭后才释放名额。

## 4. 标准插件与流程节点

沿用 [Extension 契约](https://github.com/ZHangZHengEric/Sage/blob/main/sagents/v2/runtime/extensions/contracts.py)：

- Descriptor 声明 plugin ID、版本、API 版本、能力、配置 schema、依赖和作用域。
- Registration 提供 factory 与生命周期 hooks。
- 已安装 Python 包通过 `sage.extensions` entry point 被显式发现；也可由宿主 `builder.register(registration)`。
- 声明缺失、版本不兼容、配置错误或未绑定节点会失败，不静默替换成其他实现。

例如一个标准插件提供 `flow.node:calculate`，manifest 可以写：

```yaml
plugins:
  - id: example.calculate
    version: "1.0.0"
runtime:
  capabilities:
    flow.node:
      plugin: example.calculate
      name: calculate
      config:
        precision: 4
agents:
  analyst:
    name: Analyst
    instructions:
      inline: Complete the analysis flow.
    models:
      primary: primary
    entrypoint:
      type: flow
      flow: analysis
flows:
  analysis:
    version: "1"
    start: calculate
    nodes:
      - id: calculate
        type: tool
        tool: calculate
        config:
          expression: "6 * 7"
      - id: end
        type: end
    edges:
      - from: calculate
        to: end
```

以上是配置片段，需与 metadata、models、entrypoint 等完整包字段合并。插件的节点实现遵循 `RunnableNode.run(FlowNodeContext) -> FlowNodeResult`。Builder 的插件节点装配支持 process / tenant / agent scope；Run scope 插件节点需要宿主专用 driver。也可用 `with_flow_tool_nodes({"calculate": node})` 显式绑定宿主节点。

Flow 的 agent 节点使用 Native 子 Run；前序节点结果会作为任务数据传给后续 agent。需要嵌套流程时使用 `subflow`，当前 Builder 明确拒绝 Flow agent 递归嵌套及未实现的自定义 loop，而不会忽略这些设置。

Flow interaction 节点可配置 `interaction_type: user_input`，默认仍为 approval。两者保持不同的交互边界。

### 授权源码插件的标准接入

Bundle 的 `files["extensions/<plugin_id>.py"]` 可提供 manifest.plugins 中显式声明的源码插件。文件内容参与包版本哈希。模块必须导出名为 `registration` 的标准 `ExtensionRegistration`，声明 ID、API version 2 和兼容版本；不得冒充 built-in 或替换宿主已注册插件。插件仍通过 capabilities 和正常 Builder 生命周期接入流程，不另建插件接口。

宿主必须显式设置 `AgentManagementService(..., allow_source_plugins=True)`，并在 `authorize("load_source_plugin", bundle, context)` 中批准具体包。`built_in_only` 策略拒绝加载。默认关闭；schema 返回此能力是否开启。语法编译、导出契约和版本校验失败时拒绝保存，清理加载模块；成功时模块生命周期归属于 Application，插件关闭后再移除模块。

**源码插件是可信宿主 Python 扩展，具有宿主进程权限。** 授权须检查内容与来源；模块初始化和验证会执行代码，接口校验不等于安全隔离。当前不自动安装依赖、不提供隔离构建 worker 或非可信源码沙箱。未准入源码不能通过此接口试运行。依赖由宿主预先提供。

[源码插件离线示例](https://github.com/ZHangZHengEric/Sage/blob/main/examples/sagents_v2_source_plugin.py)可用 `python3.12 -m examples.sagents_v2_source_plugin` 运行。端到端回归包括源码 Flow 节点编译、注册、包保存、实际运行、结果读取，以及错误源码清理和授权拒绝。Desktop V2 的普通 Agent 编辑页不默认开放此能力。

## 5. 持久化、并发与多轮语义

- SQLite 库存按 tenant ID 与 principal ID 的组合隔离，不使用用户提供的文件路径定位包。
- 相同 ID / version 只接受完全相同的内容。配置或文件改变必须保存新版本；ref 覆盖完整 manifest 与文件内容。
- 相同版本的重复保存返回 `reused: true`，仍检查当前授权但不重复初始化插件；并发重复保存只装配一次。需要重新检查当前模型/插件是否可用时调用 `validate`。新保存返回 `reused: false`。
- `activate` 要求 expected_ref 匹配当前指针，避免并发覆盖；首次激活传空值。
- `run` 的 operation key 在调用者范围内唯一。重试必须保持 ref、agent、内容和 Session 不变；改变参数将报冲突。
- 调用前持久记录意图，再调用 Native 幂等 admission；中途崩溃可使用相同操作重试。
- 续接仅允许同一调用者、同一 ref、同一 agent 的 Session。升级版本不会隐式迁移旧会话。
- `status` 对未终结任务不读取尚未生成的最终结果；暂停时返回交互详情。
- `reply` 必须传入交互详情中的 `interaction_id`。已接受回复可使用相同 ID、decision、payload 幂等重试；不会把旧答案应用到下一轮问题。回复命令先持久化，支持在接受回复后、恢复执行前中断的重试。若提交因 revision conflict 被拒绝，下次相同答案重试会重新读取当前 revision；已经接受的回复保留原始幂等记录。
- 保存与验证使用输入快照；资源文件和提示词保留首尾空白。
- 失效授权在后续执行前重新检查；不能通过历史已保存版本绕过宿主当前策略。
- Bundle 限制 256 个文本文件、合计序列化大小 4 MiB；拒绝绝对路径、路径穿越、反斜杠和覆盖 `sage.yaml`。

业务验收、自动迭代停止条件、跨版本会话迁移、跨租户共享和分布式调度不在本次新增服务的承诺内。

## 6. 可运行示例与测试

仓库根目录执行（Python 3.12+，已安装项目基础依赖）：

```bash
python3.12 -m examples.sagents_v2_agent_management
```

[离线示例](https://github.com/ZHangZHengEric/Sage/blob/main/examples/sagents_v2_agent_management.py)使用脚本化模型，真实经过模型工具调用、包保存、Builder 装配和 Native Run，展示父 Agent 创建并调用单位换算 Agent。示例不访问模型 API、不消耗推理额度，不作为模型能力提升证据。

[专项测试](https://github.com/ZHangZHengEric/Sage/blob/main/tests/sagents/v2/test_agent_management_matrix.py)覆盖完整创建执行、会话续接与重启恢复、版本冲突、并发写入、租户隔离、幂等调用、父模型实际调用管理工具、标准插件配置、Flow 节点绑定、技能加载、多轮提问恢复、审批边界以及已创建 Agent 再创建其他 Agent。

Flow 完成时将节点结果提交到 `flow.completed.output`，管理服务通过 `flow_results` 返回；专项测试验证自定义节点的输出在重启后仍可读取。

2026-09-13 追加核对：Agent Management 专项 **33 项通过**；V2 回归为 **2092 passed、19 skipped、1 deselected**，Desktop V2 Python 宿主回归 **168 项通过**。运行时另排除了 `test_local_sandbox_resource_limits.py` 和 `test_local_workspace_sandbox_matrix.py` 两个文件，deselect 的用例为 `test_shell_and_todo_tools_use_v2_runtime_state`。这些原生沙箱测试受外层执行环境限制，不能将排除项计为通过。离线示例、Ruff 检查与 `git diff --check` 通过；未运行真实模型质量评测。

并发正确性场景与未覆盖边界详见 [单机并发与定制可用性核对](https://github.com/ZHangZHengEric/Sage/blob/main/docs/archive/zh/architecture/SAGENTS_V2_RELIABILITY.md)。

运行时嵌入仍需宿主注入管理服务与工具授权。Server v2 已通过 `/studio` 和 `/api/agent-packages` 接入完整包平台；Desktop 普通 Agent 编辑器与多成员 Studio 不等同于完整包版本管理。产品接入复用同一管理服务。

## 追加：设置事务与失败清理

验证实例关闭失败时，管理服务保留 Application 与临时目录，后续 close 可重试。服务关闭或验证清理失败后保持 draining，拒绝新管理操作；清理失败不会恢复运行准入。新增两项故障注入回归，专项共 33 项。

Desktop V2 使用串行字段 PATCH 与单服务事务锁保护设置，关闭前提交工作区、预览与沙箱输入；Agent 失败回滚使用已确认快照。该阶段 sidecar revision 为 6（当前为 7）。后端 168 项、Flutter 202 项、核心 2092 项通过；原生沙箱排除范围不变。实现和剩余边界见 [整体审查](https://github.com/ZHangZHengEric/Sage/blob/main/docs/archive/zh/architecture/V2_COMPREHENSIVE_REVIEW.md)。

## 追加：运行时资源管理

已新增可选资源发现及严格准入、共享模型调用额度、显式空闲实例回收、Flow 可达成员装配。Desktop V2 的运行模型已共享额度。接入方式、测试与尚未覆盖的预算和产品流程详见 [运行时资源管理](SAGENTS_V2_RESOURCE_MANAGEMENT.md)。此前“没有回收”“全局模型额度待实现”等描述的当前状态以此文档为准；容量触发自动回收现已实现；全部资源的统一预算仍未实现。

## 追加：容量回收与历史读取

管理操作现在持有实例使用计数；缓存满时默认回收 300 秒未使用、可持久恢复且无非终态 Run 的实例。`auto_release_idle_seconds=None` 可关闭自动回收。终态结果在查询、回收前及正常关闭前归档，已归档查询无需重新构建 Application，且仍检查当前读取授权。内置文件存储的未归档终态现可只读加载；未终态、旧记录无存储位置或第三方存储仍走恢复装配路径。当前机制替代此前“自动回收尚未实现”的描述，详见 [运行时资源管理](SAGENTS_V2_RESOURCE_MANAGEMENT.md)。
