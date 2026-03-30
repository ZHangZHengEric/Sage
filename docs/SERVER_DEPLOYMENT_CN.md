---
layout: default
title: Server 部署指南
nav_order: 20
description: "当前 Sage 服务端与 Web 的部署指南"
---

# Server 部署指南

本文档以当前仓库中的实际部署入口为准。

## 1. Docker Compose

推荐直接使用根目录下的 [`docker-compose.yml`](../docker-compose.yml)。

```bash
docker-compose up -d
```

默认暴露的主要服务：

| 服务 | 主机端口 | 用途 |
|---|---:|---|
| `sage-server` | `30050` | 后端 API |
| `sage-web` | `30051` | Web UI |
| `sage-mysql` | `30052` | MySQL |
| `sage-es` | `30053` | Elasticsearch |
| `sage-minio` | `30054/30055` | 对象存储 |

常用访问地址：

- Web UI：`http://localhost:30051`
- API 文档：`http://localhost:30050/docs`
- Jaeger Dashboard：`http://localhost:30051/jaeger/`

## 2. 手动构建 Docker 镜像

当前服务端 Dockerfile 在 [`docker/Dockerfile.server`](../docker/Dockerfile.server)。

```bash
docker build -f docker/Dockerfile.server -t sage-server:latest .
```

运行示例：

```bash
docker run -d \
  --name sage-server \
  -p 8080:8080 \
  -e SAGE_DEFAULT_LLM_API_KEY="your_api_key" \
  -e SAGE_DEFAULT_LLM_API_BASE_URL="https://api.deepseek.com/v1" \
  -e SAGE_DEFAULT_LLM_MODEL_NAME="deepseek-chat" \
  sage-server:latest
```

## 3. 本地源码部署

从仓库根目录安装依赖：

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

启动当前维护中的后端入口：

```bash
python -m app.server.main
```

默认监听端口为 `8080`。

## 4. 前端部署

当前维护中的 Web 前端位于 [`app/server/web`](../app/server/web)。

```bash
cd app/server/web
npm install
npm run build
```

本地开发：

```bash
cd app/server/web
npm install
npm run dev
```

## 5. 独立示例服务

如果你想运行示例级流式服务，而不是完整服务端栈，可使用 [`examples/sage_server.py`](../examples/sage_server.py)。

```bash
python examples/sage_server.py \
  --default_llm_api_key "$SAGE_DEFAULT_LLM_API_KEY" \
  --default_llm_api_base_url "$SAGE_DEFAULT_LLM_API_BASE_URL" \
  --default_llm_model_name "$SAGE_DEFAULT_LLM_MODEL_NAME"
```

这个脚本有自己独立的 CLI 参数，和 `app.server.main` 不是同一套入口。

## 6. 配置

服务启动配置的权威定义在 [`app/server/core/config.py`](../app/server/core/config.py)。

常用环境变量：

- `SAGE_PORT`
- `SAGE_DEFAULT_LLM_API_KEY`
- `SAGE_DEFAULT_LLM_API_BASE_URL`
- `SAGE_DEFAULT_LLM_MODEL_NAME`
- `SAGE_DB_TYPE`
- `SAGE_SESSION_DIR`
- `SAGE_LOGS_DIR_PATH`
- `SAGE_AGENTS_DIR`
- `SAGE_SKILL_WORKSPACE`

## 7. 健康检查

可用探针接口：

- `GET /active`
- `GET /health`

示例：

```bash
curl http://127.0.0.1:8080/active
curl http://127.0.0.1:8080/health
```

## 说明

- 不要再使用 `app/server/requirements.txt` 这种旧说明；当前 Python 依赖从仓库根目录 `requirements.txt` 安装。
- 不要再参考把 CLI 参数直接传给 `python -m app.server.main` 的旧说明；当前维护中的服务入口主要通过代码默认值和环境变量读取启动配置。
