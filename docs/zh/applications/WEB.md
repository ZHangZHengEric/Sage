---
layout: default
title: Web 应用
parent: 应用入口
nav_order: 4
description: "浏览器端 Sage：一键脚本、手动前后端、Docker Compose 全栈"
lang: zh
ref: web-app
---

{% include lang_switcher.html %}

# Web 应用

**Web** 指 FastAPI 服务端（`app/server/`）与 Vue 3 前端（`app/server/web/`）组成的主产品，在浏览器中提供完整能力（认证、智能体、工具、知识库、工作台等）。

| 方式 | 适用场景 |
|------|----------|
| [一键启动](#一键启动) | 本地开发、最快上手（同 [快速开始](GETTING_STARTED.md)） |
| [手动：后端 + Vite](#手动启动前后端) | 分终端、固定端口、只调试一侧 |
| [Docker Compose](#docker-compose-全栈) | 容器化全栈（MySQL、ES、RustFS、Jaeger 等） |

## 一键启动

```bash
git clone https://github.com/ZHangZHengEric/Sage.git
cd Sage
export SAGE_DEFAULT_LLM_API_KEY="your-api-key"
export SAGE_DEFAULT_LLM_API_BASE_URL="https://api.deepseek.com/v1"
export SAGE_DEFAULT_LLM_MODEL_NAME="deepseek-chat"
./scripts/dev-up.sh
```

启动后（默认）：

- **Web 界面（Vite 开发服）：** http://localhost:5173
- **后端 API：** http://localhost:8080
- **健康检查：** http://localhost:8080/api/health

脚本可能提示 **最小模式**（SQLite）与 **完整依赖** 等，首次想最快跑通选最小模式。配置文件与变量说明见 [快速开始 - 配置说明](GETTING_STARTED.md#配置文件说明) 与 [配置说明](../CONFIGURATION.md)。

## 手动启动：前后端

在不想用 `dev-up.sh` 或需要分进程启动时使用。

1. **安装依赖**（在仓库根目录）

```bash
pip install -r requirements.txt
cd app/server/web && npm install && cd ../../..
```

2. **启动后端**

```bash
export SAGE_DEFAULT_LLM_API_KEY="your-api-key"
# 其它变量见根目录 .env
python -m app.server.main
```

默认监听 `0.0.0.0:${SAGE_PORT:-8080}`。

3. **启动前端**（另开终端）

```bash
cd app/server/web
npm run dev
```

4. **前端环境变量** — 见 `app/server/web/.env.example`，`VITE_SAGE_API_BASE_URL` 需指向已启动的后端地址。

## Docker Compose 全栈

仓库根目录 [`docker-compose.yml`](https://github.com/ZHangZHengEric/Sage/blob/main/docker-compose.yml) 会拉起 **完整** 依赖：`sage-server`、静态资源 `sage-web`、可选 `sage-wiki`，以及 MySQL、Elasticsearch、RustFS（S3 兼容）、Jaeger 等。偏 **类生产/整合演示**；若只是一般本地开发，更轻量的是「一键脚本 + 最小模式」。

**与 compose 中常见端口（映射到宿主机）对应关系：**

| 服务 | 宿主机端口（典型） | 说明 |
|------|------------------|------|
| `sage-server` | 30050 → 容器 8080 | 主 HTTP API |
| `sage-web` | 30051 → 80 | 构建后的 Web 静态资源（镜像内 nginx） |
| `sage-wiki` | 30057 → 80 | Wiki 前端（依赖 API） |
| `sage-mysql` | 30052 → 3306 | |
| `sage-es` | 30053 → 9200 | |
| `sage-rustfs` | 30054 / 30055 | 对象存储 API / 控制台 |

### 前置条件

- 已安装 **Docker** 与 **Compose v2**（`docker compose`）
- 宿主机资源充足（`docker-compose.yml` 中对 `sage-server` 等设了较大内存限制，可按需调小）
- 在仓库根目录提供 **`.env`**（`docker compose` 使用 `env_file: .env`）。可复制 [`.env.example`](https://github.com/ZHangZHengEric/Sage/blob/main/.env.example) 后修改，至少配置 **LLM** 与 **数据库/ES/对象存储** 等；示例中服务主机名为集群内名：`sage-mysql`、`sage-es`、`sage-rustfs` 等。

`SAGE_ROOT` 指向宿主机上用于**持久化卷**的目录（MySQL 数据、会话/日志、ES 数据、RustFS 等）。

### 启动

```bash
cd /path/to/Sage
export SAGE_ROOT=/path/to/sage-data   # 或例如 $(pwd)/data
cp .env.example .env
# 编辑 .env：SAGE_DEFAULT_LLM_API_KEY、各类密码、SAGE_MYSQL_PASSWORD、SAGE_ELASTICSEARCH_PASSWORD、SAGE_S3_* 等
docker compose up -d --build
```

**查看日志：**

```bash
docker compose logs -f sage-server
docker compose logs -f sage-web
```

**健康检查：**

```bash
curl -sS http://127.0.0.1:30050/api/health
```

**访问 Web** — 默认示例里常有 **基础路径**（`SAGE_WEB_BASE_PATH`，例如 `/sage`）。在示例 `.env` 下可尝试在浏览器打开 `http://127.0.0.1:30051` 并按你配置的路径（如 `/sage/`）进入；以团队实际部署的 nginx 路由为准。

`.env` 中的 `SAGE_API_BASE_URL` 需与浏览器能访问到的 **API 根地址** 一致（本地映射端口时多为 `http://127.0.0.1:30050`）。

### 停止

```bash
docker compose down
```

**端口冲突：** 若 30050–30057 等被占用，可改 `docker-compose.yml` 的 `ports:`，并同步修改 `.env` 中的公网/浏览器可达 URL 与 `SAGE_API_BASE_URL`。

## 延伸阅读

- [快速开始](GETTING_STARTED.md) — 一键脚本与总览
- [服务端架构](../architecture/ARCHITECTURE_APP_SERVER.md)
- [配置说明](../CONFIGURATION.md) · [环境变量](../ENV_VARS.md)
- [问题排查](../TROUBLESHOOTING.md)
