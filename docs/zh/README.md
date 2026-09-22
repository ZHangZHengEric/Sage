---
layout: default
title: 概览
nav_order: 1
lang: zh
ref: v2-README
permalink: /zh/
---

{% include lang_switcher.html %}

# 概览

本文档面向 **SAgents v2**、**Desktop v2** 和 **Server v2**，要求 Python **3.12+**。

| 你的目标 | 从这里开始 |
| --- | --- |
| 在本地使用 Sage | [Desktop v2](applications/DESKTOP.md) |
| 使用多用户 Web 应用 | [Server v2](applications/WEB.md) |
| 从 Python 运行 Agent | [快速开始](applications/GETTING_STARTED.md) |
| 组合插件与 Agent 包 | [配置](CONFIGURATION.md) · [插件扩展](architecture/PLUGINS.md) |
| 集成客户端 | [Python API](api/API_REFERENCE.md) · [HTTP API](api/HTTP_API_REFERENCE.md) |

## 理解运行时

[核心概念](CORE_CONCEPTS.md) → [架构](architecture/README.md) → [记忆](memory/README.md) → [工具与 MCP](MCP_SERVERS.md)。

## 运行与贡献

[环境变量](ENV_VARS.md) · [故障排查](TROUBLESHOOTING.md) · [开发](DEVELOPMENT.md)。

Desktop 是本机单用户宿主；Server 支持多用户，但当前只运行一个 worker。持久化本身不等于分布式执行。

## 文档范围

旧版应用指南、设计提案和历史审查记录已移出本站导航与搜索，保留在[仓库历史目录](https://github.com/ZHangZHengEric/Sage/blob/main/docs/archive/README.md)，不作为 v2 使用说明。独立的 `app/wiki` 内容介绍旧版产品，不是 v2 的参考文档。
