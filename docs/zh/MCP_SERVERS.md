---
layout: default
title: MCP Servers
nav_order: 6
description: "Sage 仓库中的内置 MCP Server"
lang: zh
ref: mcp-servers
---

{% include lang_switcher.html %}

# MCP Servers

## 概览

仓库在 `mcp_servers/` 下内置了一组 MCP Server 实现。它们属于 Sage 扩展模型的一部分，并可以通过工具系统暴露给运行时使用。

## 已包含的 Server

### Search

`mcp_servers/search/`

提供统一搜索能力，支持 Tavily、Brave、Serper、SerpAPI 等多种后端提供者。

### Image generation

`mcp_servers/image_generation/`

通过不同 provider adapter 提供统一的图像生成能力。

### Task scheduler

`mcp_servers/task_scheduler/`

提供定时任务执行与持久化能力，底层数据库路径由 `SAGE_ROOT` 推导。

### IM server

`mcp_servers/im_server/`

提供消息渠道集成，以及飞书、钉钉、iMessage、企业微信等渠道的 provider 实现。

## MCP 在运行时中的位置

MCP Server 让 Sage 可以用标准化协议接入外部工具能力，同时保持运行时侧的能力暴露方式一致。
