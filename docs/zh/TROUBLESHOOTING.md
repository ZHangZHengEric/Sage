---
layout: default
title: 故障排查
nav_order: 13
description: "常见 Sage 安装与运行问题"
lang: zh
ref: troubleshooting
---

{% include lang_switcher.html %}

# 故障排查

## 服务启动了，但模型调用失败

先检查默认模型设置：

- `SAGE_DEFAULT_LLM_API_KEY`
- `SAGE_DEFAULT_LLM_API_BASE_URL`
- `SAGE_DEFAULT_LLM_MODEL_NAME`

首次运行时，最常见的问题就是这些变量缺失。

## Web 应用能打开，但连不上后端

确认前后端都在运行：

- 后端：`python -m app.server.main`
- 前端：`cd app/server/web && npm run dev`

然后再确认前端配置的 API base URL 是否正确。

最先要检查的前端变量通常是：

- `VITE_SAGE_API_BASE_URL`
- `VITE_SAGE_WEB_BASE_PATH`

## 桌面版启动行为与服务端不同

这是预期行为。桌面版使用的是独立的启动路径：

- `app/desktop/entry.py`
- `app/desktop/core/main.py`

## 遇到问题时的排查顺序

1. 先确认入口是否正确
2. 再确认环境变量是否齐全
3. 然后检查日志与实际配置来源
