---
layout: default
title: 应用形态
nav_order: 6
description: "Sage 面向用户的主要应用入口"
lang: zh
ref: applications
---

{% include lang_switcher.html %}

# 应用形态

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
