# yiii 通过标准 Builder 接入沙箱目录与 Team 共享实例

本次只修改 Sage，未修改 yiii。Builder 的公开调用方式不变；共享通过本地沙箱插件的 Run 租约能力实现。yiii 应使用标准 Builder 装配 Agent，不再自行 provision 子沙箱、创建 Agent loop 或维护租约。

## 工作区与目录

宿主工作区是 Agent 的工作目录，不是操作系统的 `/`。检查当前 yiii 的 `native_runtime.py`，原生执行路径把 `workspace_root` 和 `host_workspace` 设为同一个宿主绝对路径；Project 目录另行传入上下文。因此无需额外的 `/workspace` 字符串替换。

Sage 本地插件创建独立临时目录、Home、缓存、配置、数据和状态目录，设置 `TMPDIR`、`TMP`、`TEMP`、`HOME` 及 `XDG_*` 环境变量。文件工具支持这些目录前缀和 `~/`，返回当前平台 Shell 可使用的规范路径。macOS 使用工作区内真实路径；Linux 使用 `/tmp`、`/var/tmp`、`/home/agent` 等挂载路径。所有存储计入工作区配额。

标准 Builder 自动把 handle 的 `describe_environment()` 投影为 `<sandbox_environment>`，包括 OS、目录、路径规则、资源限制、sandbox_id、lease_owner_run_id 和 shared_instance。yiii 不需要自己注入环境提供器或硬编码内部目录名称。

## Team 的默认共享行为

标准 Builder 对 `mode: team` 且使用默认 `shared_parent` 的成员，从父环境获取独立 Run 租约：

- sandbox_id、实际工作区、Home、临时/缓存目录、进程并发限制及资源监控相同。
- 各成员保留不同的 owner_run_id、签名授权、会话、工具结果、任务和进程归属；不能拿子成员的授权去操作父 Run。
- 成员完成、取消或关闭只撤销自己的租约，清理自己的运行中进程和排队任务。
- 父成员先释放时，仍有租约的子/兄弟成员继续运行；最后一个租约释放才终止公共环境。
- 显式 `private_child` / `read_only_parent` 策略继续走单独的宿主绑定，不被默认共享覆盖。
- 插件不支持共享租约时，标准 Team 装配会明确报不支持，不静默创建另一份沙箱。

本地插件的共享状态不等于共享一份聊天或一套工具权限。资源额度按整个共享实例合计；真实的整体资源故障会报告给相关成员。

## yiii 需要迁移的装配路径

当前 `python/yiii_agent_runtime/native_runtime.py` 虽然已有 Builder 创建的 App，但其 `compose_loop` 还手工调用了 sandbox provision、OfficialToolRuntime、ModeAwareAgentLoopFactory 和 AgentCompositionFactory.create_loop。该自建路径不会自动获得 Builder 的 Team 共享行为；仅升级 Sage 包不够。

把这段自建组合迁回已有公开入口，保持 `build()` / `load_agent()` / `run_stream()` 的使用方式：

```python
from sagents.v2 import SAgentBuilder
from sagents.v2.runtime.execution import LocalWorkspaceExecutionBindingProvider

# SDK 提供通用的本地绑定适配器，无需导入 Desktop application。
# resources、network、issuer、sandbox_provider 等仍按宿主已有配置传入。
bindings = LocalWorkspaceExecutionBindingProvider(
    workspace_root,
    resources=resource_limits,
    network=network_policy,
)

app = await (
    SAgentBuilder()
    .with_models(model_catalog)
    .with_session_store(session_store)
    .with_model_provider_factory(model_provider_factory)
    .with_execution_binding_provider(bindings)  # 已有 Builder API
    .with_additional_tools(mcp_catalog, mcp_executor)  # 已有 Builder API
    .build(runtime=runtime_config)
)

# 先加载成员，再把成员 handle 绑定到 Team 包声明的别名。
worker = await app.load_agent(worker_package)
team = await app.load_agent(team_package, subagents={"worker": worker})
# 使用已有 app.entrypoint().run_stream(command, context, agent=team)。
# command.agent_id=team.id，resolved_spec_hash=team.composition_hash。
```

Team 包配置 `mode: team`、声明 `subagents`；官方工具仍通过现有 `tool.catalog: sage.tool.official` 配置选择。模型、MCP、技能和策略继续从现有 Builder 扩展点及 runtime/plugin config 接入；上面的变量来自 yiii 当前宿主配置。持久化的 Agent revision、模型/工具绑定和恢复配置必须保留，不应在恢复旧 Run 时替换成最新 Project 设置。

如果 yiii 的某项现有能力无法通过这些公开扩展点表达，应在 Sage 中补齐相应配置/插件支持并添加 Builder 回归测试，不恢复自建 loop 路线。关闭 App 后由宿主按既有资源所有权约定关闭 `bindings`；不要由 yiii 子任务直接 destroy 公共沙箱。

## 更新 Agent 提示

更新 `python/yiii_agent_runtime/sage_chat_sections/project_context.py` 的 storage guidance：

- 称工作区为“默认工作目录”，明确它不是 OS root；Project 是另一个明确的路径。
- 以 `<sandbox_environment>` 为目录事实来源；临时文件用 Python tempfile / `$TMPDIR`，Home 用 `$HOME`，缓存和配置使用相应 XDG 变量。
- “宿主与沙箱路径相同”只用于当前 identity workspace，不扩展为所有平台的所有路径通则。
- 发生工具错误时读取原始异常、资源用量/限额、恢复结果和可用能力，继续使用可用工具；中断命令可能已有部分产物，先检查，不自动重放。

## 哪些路径转换可以删除

| 场景 | 处理 |
| --- | --- |
| 宿主目录与 workspace_root 相同 | 不需要额外转换；仍保留工作区和 allowed roots 配置以授权及隔离 |
| macOS 文件工具返回的规范绝对路径 | 可直接传给 Shell，无需替换 `/workspace` |
| 临时目录、Home、缓存的文件工具/Shell 互通 | 使用插件提供的环境变量/规范路径，yiii 不维护映射 |
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
