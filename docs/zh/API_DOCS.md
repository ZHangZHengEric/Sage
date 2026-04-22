---
layout: default
title: API 文档
nav_order: 8.5
has_children: true
description: "当前 HTTP 与历史 Python 运行时 API 的入口与说明"
lang: zh
ref: api-docs
---

{% include lang_switcher.html %}

# API 文档

从此页进入两类资料，避免与「主站 HTTP」混淆：

- **[HTTP API 参考](HTTP_API_REFERENCE.md)**（可展开**二级子文档**）：与当前 `app/server/routers` 的 `register_routes` 一致的后端 HTTP 端点、请求体、响应与 `curl` 示例。对接**现有服务端**以本组为准。
- **[Python 运行时 API（历史 v0.9）](API_REFERENCE.md)**：从旧版材料恢复的运行时侧 Python 类/方法说明，**不**代表当前仓库的对外 HTTP；若你只做 HTTP 集成，可忽略此项。