---
layout: default
title: 平台与可观测性
nav_order: 3
lang: zh
ref: v2-api-HTTP_API_PLATFORM
parent: API
---

{% include lang_switcher.html %}

# 平台与可观测性

- `GET /health` 和 `GET /active` 返回服务健康状态与实际后端选择。
- Server 默认输出 `sage.log/v1` JSON 行日志，通过 `SAGE_SERVER_LOG_*` 配置级别、格式和可选目录。
- 请求关联使用 `X-Request-ID`，JSON 响应也包含 `request_id`。
- 可选 Jaeger 集成使用 `SAGE_SERVER_JAEGER_*`，不是对话启动的必要依赖。
- Session 状态是权威来源，诊断文件和日志不能另建一套消息账本。

Server v2 使用 MySQL 保存应用库存和 Session，AG-UI 回放读取 Session 事件。Desktop 使用独立的本地数据根目录和 catalog。两者不依赖旧版桌面更新 API。

[环境变量](../ENV_VARS.md) · [服务端组件](https://github.com/ZHangZHengEric/Sage/blob/main/app/server_v2/README.md)
