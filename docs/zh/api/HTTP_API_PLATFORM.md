---
layout: default
title: 平台、存储与可观测
parent: HTTP API 参考
nav_order: 7
description: "LLM Provider、系统、版本、OSS、Jaeger、探活、OAuth2 与外链"
lang: zh
ref: http-api-platform
---

{% include lang_switcher.html %}

# 平台、存储与可观测

对应路由：`llm_provider.py`、`system.py`、`oss.py`、`version.py`、`observability.py`，根路径 `GET /active` 在 `app/server/main.py` 中挂在应用根上。

## LLM Provider（ `/api/llm-provider/...`）

- `verify` / `verify-capabilities` / `verify-multimodal` 三种校验用途不同：连通性、能力探测、多模态探针。上线前在管理 UI 里常先跑通其中一类再保存。
- `create` 成功时 `data` 为 `{"provider_id": ...}`，后续 `update` / `delete` 使用路径参数中的 `provider_id`。
- **默认 provider** 在删除等操作中有保护逻辑（主参考已给错误样例），自动化脚本要区分「业务用户自建」与「系统默认」。

## 系统与统计

- `GET /api/system/info`：前端首屏/登录页会用来展示是否开放注册、可用登录方式等（**公开侧**能看到的字段以代码为准，勿假设包含密钥）。
- `POST /api/system/update_settings`：**仅 admin**，改 `allow_registration` 等。
- `POST /api/system/agent/usage-stats`：带 `days` 与可选 `agent_id` 的用量统计，用于仪表盘类页面。

## 版本与包（`/api/system/version`*）

- `.../check`、`.../latest` 分别面向 Tauri/桌面与 Web 下载场景（响应模型不同，见主表）。
- 版本列表的 `POST/GET/DELETE` 供运营或脚本维护发布记录；与容器镜像 tag **无自动绑定**，属于产品元数据层。

## 对象存储 `POST /api/oss/upload`

- 多用在 Web/桌面**上传用户文件**、生成可被 markdown 引用的 URL；**桌面端**可能返回可映射到本地的路径（以当前平台实现与前端约定为准），对接时不要假设永远是 `https://` 公网地址。

## 可观测与 Jaeger

- `/api/observability/jaeger`*  为 **重定向/鉴权** 入口，并不要求你在业务 JSON 里解析 trace；**admin** 才能通过本地登录式跳转。详见主表与代码中的 `SageHTTPException` 分支（例如未启用本地登录时可能 503）。

## 根探活 `GET /active`

- 纯文本，用于负载均衡或 k8s 外层的存活检查；**不要**和 `GET /api/health`（JSON 包一层）混在同一监控项里不区分解析。

## OAuth2 与 `/api/auth` 的分工

- 本节 **不重复** 每种 grant 的报文。对外暴露 discovery（`/.well-known/oauth-authorization-server` 及别名 metadata）、`authorize`、`token`、`userinfo` 是 **标准 OAuth2/OIDC 行为**，适合「我们的 Server 当授权服务器、第三方要接 token」的集成方。
- 与 **网页里账户密码登录** 是两条故事线：一个读 [认证与用户](HTTP_API_AUTH_USER.md)，一个读仓库内 [OAUTH2_LAGE_INTEGRATION.md](OAUTH2_LAGE_INTEGRATION.md) 及你的客户端注册信息。

[返回 HTTP API 参考](HTTP_API_REFERENCE.md)