---
layout: default
title: 配置
nav_order: 5
description: "环境变量与运行时配置"
lang: zh
ref: configuration
---

{% include lang_switcher.html %}

# 配置

## 权威来源

主要配置来源是 `app/server/core/config.py`。它会基于环境变量和默认值构建 `StartupConfig`。

如果文档与实际行为不一致，以 `app/server/core/config.py` 为准。

## 最低必需设置

通常你最先需要配置的是：

- `SAGE_DEFAULT_LLM_API_KEY`
- `SAGE_DEFAULT_LLM_API_BASE_URL`
- `SAGE_DEFAULT_LLM_MODEL_NAME`

对于很多本地运行场景，这三个变量加上 `SAGE_PORT` 就足够了。

## 服务端与存储

- `SAGE_PORT`
- `SAGE_SESSION_DIR`
- `SAGE_LOGS_DIR_PATH`
- `SAGE_AGENTS_DIR`
- `SAGE_USER_DIR`
- `SAGE_SKILL_WORKSPACE`

这些设置控制 Sage 写入运行时状态、会话、智能体和 Skill 工作区数据的位置。

## 数据库

- `SAGE_DB_TYPE`
- `SAGE_MYSQL_HOST`
- `SAGE_MYSQL_PORT`
- `SAGE_MYSQL_USER`
- `SAGE_MYSQL_PASSWORD`
- `SAGE_MYSQL_DATABASE`

只有在你使用数据库后端时，才需要完整填写这组变量。

## 前端相关变量

如果你运行 `app/server/web/`，最先要检查的通常是：

- `VITE_SAGE_API_BASE_URL`
- `VITE_SAGE_WEB_BASE_PATH`

## 配置建议

- 优先先跑通最小配置，再逐步加上持久化和扩展能力。
- 当行为与预期不一致时，先回到 `config.py` 与实际启动日志核对。
