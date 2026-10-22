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

Sage 是一个 **RSI Agent Harness**，整合任务执行、独立评测与递归自我改进。这里介绍当前实现的使用、接入和运行边界。

## 选择你的入口

| 你的目标 | 从这里开始 |
| --- | --- |
| 理解 RSI 如何改进 Package | [RSI 流程](applications/RSI.md) |
| 无需模型密钥体验一次迭代 | [首次 RSI 运行](applications/FIRST_RSI_RUN.md) |
| 安装桌面端并使用 RSI | [Desktop](applications/DESKTOP.md) |
| 嵌入自己的 Python 应用 | [快速开始](applications/GETTING_STARTED.md) · [宿主开发](architecture/sagents-host-development.md) |
| 提供多用户 Web 服务 | [Server](applications/WEB.md) |
| 配置模型、工具和 Skills | [配置](CONFIGURATION.md) · [工具与 MCP](MCP_SERVERS.md) |
| 接入现有客户端 | [Python API](api/API_REFERENCE.md) · [HTTP API](api/HTTP_API_REFERENCE.md) |

## 理解与扩展 Harness

[核心概念](CORE_CONCEPTS.md) · [架构](architecture/README.md) · [插件](architecture/PLUGINS.md) · [记忆](memory/README.md) · [支持范围](architecture/support-boundaries.md)。

## 运行与贡献

[环境变量](ENV_VARS.md) · [故障排查](TROUBLESHOOTING.md) · [开发](DEVELOPMENT.md)。

源码运行需要 Python **3.12+**。Desktop 安装包自带后端；Server 当前支持单 worker。

## 文档范围

本站只维护 Sage 自身的产品、SDK、协议与运行参考。旧版使用说明见 [Sage v1](https://github.com/ZHangZHengEric/Sage/blob/main/app/v1/README.md) 和[旧版参考目录](https://github.com/ZHangZHengEric/Sage/blob/main/docs/archive/README.md)。客户业务方案、临时审查和阶段性验收记录不作为仓库文档保留。
