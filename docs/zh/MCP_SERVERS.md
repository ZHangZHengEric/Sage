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

## 嵌入式宿主

最小示例有意不启用文件或 Shell 工具。Official tools 需要宿主提供 `OfficialToolRuntime` 和明确的工作区、沙箱绑定。工具执行必须在资源边界校验 grant。内存 manifest 本身不授权任意本机文件访问。

通过[集成手册](https://github.com/ZHangZHengEric/Sage/blob/main/sagents/v2/使用手册.md)选择 catalog、executor、Skill 来源和策略 provider。`mcp_servers/` 中也有面向旧应用的集成，目录存在不代表 v2 自动启用它们。
