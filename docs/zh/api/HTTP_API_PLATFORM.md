---
layout: default
title: 平台、存储与可观测
parent: HTTP API 参考
nav_order: 7
description: "LLM Provider、系统、OSS、Jaeger、探活与外链"
lang: zh
ref: http-api-platform
---

{% include lang_switcher.html %}

# 平台、存储与可观测

对应路由：`llm_provider.py`、`system.py`、`oss.py`、`observability.py`，根路径 `GET /active` 在 `app/server/main.py` 中挂在应用根上。

## LLM Provider（ `/api/llm-provider/...`）

- `verify` / `verify-capabilities` / `verify-multimodal` 三种校验用途不同：连通性、能力探测、多模态探针。上线前在管理 UI 里常先跑通其中一类再保存。
- `create` 成功时 `data` 为 `{"provider_id": ...}`，后续 `update` / `delete` 使用路径参数中的 `provider_id`。
- **默认 provider** 在删除等操作中有保护逻辑（主参考已给错误样例），自动化脚本要区分「业务用户自建」与「系统默认」。

## 系统与统计

- `GET /api/system/info`：前端首屏/登录页会用来展示是否开放自注册（**公开侧**能看到的字段以代码为准，勿假设包含密钥）。
- `POST /api/system/update_settings`：**仅 admin**，改 `allow_registration` 等。
- `POST /api/system/agent/usage-stats`：带 `days` 与可选 `agent_id` 的用量统计，用于仪表盘类页面。

## 对象存储 `POST /api/oss/upload`

- 多用在 Web/桌面**上传用户文件**、生成可被 markdown 引用的 URL；**桌面端**可能返回可映射到本地的路径（以当前平台实现与前端约定为准），对接时不要假设永远是 `https://` 公网地址。

## 可观测与 Jaeger

- `/api/observability/jaeger`*  为 **重定向/鉴权** 入口，并不要求你在业务 JSON 里解析 trace；**admin** 通过本地账号登录后访问。

## 根探活 `GET /active`

- 纯文本，用于负载均衡或 k8s 外层的存活检查；**不要**和 `GET /api/health`（JSON 包一层）混在同一监控项里不区分解析。

[返回 HTTP API 参考](HTTP_API_REFERENCE.md)
