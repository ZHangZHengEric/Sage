---
layout: default
title: 快速开始
parent: 应用入口
nav_order: 1
description: "安装 Sage 并运行主要入口"
lang: zh
ref: getting-started
---

{% include lang_switcher.html %}

# 快速开始

## 一键启动（推荐）

**适用场景：** 本地开发、快速体验

```bash
# 1. 克隆仓库
git clone https://github.com/ZHangZHengEric/Sage.git
cd Sage

# 2. 配置 LLM API Key
export SAGE_DEFAULT_LLM_API_KEY="your-api-key"
export SAGE_DEFAULT_LLM_API_BASE_URL="https://api.deepseek.com/v1"
export SAGE_DEFAULT_LLM_MODEL_NAME="deepseek-chat"

# 3. 运行启动脚本
./scripts/dev-up.sh
```

**首次运行时，脚本会提示你选择配置模式：**

- **精简模式**（推荐新手）：使用 SQLite，无需外部依赖
  - 模板文件：`.env.example.minimal`
  - 适合：本地快速开发
- **完整模式**：使用 MySQL + ES + RustFS
  - 模板文件：`.env.example`
  - 适合：生产环境模拟

**启动成功后：**
- 前端访问：http://localhost:5173
- 后端 API：http://localhost:8080
- 健康检查：http://localhost:8080/api/health

## 配置文件说明

启动脚本会自动创建以下配置文件：

### 后端配置

- **位置：** 根目录 `.env`
- **模板：**
  - `.env.example.minimal` - 精简配置（SQLite，无外部依赖）
  - `.env.example` - 完整配置（MySQL + ES + RustFS）
- **用途：** Python 后端服务配置
- **关键配置项：**
  - `SAGE_DB_TYPE` - 数据库类型（sqlite/mysql）
  - `SAGE_AUTH_MODE` - 认证模式（native/trusted_proxy/oauth）
  - `SAGE_DEFAULT_LLM_API_KEY` - LLM API 密钥（必填）
  - `SAGE_PORT` - 后端端口（默认 8080）

### 前端配置

- **位置：** `app/server/web/.env.development`
- **模板：** `app/server/web/.env.example`
- **用途：** Vite 前端构建配置
- **关键配置项：**
  - `VITE_SAGE_API_BASE_URL` - 后端 API 地址
  - `VITE_SAGE_WEB_BASE_PATH` - Web 基础路径

---

## 手动启动（进阶）

如果你需要手动控制启动流程，可以参考以下步骤。

### 前置条件

- Python 3.10 或更高版本
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

## 选择认证部署模式

当前支持的认证部署模式先收敛为三种：

- `trusted_proxy`：企业网关或反向代理位于 `SAGE_TRUSTED_IDENTITY_PROXY_IPS` 白名单内时，业务请求无需用户在 Sage 内再次登录；管理员仍可使用原生账号密码登录，且上游可选透传 `X-Sage-Internal-UserId`
- `oauth`：Sage 自身跳转到上游 OAuth/OIDC Provider，配置来源是 `SAGE_AUTH_PROVIDERS`
- `native`：Sage 自身使用原生用户名密码登录

透传模式最小示例：

```bash
export SAGE_AUTH_MODE="trusted_proxy"
export SAGE_TRUSTED_IDENTITY_PROXY_IPS="10.0.0.0/8,127.0.0.1/32"
```

OAuth 模式最小示例：

```bash
export SAGE_AUTH_MODE="oauth"
export SAGE_AUTH_PROVIDERS='[{"id":"corp-sso","type":"oidc","name":"Corp SSO","discovery_url":"https://sso.example.com/.well-known/openid-configuration","client_id":"sage","client_secret":"secret"}]'
```

Native 模式最小示例：

```bash
export SAGE_AUTH_MODE="native"
```

本地开发默认使用 `SAGE_ENV=development`。如果你将 `SAGE_ENV` 设为 `production` 或 `staging`，还必须显式提供以下 secret：

- `SAGE_JWT_KEY`
- `SAGE_REFRESH_TOKEN_SECRET`
- `SAGE_SESSION_SECRET`

在这类生产环境配置下，Sage 也会强制启用安全的 session cookie。

## 运行 CLI

如果你想最快完成一次本地冒烟验证，可以运行 CLI：

```bash
pip install -r requirements.txt
pip install -e .
sage doctor
sage run "帮我分析当前仓库"
sage chat
```

这是验证模型配置和基本运行时链路是否正常的最快方式。

更完整的命令行使用说明请参考 [CLI 使用指南](CLI.md)。

## 手动启动 Web 服务

### 启动后端

启动后端：

```bash
python -m app.server.main
```

### 启动前端

在另一个终端：

```bash
cd app/server/web
npm install
npm run dev
```

---

## 桌面版构建

从源码构建桌面应用时，可使用：

```bash
# macOS/Linux
app/desktop/scripts/build.sh release

# Windows
./app/desktop/scripts/build_windows.ps1 release
```
