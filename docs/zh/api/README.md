---
layout: default
title: API
nav_order: 8
lang: zh
ref: v2-api-README
has_children: true
---

{% include lang_switcher.html %}

# API

| 接口 | 用途 |
| --- | --- |
| [Python 运行时](API_REFERENCE.md) | 嵌入 SAgents v2 并管理生命周期。 |
| [Server HTTP](HTTP_API_REFERENCE.md) | 用户认证，管理模型、Agent、Skill、MCP 与 Run。 |
| [平台与可观测性](HTTP_API_PLATFORM.md) | 查看健康状态、日志和存储边界。 |

Server v2 与 Desktop sidecar 是不同的 API。Server 通过 `POST /api/agent` 提供 AG-UI SSE；Desktop 使用带本机认证的 `/api/v2/...` 路由及原生运行事件。不能把旧服务端路由直接用于 v2 客户端。
