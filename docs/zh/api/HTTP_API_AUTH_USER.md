---
layout: default
title: 认证与用户
parent: HTTP API 参考
nav_order: 1
description: "本地账号 session、注册、用户管理与兼容路径"
lang: zh
ref: http-api-auth
---

{% include lang_switcher.html %}

# 认证与用户

路由源文件：`app/server/routers/auth.py`、`app/server/routers/user.py`，中间件白名单与 session 见 `app/server/core/middleware.py`。

## 本地账号行为

- **自注册**（`/api/auth/register`，及兼容的 `/api/user/register`）在开放自注册时可用，只接收 `username` 与 `password`。
- **密码登录**只接收 `username` 与 `password`。邮箱只用于注册验证，不可作为登录标识。
- **读取 `/api/auth/session`** 是前端判断是否已登录、是否完成引导的权威来源之一。

## 建议的二次开发接法

1. **同浏览器 Web 集成**：优先走 **Session Cookie**（`curl -c` / `withCredentials: true`），与现有 Vue 管理端行为一致。
2. **用户配置**：`GET/POST /api/user/config` 存的是当前用户可序列化的偏好（与 Agent/界面相关），**不是**系统级 `update_settings`（那在 `POST /api/system/update_settings`，管理员专用）。

## `/api/auth/`* 与 `/api/user/*` 的边界

- **推荐新代码**使用 `/api/auth/`* 列出的路径。
- `**/api/user/*` 兼容旧客户端**：多数与 `/api/auth` 成对，语义接近；迁移期两条都可能出现在 SDK 中，**不要**在同一次登录流程里混用两套路径 unless 你知道自己在做兼容层。

## 管理端与权限

- `GET/POST /api/user/list`、`/add`、`/delete` 等需要 **admin** 角色，否则会 403。集成自动化前确认当前 session 的 `role`（通常来自 `session` 或 claims）。
- 修改密码、用户选项等针对**当前**用户，与管理员管理他人账号是不同接口组。

[返回 HTTP API 参考](HTTP_API_REFERENCE.md)
