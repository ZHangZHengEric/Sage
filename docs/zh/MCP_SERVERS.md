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

嵌入式宿主应显式从进程环境读取 token：

```python
import os
from sagents.v2.tool import McpServerConfig, McpToolPlugin

key = os.environ["REMOTE_MCP_API_KEY"]
if not key.strip():
    raise ValueError("REMOTE_MCP_API_KEY must not be empty")

mcp = McpToolPlugin((McpServerConfig(
    name="remote",
    protocol="streamable_http",
    url="https://mcp.example.com/mcp",
    api_key=key,
),))
```

这一步只构造 provider，不连接服务。在构建 v2 application 前，用 builder 的 `with_tool_provider(mcp, mcp)` 将其注册为 catalog 和 executor；组合多个 provider 的方式见集成手册。API Key 字段中的 `${REMOTE_MCP_API_KEY}` 是字面值，不会自动展开环境变量。不要把 token 放入提交的配置、截图或日志。

### 发现、授权、调用与清理

1. **发现：** 启用连接，检查 catalog 实际返回的工具、Sage 名称与输入 schema。Server 的刷新操作会重新发现工具。保存连接或成功列出工具，不代表工具调用已成功。
2. **授权：** 嵌入式 Agent 的 `tools` 授权名单应包含实际发现的名称；宿主还需给 actor 所需的 `tool.external_side_effect` scope。MCP bridge 将所有外部工具标为 `WRITE` 与 `requires_approval=True`，即使名称或注释看起来只是只读搜索。默认 `CONFIGURED` 策略在 scope 检查后要求审批；宿主选择的策略与审批记忆可能改变交互。服务 Key 不能代替 Sage 授权。
3. **调用：** 在宿主审批流程中核对工具和参数，再检查返回结果。区分发现/鉴权失败与工具响应的 `isError`。超时、取消或丢失响应可能使远端副作用未知；考虑重试前先核实远端结果。
4. **清理：** 默认 bridge 为发现或一次调用打开短生命周期 SDK 会话，并在退出 context 后关闭。嵌入式宿主退出时保留 `await application.close()`。停用或删除连接用于停止后续使用，活动 Run 需另外取消；关闭本地会话不等于撤销服务 Key，也不能证明远端任务已停止。

## 免 Key 的 Parallel 搜索示例

[可运行的 SAgents v2 示例](../../examples/PARALLEL_SEARCH.md)通过 Streamable HTTP
使用 Parallel Search MCP，在不提供 Parallel API Key 的情况下，经 v2 桥接发现并调用
网页搜索和页面抓取工具。示例由宿主显式调用；接入 Agent 时，请按上面的授权步骤配置。
