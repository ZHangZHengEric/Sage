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

## 认证与启动管理员

- `SAGE_AUTH_MODE`
- `SAGE_AUTH_PROVIDERS`
- `SAGE_TRUSTED_IDENTITY_PROXY_IPS`
- `SAGE_BOOTSTRAP_ADMIN_USERNAME`
- `SAGE_BOOTSTRAP_ADMIN_PASSWORD`
- `SAGE_JWT_KEY`
- `SAGE_JWT_EXPIRE_HOURS`
- `SAGE_REFRESH_TOKEN_SECRET`
- `SAGE_SESSION_SECRET`
- `SAGE_SESSION_COOKIE_NAME`
- `SAGE_SESSION_COOKIE_SECURE`
- `SAGE_SESSION_COOKIE_SAME_SITE`
- `SAGE_CORS_ALLOWED_ORIGINS`
- `SAGE_CORS_ALLOW_CREDENTIALS`
- `SAGE_CORS_ALLOW_METHODS`
- `SAGE_CORS_ALLOW_HEADERS`
- `SAGE_CORS_EXPOSE_HEADERS`
- `SAGE_CORS_MAX_AGE`

当前支持的部署模式先收敛为三种：

- `SAGE_AUTH_MODE=trusted_proxy`
  使用受信任代理接入模式。Sage 仍保留本地用户名密码登录，但只允许管理员登录；普通业务用户通常由上游系统完成认证，再通过受信任代理把身份透传给 Sage。
- `SAGE_AUTH_MODE=oauth`
  Sage 自身走上游 OAuth/OIDC 登录。通过 `SAGE_AUTH_PROVIDERS` 配置 OIDC provider。
- `SAGE_AUTH_MODE=native`
  使用 Sage 原生的用户名密码认证，支持本地密码登录。这里的 `native` 表示认证方式，不是“本地开发环境”。

`SAGE_TRUSTED_IDENTITY_PROXY_IPS` 支持逗号分隔的 IP 或 CIDR 白名单。它的作用是校验请求来源是否可以被视为受信任身份代理。只有来源命中该白名单时，Sage 才会接受可选的 `X-Sage-Internal-UserId` 并写入请求上下文，默认角色是 `user`。

Sage 现在把主要 CORS 维度都开放成可配置项，并保留默认值：

- `SAGE_CORS_ALLOWED_ORIGINS`：逗号分隔的来源白名单，默认 `*`
- `SAGE_CORS_ALLOW_CREDENTIALS`：是否允许浏览器携带凭据，默认 `false`
- `SAGE_CORS_ALLOW_METHODS`：逗号分隔的方法白名单，默认 `*`
- `SAGE_CORS_ALLOW_HEADERS`：逗号分隔的请求头白名单，默认 `*`
- `SAGE_CORS_EXPOSE_HEADERS`：逗号分隔的响应头暴露列表，默认空
- `SAGE_CORS_MAX_AGE`：预检缓存秒数，默认 `600`

默认形态是公开跨域，也就是 `*` 且不允许浏览器凭据。如果你把 `SAGE_CORS_ALLOW_CREDENTIALS=true` 打开，就不能继续使用通配符 `*`，必须显式配置来源白名单。

`SAGE_BOOTSTRAP_ADMIN_USERNAME` 和 `SAGE_BOOTSTRAP_ADMIN_PASSWORD` 现在是显式启用的一组配置。只有这两个变量都提供时，Sage 才会在首次启动时创建 bootstrap 管理员用户。

## 前端相关变量

如果你运行 `app/server/web/`，最先要检查的通常是：

- `VITE_SAGE_API_BASE_URL`
- `VITE_SAGE_WEB_BASE_PATH`

## 配置建议

- 优先先跑通最小配置，再逐步加上持久化和扩展能力。
- 当行为与预期不一致时，先回到 `config.py` 与实际启动日志核对。

## 示例 `.env`

```env
SAGE_PORT=8080
SAGE_AUTH_MODE=trusted_proxy
SAGE_DEFAULT_LLM_API_KEY=your-api-key
SAGE_DEFAULT_LLM_API_BASE_URL=https://api.deepseek.com/v1
SAGE_DEFAULT_LLM_MODEL_NAME=deepseek-chat
SAGE_DB_TYPE=file
SAGE_SESSION_DIR=sessions
SAGE_AGENTS_DIR=agents
SAGE_TRUSTED_IDENTITY_PROXY_IPS=10.0.0.0/8,127.0.0.1/32
SAGE_BOOTSTRAP_ADMIN_USERNAME=admin
SAGE_BOOTSTRAP_ADMIN_PASSWORD=change-this-before-first-run
```

OAuth 模式示例：

```env
SAGE_AUTH_MODE=oauth
SAGE_AUTH_PROVIDERS=[{"id":"corp-sso","type":"oidc","name":"Corp SSO","discovery_url":"https://sso.example.com/.well-known/openid-configuration","client_id":"sage","client_secret":"secret"}]
```

Native 模式示例：

```env
SAGE_AUTH_MODE=native
```
