---
layout: default
title: 快速开始
nav_order: 2
description: "安装 Sage 并运行主要入口"
lang: zh
ref: getting-started
---

{% include lang_switcher.html %}

# 快速开始

## 先选一条起步路径

- 如果你想最快完成一次本地冒烟验证，使用示例 CLI。
- 如果你需要主应用栈，使用 `app/server/main.py` 加 Web UI。
- 只有在你明确需要打包桌面版时，才使用桌面构建链路。

## 前置条件

- Python 3.11 或更高版本
- 运行 Web 客户端和部分桌面流程所需的 Node.js
- 你计划使用的模型供应商对应的有效 LLM API Key

在仓库根目录安装 Python 依赖：

```bash
pip install -r requirements.txt
```

如果你计划运行 Web 客户端，还需要在 `app/server/web/` 下单独安装 Node.js 依赖。

## 最小环境变量

只配置默认 LLM 相关设置时，Sage 就可以启动：

```bash
export SAGE_DEFAULT_LLM_API_KEY="your-api-key"
export SAGE_DEFAULT_LLM_API_BASE_URL="https://api.deepseek.com/v1"
export SAGE_DEFAULT_LLM_MODEL_NAME="deepseek-chat"
```

如果你使用本地 `.env` 文件，`app/server/main.py` 和 `app/desktop/core/main.py` 都会自动加载它。

本地开发默认使用 `SAGE_ENV=development`。如果你将 `SAGE_ENV` 设为 `production` 或 `staging`，还必须显式提供以下 secret：

- `SAGE_JWT_KEY`
- `SAGE_REFRESH_TOKEN_SECRET`
- `SAGE_SESSION_SECRET`

在这类生产环境配置下，Sage 也会强制启用安全的 session cookie。

## 运行轻量 CLI

```bash
python examples/sage_cli.py \
  --default_llm_api_key YOUR_API_KEY \
  --default_llm_api_base_url https://api.deepseek.com/v1 \
  --default_llm_model_name deepseek-chat
```

这是验证模型配置和基本运行时链路是否正常的最快方式。

## 运行主服务端和 Web UI

启动后端：

```bash
python -m app.server.main
```

另开一个终端启动前端：

```bash
cd app/server/web
npm install
npm run dev
```

## 构建桌面版

从源码构建桌面应用时，可使用：

```bash
# macOS/Linux
app/desktop/scripts/build.sh release

# Windows
./app/desktop/scripts/build_windows.ps1 release
```
