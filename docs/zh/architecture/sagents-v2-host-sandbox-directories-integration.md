---
layout: default
title: 宿主沙箱接入
parent: 架构
nav_order: 16
lang: zh
ref: v2-detail-sagents-v2-host-sandbox-directories-integration
---

{% include lang_switcher.html %}

# 宿主通过标准 Builder 接入沙箱目录与 Team 共享实例

公开调用链为 `register → build → load_agent → run_stream`，共享通过本地沙箱插件的 Run 租约能力实现。宿主使用标准 Builder 装配 Agent，不再自行 provision 子沙箱、创建 Agent loop 或维护租约。

## 工作区与目录

宿主工作区是 Agent 的工作目录，不是操作系统的 `/`。当 `workspace_root` 和 `host_workspace` 指向同一个宿主绝对路径时，无需额外的 `/workspace` 字符串替换。Project 目录另行传入上下文；其他隔离布局仍按各自规则解析路径。

Sage 本地插件创建独立临时目录、Home、缓存、配置、数据和状态目录，设置 `TMPDIR`、`TMP`、`TEMP`、`HOME` 及 `XDG_*` 环境变量。文件工具支持这些目录前缀和 `~/`，返回当前平台 Shell 可使用的规范路径。macOS 使用工作区内真实路径；Linux 使用 `/tmp`、`/var/tmp`、`/home/agent` 等挂载路径。所有存储计入工作区配额。

标准 Builder 自动把 handle 的 `describe_environment()` 投影为 `<sandbox_environment>`，包括 OS、目录、路径规则、资源限制、sandbox_id、lease_owner_run_id 和 shared_instance。宿主不需要自己注入环境提供器或硬编码内部目录名称。

## Team 的默认共享行为

标准 Builder 对 `mode: team` 且使用默认 `shared_parent` 的成员，从父环境获取独立 Run 租约：

- sandbox_id、实际工作区、Home、临时/缓存目录、进程并发限制及资源监控相同。
- 各成员保留不同的 owner_run_id、签名授权、会话、工具结果、任务和进程归属；不能拿子成员的授权去操作父 Run。
- 成员完成、取消或关闭只撤销自己的租约，清理自己的运行中进程和排队任务。
- 父成员先释放时，仍有租约的子/兄弟成员继续运行；最后一个租约释放才终止公共环境。
- 显式 `private_child` / `read_only_parent` 策略继续走单独的宿主绑定，不被默认共享覆盖。
- 插件不支持共享租约时，标准 Team 装配会明确报不支持，不静默创建另一份沙箱。

本地插件的共享状态不等于共享一份聊天或一套工具权限。资源额度按整个共享实例合计；真实的整体资源故障会报告给相关成员。

## 显式嵌套 Team（标准行为，无额外参数）

`root(team) → director(team) → maker(simple)` 使用相同的公开 API，逐层绑定声明的成员：

```python
maker = await app.load_agent(maker_package)
director = await app.load_agent(director_package, subagents={"maker": maker})
root = await app.load_agent(root_package, subagents={"director": director})
# root_package: mode=team, subagents=("director",)
# director_package: mode=team, subagents=("maker",)
# maker_package: mode=simple
# 照常使用 app.entrypoint().run_stream(command, context, agent=root)。
```

Builder 会递归装配冻结图里的全部模型与组件，各层保留自己的工具、技能、preload 和模型选择。root 的 roster 只有 director；director 的 roster 使用本层别名 maker，持久化身份为 director.maker。root 无权绕过 director 直接委派 maker，director 无权委派 root 的其他成员；普通委派叶子不会获得递归委派权限。

每层显式 Team 都有自己的委派控制器，最深层交互逐层传到根。扩展清单中的无序 scope 集合会排序后参与恢复指纹，避免不同 Python 进程误判 composition 变化。恢复旧 Run 时使用 `await app.agent_for_run(run_id, context)` 得到原 revision，再通过公开 Interaction 回复和 `continue_run(..., agent=restored)` 继续；不要把最新 load/update 返回的 handle 替换进旧 Run。

默认 shared_parent 从**当前父层的实际环境**取得独立租约，因此嵌套层会保留父层已有的私有或只读边界。中间层释放自己的租约不撤销其他成员。等待子任务的 Team 暂时归还执行并发额度，避免多个中间 Team 占满额度后，最深层任务永远无法启动。

嵌套 Team 使用上述公开链路，无需额外配置，也无需宿主自行创建 loop、provision 沙箱或管理租约。

Sage 回归覆盖越权 roster 拒绝、独立模型绑定与技能 preload、并行嵌套、租约释放、私有/只读边界、跨 Python 进程暂停恢复，见 `tests/sagents/v2/test_builder_*.py`。

## Goal / Plan 完成门与宿主 continuation 插件

标准 Builder 继续通过公开 `agent.continuation-policy` capability 接入宿主策略，无需宿主自建 loop 或新增完成门扩展点。

Goal 未完成或 Plan 尚未成功提交时，已有的 `CONTINUE_STEP`、`FAIL`、`REQUEST_INTERACTION` 决策原样通过，保留 reason_code、reason、metadata 和 usage。完成门仍将提前结束请求（COMPLETE_RUN / COMPLETE_TURN / HANDOFF）改为继续执行，并保留宿主 metadata 与 usage；Goal 的 `goal_complete`、Plan 的用户批准提交及最终说明要求不变。

宿主恢复标记（例如 `metadata.host_autonomous_replan`）持久化到 `continuation.decided.data.details`，计费用量进入 `usage.recorded`。恢复次数应从原 Run 的规范事件累计，避免上下文缩减或进程重启重置次数。现有 `judge.continue` 的恢复指导会按原机制进入下一次模型请求。

Sage 公开 Builder 回归覆盖真实 `goal_submit`、连续三次自主恢复、Goal 与 Plan 跨 Python 进程恢复后的计数，以及完成门拒绝提前完成并在成功提交/完成后正常结束。

## 宿主的标准装配路径

宿主通过 `builder.register(registration)` 注册自定义能力实现，并在 runtime 配置中选择插件 ID、scope 和可序列化参数。模型通过 `build(models=...)` 传入；宿主对象同样通过明确资源所有权的注册工厂提供。

通过已有公开入口执行 `build()` / `load_agent()` / `run_stream()`：

```python
from sagents.v2 import SAgentBuilder

builder = SAgentBuilder()
for registration in host_registrations:
    builder.register(registration)
app = await builder.build(runtime=runtime_config, models=model_catalog)
worker = await app.load_agent(worker_package)
team = await app.load_agent(team_package, subagents={"worker": worker})
# command.agent_id=team.id，resolved_spec_hash=team.composition_hash。
stream = await app.entrypoint().run_stream(command, context, agent=team)
```

Team 包配置 `mode: team`、声明 `subagents`；官方工具仍通过现有 `tool.provider: sage.tool.official` 配置选择。模型、MCP、技能和策略继续从统一注册能力及 runtime/plugin config 接入；上面的变量由宿主配置提供。持久化的 Agent revision、模型/工具绑定和恢复配置必须保留，不应在恢复旧 Run 时替换成最新 Project 设置。

如果宿主的某项现有能力无法通过这些公开扩展点表达，应在 Sage 中补齐相应配置/插件支持并添加 Builder 回归测试，不恢复自建 loop 路线。关闭 App 后由宿主按既有资源所有权约定关闭 `bindings`；不要由子任务直接 destroy 公共沙箱。

## 更新 Agent 提示

宿主提供的 Agent 提示应按以下规则描述存储：

- 称工作区为“默认工作目录”，明确它不是 OS root；Project 是另一个明确的路径。
- 以 `<sandbox_environment>` 为目录事实来源；临时文件用 Python tempfile / `$TMPDIR`，Home 用 `$HOME`，缓存和配置使用相应 XDG 变量。
- “宿主与沙箱路径相同”只用于当前 identity workspace，不扩展为所有平台的所有路径通则。
- 发生工具错误时读取原始异常、资源用量/限额、恢复结果和可用能力，继续使用可用工具；中断命令可能已有部分产物，先检查，不自动重放。

## 哪些路径转换可以删除

| 场景 | 处理 |
| --- | --- |
| 宿主目录与 workspace_root 相同 | 不需要额外转换；仍保留工作区和 allowed roots 配置以授权及隔离 |
| macOS 文件工具返回的规范绝对路径 | 可直接传给 Shell，无需替换 `/workspace` |
| 临时目录、Home、缓存的文件工具/Shell 互通 | 使用插件提供的环境变量/规范路径，宿主不维护映射 |
| Linux 虚拟路径与宿主目录不同 | 跨到宿主 MCP 时仍需明确解析，不能原样当宿主路径 |
| Project 相对路径、附件、预览、产物下载 | 保留各自的路径解析和授权，它们不是冗余的工作区映射 |

不要全局替换 Shell 字符串中的 `/tmp`、`~` 或 `/workspace`；只在明确的路径字段处理必要的跨边界转换。

## 本机能力与环境变量

沙箱 HOME/TMPDIR/XDG 只改变默认配置、缓存、临时文件的读写位置，不撤销已有宿主授权。用户电脑能否访问仍取决于执行插件、文件/网络策略、宿主允许的只读运行时目录以及 MCP/电脑控制等工具权限。当前本地文件工具仍限制在工作区内；Shell 只按平台策略访问系统路径。需要读宿主配置时应显式授权/配置实际路径，不能通过把 HOME 改回宿主目录隐式扩大权限。

## 验收

1. 通过标准 Builder 驱动真实 Team 委派，父子模型请求中的 sandbox_id 相同、lease_owner_run_id 不同，初始工作区相同。
2. 子任务完成后父任务能继续读写；父、子、兄弟成员并发时关闭其中一个，不终止其他成员的进程。
3. 子任务排队时关闭该成员，排队命令永不执行；最后一个租约释放才关闭实例。
4. Shell 与文件工具能互读 Home/TMPDIR/缓存文件，跨工作区路径和符号链接仍被拒绝。
5. 同 Project 的独立顶层任务不会仅因目录相同就共享实例；共享只来自明确的父子 Team 关系。
