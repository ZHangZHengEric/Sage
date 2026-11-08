---
layout: default
title: 工具、Skills 与 MCP
nav_order: 6
lang: zh
ref: v2-MCP_SERVERS
---

{% include lang_switcher.html %}

# 工具、Skills 与 MCP

| 能力 | 用途 |
| --- | --- |
| 内置工具 | 通过 v2 catalog/executor 提供文件、进程、规划等运行操作。 |
| Skills | 可复用的指令和资源，由 Skill provider 发现与加载。 |
| MCP | 外部服务，发现的工具由宿主接入工具 catalog。 |

## Desktop

在 Agent 中配置工具与 Skills，在设置中添加 MCP 连接。启用的连接会在 catalog/运行组合阶段发现工具，失败会明确报告。`load_skill` 激活相应资源；选择 Skill 不代表完整内容已经进入模型上下文。

## Server

通过 Web 界面管理模型、Agent、Skill 和 MCP。Skills 支持 ZIP 上传及按 Agent 选择。MCP 管理使用 `/api/mcp`，刷新连接可重新发现工具。详见 [HTTP API](api/HTTP_API_REFERENCE.md)。

Server MCP 只接受 `sse` 和 `streamable_http`，拒绝租户 `stdio` 命令；Desktop 可以使用 stdio。Skill 列表完整保留描述，包括多行 YAML；只有加载后的活跃 Skill 内容有独立 token 预算。完整列表仍计入上下文总预算。

## 嵌入式宿主

最小示例有意不启用文件或 Shell 工具。Official tools 需要宿主提供 `OfficialToolRuntime` 和明确的工作区、沙箱绑定。工具执行必须在资源边界校验 grant。内存 manifest 本身不授权任意本机文件访问。

通过[集成手册](https://github.com/ZHangZHengEric/Sage/blob/main/sagents/v2/使用手册.md)选择 catalog、executor、Skill 来源和策略 provider。`mcp_servers/` 中也有面向旧应用的集成，目录存在不代表 v2 自动启用它们。

## v2 远端 MCP 鉴权

本节对应当前 `sagents/v2` 与 `app/v2` 源码，要求 Python 3.12+。请使用所选宿主的说明；v1 配置或旧版 Desktop 安装包不能证明支持这些 v2 入口。

### 连接与凭据

对于使用 Bearer 鉴权的服务，在 Desktop 的设置 → MCP 连接对话框或 Server 的 MCP 管理中填写：

| 设置 | 示例 | 含义 |
| --- | --- | --- |
| 名称 | `remote` | 本连接的名称。 |
| 协议 | `streamable_http` | 使用 Streamable HTTP，而不是 stdio 或 SSE。 |
| URL | `https://mcp.example.com/mcp` | 替换为服务的实际端点。 |
| API Key / `api_key` | 不含 `Bearer ` 前缀的 token | SDK 会话会添加 `Authorization: Bearer ` 前缀。这是 MCP 服务凭据，不是模型 Key。 |

Server 的 `/api/mcp` 请求使用 `url`，Desktop 的连接载荷使用 `streamable_http_url`。让各宿主的界面生成对应载荷，不混用两套字段。当前桥接支持用 API Key 进行 Bearer 鉴权；本例不是任意 Header 或 OAuth 配置。

嵌入式宿主通过 `builder.register(ExtensionRegistration(...))` 注册成对的
`tool.provider` 实现，在 runtime 中选择插件、Run scope 和可序列化参数。
工厂声明 `execution.environment` 依赖，取得当前 Run 的可信身份后创建 `McpToolPlugin`。
插件只实现工具协议，不组装 Agent 执行链。

凭据通过声明的 `credentials.provider` 依赖，使用 Run 请求上下文解析 `CredentialRef`。
密钥保存在凭据提供者中，配置和持久化元数据只保存引用。
`${REMOTE_MCP_API_KEY}` 是字面值，不会自动展开环境变量。
完整注册、配置及标准执行示例见[标准宿主参考项目](../../examples/v2/standard_host/README.md)。

### 发现、授权、调用与清理

1. **发现：** 启用连接，检查 catalog 实际返回的工具、Sage 名称与输入 schema。Server 的刷新操作会重新发现工具。保存连接或成功列出工具，不代表工具调用已成功。
2. **授权：** Server 页面在「智能体 → 编辑 → 可用工具 → 外部工具」逐项勾选，通过 Server API 的 `external_tools` 名单控制 MCP/A2A 可用范围；标准包沿用 `tools` 名单，由 Server 过滤后注入。未选择时禁用，新增工具需重新授权。嵌入式 Agent 的 `tools` 授权名单应包含实际发现的名称；宿主还需给 actor 所需的 `tool.external_side_effect` scope。MCP bridge 将所有外部工具标为 `WRITE` 与 `requires_approval=True`，即使名称或注释看起来只是只读搜索。默认 `CONFIGURED` 策略在 scope 检查后要求审批；宿主选择的策略与审批记忆可能改变交互。服务 Key 不能代替 Sage 授权。
3. **调用：** 在宿主审批流程中核对工具和参数，再检查返回结果。区分发现/鉴权失败与工具响应的 `isError`。超时、取消或丢失响应可能使远端副作用未知；考虑重试前先核实远端结果。
4. **清理：** 默认 bridge 为发现或一次调用打开短生命周期 SDK 会话，并在退出 context 后关闭。嵌入式宿主退出时保留 `await application.close()`。停用或删除连接用于停止后续使用，活动 Run 需另外取消；关闭本地会话不等于撤销服务 Key，也不能证明远端任务已停止。

MCP 调用默认时限为 7200 秒（2 小时），可通过每个服务的 `call_timeout_seconds` 配置其他正的有限时长；旧配置的空值使用默认时限。超时后将未知执行结果交给 Agent，由其查询状态或检查已有产物，再判断能否安全重试；超时本身不会要求人工参与。

该时限仅约束单次 MCP 远端调用，不是通用工具执行超时，也不限制内部 Team 或委派子 Run 的总运行时长。内部子任务没有默认两小时期限；只有显式配置的任务及祖先期限、预算或取消会形成相应约束。若通过外部 MCP 服务提交远端长任务，单次请求仍受 MCP 时限约束，应使用服务提供的任务提交与状态查询接口；本地请求超时不能证明远端任务已取消。

参见[宿主开发指南](architecture/sagents-host-development.md)。

## 免 Key 的 Parallel 搜索示例

[可运行的 SAgents 示例](../../examples/v2/PARALLEL_SEARCH.md)通过 Streamable HTTP
使用 Parallel Search MCP，在不提供 Parallel API Key 的情况下，经 v2 桥接发现并调用
网页搜索和页面抓取工具。示例由宿主显式调用；接入 Agent 时，请按上面的授权步骤配置。

### 嵌入式宿主可选的会话复用

宿主可以显式将 `McpSessionPool` 注入桥接层的 `session_factory`。
默认桥接仍为每次发现或调用建立会话，Desktop 和 Server 配置不会自动启用连接池。
宿主负责连接池的生命周期，必须在 MCP 工作期间保持连接池打开。
下例中的 `servers` 是 `McpServerConfig` 元组，`run_agent` 将传入的插件用作工具目录和执行器：

```python
from sagents.v2.tool import McpSessionPool, McpToolPlugin

async def run_with_mcp(servers, run_agent):
    pool = McpSessionPool(
        idle_timeout_seconds=300,
        shutdown_timeout_seconds=10,
        cleanup_timeout_seconds=5,
    )
    try:
        async with pool:
            plugin = McpToolPlugin(servers, session_factory=pool)
            await run_agent(plugin)
    finally:
        await pool.wait_closed()  # No deadline: keep the loop alive for teardown.
        # Inspect pool.cleanup_errors in the host shutdown diagnostics.
```

每个池属于一个事件循环和一个由宿主确定的安全作用域。不同租户或凭据作用域应使用独立的池。
相同有效配置共享一个已初始化会话，支持并发借用；释放或取消一个借用者不会关闭其他借用者的会话。
凭据、URL、命令、参数、环境变量和超时设置都参与会话标识；配置或凭据变化会创建独立条目。
如果继承的进程环境发生变化，宿主必须更换连接池。

`timeout_seconds` 独立限制每次获取和初始化，工具执行仍受 `call_timeout_seconds` 限制。
池的各项超时和获取超时必须为有限正数。空闲回收从最后一个借用归还后开始计时，
未被使用的初始化完成后也会开始计时。操作异常会使连接停止接受新借用，
后续获取可在已有借用归还后建立替代连接。池不会重试工具调用、执行退避或保活，
也不会根据通知刷新工具列表。

`aclose()` 拒绝新获取并唤醒等待者，最多等待 `shutdown_timeout_seconds` 让活跃借用归还，
然后关闭剩余会话。SDK 上下文始终由进入它的任务退出。各会话并行清理，
宿主等待受独立的 `cleanup_timeout_seconds` 限制。HTTP 或自定义初始化中断只发送一次取消，
让异步清理能够继续。默认 SDK 的 stdio 初始化使用其自身的 `timeout_seconds` 时限；
即使宿主等待超时，也会保留其初始化和进程树清理任务；
打断其优雅退出过程可能遗留子进程。宽限期到期可能中断活跃调用，
但不能据此认定服务端已经停止或可以安全重放。
取消等待 `aclose()` 的调用者不会放弃共享清理任务，再次调用 `aclose()` 会等待同一个有时限的关闭阶段。
已关闭的池不能重新进入。

`wait_closed()` 会在需要时发起关闭，并等待所有保留的生命周期任务结束。
它没有时限，支持重复调用和多个调用者同时等待。取消等待者或让等待超时不会取消 SDK 清理；
之后仍可通过 `wait_closed()` 观察完成。如果自定义工厂始终不退出，该等待也可能一直挂起。

有容量上限的 `cleanup_errors` 元组只包含脱敏的生命周期错误码，
包括 `session_cleanup_failed`、`cleanup_timeout` 和 `cleanup_incomplete`，宿主应将其纳入关闭诊断。
SDK 的 stdio 清理或抑制取消的自定义会话工厂可能超过宿主等待时限；
`cleanup_incomplete` 会报告此情况，池继续跟踪任务且不会复用该条目。
应保持事件循环运行直到 `wait_closed()` 完成；立即关闭事件循环可能中断保留的清理。
这些错误码是历史诊断记录，不是完成标志，清理结束后仍会保留。
已经收到的成功响应不会因后续传输清理失败而失效。会话复用不提供持久操作账本或恰好一次执行保证。
