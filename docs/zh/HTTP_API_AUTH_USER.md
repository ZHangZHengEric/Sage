---

## layout: default
title: 认证与用户
parent: HTTP API 参考
nav_order: 1
description: "部署模式、session、本地/OIDC 登录、用户管理与兼容路径"
lang: zh
ref: http-api-auth

{% include lang_switcher.html %}

# 认证与用户

路由源文件：`app/server/routers/auth.py`、`app/server/routers/user.py`，中间件白名单与 session 见 `app/server/core/middleware.py`。

## 部署模式对行为的影响

产品支持 `native`（本地账号+邮箱）、`trusted_proxy`（由前置认证注入身份）、`oauth` 等组合（具体以 `config` 与 `system_info` 为准）。**典型差异**：

- **注册与邮箱验证码**（`/api/auth/register*`，及兼容的 `/api/user/register*`）仅在开启本地注册时可用，否则会返回 400 类业务错误，文案见主参考「常见错误」。
- **密码登录**在 `native` 与 `trusted_proxy` 下可开，但 `trusted_proxy` 常限制为**管理员**登录，普通用户经上游身份注入走别的链路。
- **读取 `/api/auth/session`** 是前端判「是否已登录、是否做完引导」的权威来源之一，返回体结构见主参考中的 `UserInfoResponse` 表意。

## 建议的二次开发接法

1. **同浏览器 Web 集成**：优先走 **Session Cookie**（`curl -c` / `withCredentials: true`），与现有 Vue 管理端行为一致。不要假设「只用 OAuth2 `access_token` 就能带齐所有产品接口」——多数管理接口以服务端 session 为准（见主参考快速约定表）。
2. **机器对机器 / 外部系统**：看是否走 **OAuth2 授权服务**（见 [平台与可观测](HTTP_API_PLATFORM.md) 的 OAuth2 段与仓库内 [OAUTH2_LAGE_INTEGRATION.md](OAUTH2_LAGE_INTEGRATION.md)），或走上游 IdP 后再由 `trusted_proxy` 注入；两者与 `/api/auth/login` 不是同一套契约。
3. **用户配置**：`GET/POST /api/user/config` 存的是当前用户可序列化的偏好（与 Agent/界面相关），**不是**系统级 `update_settings`（那在 `POST /api/system/update_settings`，管理员专用）。

## `/api/auth/`* 与 `/api/user/*` 的边界

- **推荐新代码**使用 `/api/auth/`* 列出的路径。
- `**/api/user/*` 兼容旧客户端**：多数与 `/api/auth` 成对，语义接近；迁移期两条都可能出现在 SDK 中，**不要**在同一次登录流程里混用两套路径 unless 你知道自己在做兼容层。

## 管理端与权限

- `GET/POST /api/user/list`、`/add`、`/delete` 等需要 **admin** 角色，否则会 403。集成自动化前确认当前 session 的 `role`（通常来自 `session` 或 claims）。
- 修改密码、用户选项等针对**当前**用户，与管理员管理他人账号是不同接口组。

[返回 HTTP API 参考](HTTP_API_REFERENCE.md)