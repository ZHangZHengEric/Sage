---
layout: default
title: 应用入口
nav_order: 2
has_children: true
description: "快速开始、CLI、主服务端与桌面端等 Sage 应用入口"
lang: zh
ref: applications
---

{% include lang_switcher.html %}

# 应用入口

这部分收纳 Sage 的主要使用和启动入口。先看这一组文档，可以快速判断应该从 CLI、示例服务、主服务端，还是桌面端进入。

## 当前文档

1. [快速开始](GETTING_STARTED.md)
2. [CLI 使用指南](CLI.md)

## 该选哪个入口

### CLI

当你需要最快的开发测试入口、提示词迭代或运行时诊断时，使用 `sage run`、`sage chat` 和 `sage doctor`。

### Streamlit 演示

当你想快速看一个轻量演示 UI，而不想启动完整应用服务端时，使用 `examples/sage_demo.py`。

### 主服务端 + Web UI

当你需要主要的多用户应用栈时，使用 `app/server/main.py` 配合 `app/server/web/`：

- 认证
- 智能体管理
- 工具与技能管理
- 知识库集成
- 可观察性接口
- 浏览器聊天体验

### 桌面应用

当你需要带本地后端和 UI 壳层的打包应用时，使用 `app/desktop/entry.py` 与桌面源码树。

## Web 应用结构

- `app/server/main.py`：FastAPI 应用创建与启动
- `app/server/routers/`：HTTP 路由分组
- `app/server/services/`：应用服务层
- `app/server/web/src/`：Vue 应用源码

## 如何选择

- 想快速验证：优先 CLI
- 想体验主产品：优先服务端 + Web
- 想交付桌面安装包：进入桌面构建链路
