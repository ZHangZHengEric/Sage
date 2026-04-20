---
layout: default
title: 概览
nav_order: 1
description: "面向当前 Sage 仓库的任务型文档"
permalink: /zh/
lang: zh
ref: home
---

{% include lang_switcher.html %}

# Sage 文档

这套文档面向当前仓库实际存在的代码结构，围绕 `examples/`、`app/server/`、`app/desktop/`、`sagents/` 和 `mcp_servers/` 这些真实入口组织。

## 适合谁阅读

- 想在本地运行 Sage 的使用者
- 需要理解运行时和应用结构的贡献者
- 需要通过工具、技能、API 或 MCP Server 扩展 Sage 的集成人员

## 建议先读

1. [快速开始](GETTING_STARTED.md)：本地安装与首次运行
2. [CLI 使用指南](CLI.md)：命令行工作流与本地验证
2. [核心概念](CORE_CONCEPTS.md)：运行时模型
3. [架构](ARCHITECTURE.md)：仓库与子系统边界
4. [配置](CONFIGURATION.md)：环境变量与部署参数

## 常见阅读路径

### 我想在本地运行 Sage

建议阅读：

1. [快速开始](GETTING_STARTED.md)
2. [CLI 使用指南](CLI.md)
2. [应用形态](APPLICATIONS.md)
3. [故障排查](TROUBLESHOOTING.md)

### 我想扩展运行时

建议阅读：

1. [核心概念](CORE_CONCEPTS.md)
2. [架构](ARCHITECTURE.md)
3. [MCP Servers](MCP_SERVERS.md)
4. [开发](DEVELOPMENT.md)

### 我想和服务端集成

建议阅读：

1. [快速开始](GETTING_STARTED.md)
2. [配置](CONFIGURATION.md)
3. [API 参考](API_REFERENCE.md)
4. [HTTP API 参考](HTTP_API_REFERENCE.md)
5. [OAuth2 对接指南（Lage）](OAUTH2_LAGE_INTEGRATION.md)

## 文档地图

- [快速开始](GETTING_STARTED.md)：安装依赖并运行 CLI、服务端、Web UI 或桌面版
- [CLI 使用指南](CLI.md)：命令行工作流、会话、技能、工作目录与结构化输出
- [核心概念](CORE_CONCEPTS.md)：会话、智能体、工具、技能、流程和沙箱
- [架构](ARCHITECTURE.md)：代码库整体组织方式（含子章节）
  - 应用层：[Server](ARCHITECTURE_APP_SERVER.md) · [Desktop](ARCHITECTURE_APP_DESKTOP.md) · [其它入口](ARCHITECTURE_APP_OTHERS.md)
  - sagents 核心：[总览](ARCHITECTURE_SAGENTS_OVERVIEW.md) · [Agent / Flow](ARCHITECTURE_SAGENTS_AGENT_FLOW.md) · [Session / Context](ARCHITECTURE_SAGENTS_SESSION_CONTEXT.md) · [Tool / Skill](ARCHITECTURE_SAGENTS_TOOL_SKILL.md) · [Sandbox / LLM / Obs](ARCHITECTURE_SAGENTS_SANDBOX_OBS.md)
- [配置](CONFIGURATION.md)：运行时环境变量与存储设置
- [应用形态](APPLICATIONS.md)：不同入口分别适合什么场景
- [MCP Servers](MCP_SERVERS.md)：内置 MCP Server 以及它们在平台中的角色
- [API 参考](API_REFERENCE.md)：主要 HTTP 路由分组与流式接口
- [HTTP API 参考](HTTP_API_REFERENCE.md)：按当前代码库订正后的后端接口细节、请求体、返回体与示例
- [OAuth2 对接指南（Lage）](OAUTH2_LAGE_INTEGRATION.md)：恢复自历史提交的 OAuth2 对接文档
- [开发](DEVELOPMENT.md)：贡献流程和源码位置
- [故障排查](TROUBLESHOOTING.md)：常见启动和环境问题

## 当前产品入口

### 轻量示例

- `sage run` / `sage chat` / `sage doctor`：开发向 CLI 入口
- `examples/sage_demo.py`：Streamlit 演示
- `examples/sage_server.py`：独立 FastAPI 示例服务

### 主应用服务端

- `app/server/main.py`：主 FastAPI 应用入口
- `app/server/web/`：Vue 3 + Vite Web 客户端

当你需要完整产品能力，而不是演示程序时，优先走这条路径。

### 桌面应用

- `app/desktop/entry.py`：桌面端启动入口
- `app/desktop/core/main.py`：桌面本地 FastAPI 后端
- `app/desktop/ui/`：桌面 UI

当你需要打包后的桌面体验，而不是浏览器版应用时，使用这条路径。

### 核心运行时

- `sagents/sagents.py`：`SAgent` 流式运行时入口
- `sagents/agent/`：智能体实现
- `sagents/tool/`：工具系统与 MCP 代理支持
- `sagents/skill/`：Skill 加载与执行
- `sagents/utils/sandbox/`：沙箱抽象与提供者

## 文档原则

- 这套文档优先保证与当前源码一致，而不是追求历史信息完整。
- 历史迁移说明和重复页面不再作为主文档集合的一部分。
- 仓库根目录的 `README.md` 仍然是项目介绍页面；这里是技术层面的权威来源。
