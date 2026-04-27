---
layout: default
title: Chrome 扩展
parent: 应用入口
nav_order: 6
description: "加载 Sage 浏览器扩展并连接本地桌面端或服务端"
lang: zh
ref: chrome-extension
---

{% include lang_switcher.html %}

# Chrome 扩展（浏览器桥接）

仓库中 **`app/chrome-extension/`** 下的 **Chrome 扩展** 是**浏览器侧桥接**：在 **侧边栏** 与已运行的 Sage **桌面端**（或兼容的本地 API）通信，把页面上下文交给智能体，并可按命令队列在标签页上执行简单自动化。

它不是完整 **Web 主产品**（`app/server` + 常规浏览器访问）的替代品，而是**在 Chrome 中配合本地 Sage 后端**的轻量入口。

**仓库内技术说明原文：** [app/chrome-extension/README.md](https://github.com/ZHangZHengEric/Sage/blob/main/app/chrome-extension/README.md)

## 能力概述

- 在浏览器 **Side Panel** 中对话（按配置流式连接后端，例如桌面端 `/api/web-stream`）。
- 在允许对话前检测本地 Sage 服务是否已启动。
- 上报当前页上下文：标题、URL、选区、正文摘要等。
- 轮询**浏览器命令队列**，在需要时于当前标签页执行导航、点击、填表、脚本等动作。

## 加载未打包扩展（开发调试用）

1. 打开 `chrome://extensions/`。
2. 打开右上角**开发者模式**。
3. 点击**加载已解压的扩展程序**，选择目录：仓库内 **`app/chrome-extension`**（含扩展 `manifest` 的文件夹）。

## 配置后端地址

扩展默认会尝试常见本机地址，包括：

- `http://127.0.0.1:8000` / `http://localhost:8000`
- `http://127.0.0.1:8080` / `http://localhost:8080`

若你的服务端口或主机不同，在**扩展弹窗**中填写并保存。

## 使用侧边栏

点击工具栏中的 Sage 图标，Chrome 会以分屏方式打开 **Side Panel**，可在浏览网页的同时对话。

## 延伸阅读

- [其它应用入口架构 - Chrome 扩展](../architecture/ARCHITECTURE_APP_OTHERS.md) 中的扩展说明
- [桌面应用](DESKTOP.md) — 扩展通常与**已启动的桌面端后端**一起使用
- [Web 应用](WEB.md) — 完整 Web 与 Docker/服务端形态
