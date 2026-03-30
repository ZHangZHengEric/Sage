---
layout: default
title: Server Deployment Guide
nav_order: 20
description: "Current deployment guide for Sage server and web app"
---

# Server Deployment Guide

This guide reflects the current deployment entry points in the repository.

## 1. Docker Compose

The recommended deployment path is the root [`docker-compose.yml`](../docker-compose.yml).

```bash
docker-compose up -d
```

Default exposed services from the bundled stack:

| Service | Host Port | Purpose |
|---|---:|---|
| `sage-server` | `30050` | backend API |
| `sage-web` | `30051` | web UI |
| `sage-mysql` | `30052` | MySQL |
| `sage-es` | `30053` | Elasticsearch |
| `sage-minio` | `30054/30055` | object storage |

Common access URLs:

- Web UI: `http://localhost:30051`
- API docs: `http://localhost:30050/docs`
- Jaeger dashboard: `http://localhost:30051/jaeger/`

## 2. Manual Docker Build

The current server Dockerfile is [`docker/Dockerfile.server`](../docker/Dockerfile.server).

```bash
docker build -f docker/Dockerfile.server -t sage-server:latest .
```

Example:

```bash
docker run -d \
  --name sage-server \
  -p 8080:8080 \
  -e SAGE_DEFAULT_LLM_API_KEY="your_api_key" \
  -e SAGE_DEFAULT_LLM_API_BASE_URL="https://api.deepseek.com/v1" \
  -e SAGE_DEFAULT_LLM_MODEL_NAME="deepseek-chat" \
  sage-server:latest
```

## 3. Local Source Deployment

Install dependencies from the repository root:

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Start the maintained backend entry:

```bash
python -m app.server.main
```

By default it listens on port `8080`.

## 4. Frontend Deployment

The maintained web frontend lives in [`app/server/web`](../app/server/web).

```bash
cd app/server/web
npm install
npm run build
```

For local development:

```bash
cd app/server/web
npm install
npm run dev
```

## 5. Standalone Example Server

If you specifically want the example streaming service instead of the full server stack, use [`examples/sage_server.py`](../examples/sage_server.py).

```bash
python examples/sage_server.py \
  --default_llm_api_key "$SAGE_DEFAULT_LLM_API_KEY" \
  --default_llm_api_base_url "$SAGE_DEFAULT_LLM_API_BASE_URL" \
  --default_llm_model_name "$SAGE_DEFAULT_LLM_MODEL_NAME"
```

This script has its own CLI arguments and is separate from `app.server.main`.

## 6. Configuration

The authoritative server startup config is [`app/server/core/config.py`](../app/server/core/config.py).

Common environment variables:

- `SAGE_PORT`
- `SAGE_DEFAULT_LLM_API_KEY`
- `SAGE_DEFAULT_LLM_API_BASE_URL`
- `SAGE_DEFAULT_LLM_MODEL_NAME`
- `SAGE_DB_TYPE`
- `SAGE_SESSION_DIR`
- `SAGE_LOGS_DIR_PATH`
- `SAGE_AGENTS_DIR`
- `SAGE_SKILL_WORKSPACE`

## 7. Health Checks

Useful endpoints:

- `GET /active`
- `GET /health`

Examples:

```bash
curl http://127.0.0.1:8080/active
curl http://127.0.0.1:8080/health
```

## Notes

- Do not use old instructions that reference `app/server/requirements.txt`; the current Python dependencies are installed from the repository root `requirements.txt`.
- Do not use old instructions that pass CLI flags directly to `python -m app.server.main`; the maintained server entry reads its startup config from code defaults and environment variables.
