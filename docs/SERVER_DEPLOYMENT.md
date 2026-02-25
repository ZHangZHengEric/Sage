---
layout: default
title: Server Deployment Guide
nav_order: 20
description: "Sage Server Deployment and Configuration Guide"
---

# Sage Server Deployment Guide

Sage Server is a streaming Agent platform backend service based on FastAPI, supporting multiple LLM models, memory management, tool calling, and flexible configuration options.

This document provides detailed instructions for deploying Sage Server using Docker, including environment configuration, startup parameters, and best practices.

## Prerequisites

- Docker is installed and running
- Ensure you are in the root directory of the Sage project

## Deployment Steps

### 1. Docker Compose Deployment (Recommended)

We highly recommend using **Docker Compose** for one-click deployment, which automatically manages all dependent services (MySQL, Elasticsearch, RustFS, Jaeger, etc.).

#### Start Services
Execute in the project root directory:

```bash
docker-compose up -d
```

#### Service Port Mapping

| Service Name | Container Port | Host Port | Description |
| :--- | :--- | :--- | :--- |
| **sage-server** | 8080 | **30050** | Backend API Service |
| **sage-web** | 80 | **30051** | Frontend Web Interface |
| **sage-mysql** | 3306 | **30052** | Relational Database |
| **sage-es** | 9200 | **30053** | Vector Search & Full-text Search |
| **sage-minio** | 9000/9001 | **30054/30055** | Object Storage Service |
| **sage-jaeger** | 16686/4317 | **30056/4317** | Distributed Tracing |

> **Note**: After startup, please access the Web interface via `http://localhost:30051`. The backend API documentation is available at `http://localhost:30050/docs`.

---

### 2. Manual Docker Image Build (Alternative)

If you only need to run the core server or want to build manually:

```bash
docker build -f app/server/docker/Dockerfile -t sage-server:latest .
```

#### Basic Run Example

```bash
docker run -d \
  --name sage-server \
  -p 8080:8080 \
  -v $(pwd)/workspace:/app/agent_workspace \
  -v $(pwd)/logs:/app/logs \
  -v $(pwd)/data:/app/data \
  -e SAGE_DEFAULT_LLM_API_KEY="your_api_key" \
  -e SAGE_DEFAULT_LLM_MODEL_NAME="deepseek-chat" \
  -e SAGE_DEFAULT_LLM_API_BASE_URL="https://api.deepseek.com/v1" \
  sage-server:latest
```

#### Complete Configuration Example (Using Command Line Arguments)

```bash
docker run -d \
  --name sage-server \
  -p 8080:8080 \
  -v $(pwd)/workspace:/app/agent_workspace \
  -v $(pwd)/logs:/app/logs \
  sage-server:latest \
  --default_llm_api_key "your_api_key" \
  --default_llm_model_name "qwen-plus" \
  --default_llm_api_base_url "https://dashscope.aliyuncs.com/compatible-mode/v1/" \
  --default_llm_max_tokens 8192 \
  --default_llm_temperature 0.3 \
  --port 8080 \
  --workspace agent_workspace \
  --logs-dir logs \
  --force_summary
```

---

## Local Source Deployment

If you wish to develop locally or run directly from source, please follow the steps below.

### 1. Environment Preparation

- Python 3.10+
- Virtual environment recommended

### 2. Install Dependencies

Execute in the project root directory:

```bash
# Create and activate virtual environment (optional)
python -m venv venv
source venv/bin/activate  # Linux/macOS
# venv\Scripts\activate   # Windows

# Install dependencies
pip install -r app/server/requirements.txt
```

### 3. Start Service

Start the service using modular way:

```bash
# Basic start (using default configuration)
python -m app.server.main

# Start with parameters
python -m app.server.main \
  --port 8080 \
  --workspace ./agent_workspace \
  --default_llm_model_name "deepseek-chat" \
  --default_llm_api_key "your_api_key"
```

## Performance Test Results

Here is the evaluation report for `test-load-generator-1`:

```text
Starting load test with 600 total requests...
Target QPS: 60.0
Target: http://sage-server:8080/api/stream
Timeout: 600s
Waiting for server to be ready...
Server ready after 5.03s
Ensuring Mock MCP is registered...
Add MCP result: 500, trying refresh...
Refresh Mock MCP status: 200
Waiting for 'get_weather' tool to be available...
Tool 'get_weather' is available after 0.01s

=== Load Test Results ===
Total Requests: 600
Successful (200 OK): 600
Failed: 0
Success Rate: 100.00%
```

> **Note**: Please ensure you execute commands in the Sage project root directory to correctly resolve module paths.

---

## Configuration Details

Sage Server supports configuration via **Command Line Arguments** or **Environment Variables**. Command line arguments take precedence over environment variables.

### 1. Server Basic Configuration

| Command Line Argument | Environment Variable | Default Value | Description |
| :--- | :--- | :--- | :--- |
| `--port` | `SAGE_PORT` | `8080` | Server listening port |
| `--workspace` | `SAGE_WORKSPACE_PATH` | `agent_workspace` | Workspace directory (storing files, temporary data, etc.) |
| `--logs-dir` | `SAGE_LOGS_DIR_PATH` | `logs` | Log file storage directory |
| `--force_summary` | `SAGE_FORCE_SUMMARY` | `False` | Whether to force enable summary function |
| `--preset_mcp_config` | `SAGE_MCP_CONFIG_PATH` | `mcp_setting.json` | MCP configuration file path |
| `--preset_running_config` | `SAGE_PRESET_RUNNING_CONFIG_PATH` | `agent_setting.json` | Preset running configuration (system_context, workflow, etc.) |

### 2. LLM Model Configuration

| Command Line Argument | Environment Variable | Default Value | Description |
| :--- | :--- | :--- | :--- |
| `--default_llm_api_key` | `SAGE_DEFAULT_LLM_API_KEY` | - | Default LLM API Key |
| `--default_llm_api_base_url` | `SAGE_DEFAULT_LLM_API_BASE_URL` | `https://api.deepseek.com/v1` | Default LLM API Base URL |
| `--default_llm_model_name` | `SAGE_DEFAULT_LLM_MODEL_NAME` | `deepseek-chat` | Default LLM Model Name |
| `--default_llm_max_tokens` | `SAGE_DEFAULT_LLM_MAX_TOKENS` | `4096` | Max Generated Tokens |
| `--default_llm_temperature` | `SAGE_DEFAULT_LLM_TEMPERATURE` | `0.2` | Temperature Parameter (0.0 - 1.0) |
| `--default_llm_max_model_len` | `SAGE_DEFAULT_LLM_MAX_MODEL_LEN` | `54000` | Max Context Length |
| `--default_llm_top_p` | `SAGE_DEFAULT_LLM_TOP_P` | `0.9` | Top P Sampling Parameter |
| `--default_llm_presence_penalty` | `SAGE_DEFAULT_LLM_PRESENCE_PENALTY` | `0.0` | Presence Penalty Parameter |

### 3. Context and Memory Configuration

| Command Line Argument | Environment Variable | Default Value | Description |
| :--- | :--- | :--- | :--- |
| `--context_history_ratio` | `SAGE_CONTEXT_HISTORY_RATIO` | `0.2` | Ratio of history messages to total context |
| `--context_active_ratio` | `SAGE_CONTEXT_ACTIVE_RATIO` | `0.3` | Ratio of active messages to total context |
| `--context_max_new_message_ratio` | `SAGE_CONTEXT_MAX_NEW_MESSAGE_RATIO` | `0.5` | Max ratio of new messages |
| `--context_recent_turns` | `SAGE_CONTEXT_RECENT_TURNS` | `0` | Include recent N turns of dialogue |
| `--memory_type` | `SAGE_MEMORY_TYPE` | `session` | Memory Type (session \| user) |
| - | `MEMORY_ROOT_PATH` | - | Memory storage root directory (only effective when memory_type is user) |

### 4. Database Configuration

| Command Line Argument | Environment Variable | Default Value | Description |
| :--- | :--- | :--- | :--- |
| `--db_type` | `SAGE_DB_TYPE` | `memory` | Database Type (`file`, `memory`, `mysql`) |
| `--db_path` | `SAGE_DB_PATH` | `./data/` | Database file path (file mode only) |
| `--mysql_host` | `SAGE_MYSQL_HOST` | `127.0.0.1` | MySQL Host Address |
| `--mysql_port` | `SAGE_MYSQL_PORT` | `3306` | MySQL Port |
| `--mysql_user` | `SAGE_MYSQL_USER` | `root` | MySQL Username |
| `--mysql_password` | `SAGE_MYSQL_PASSWORD` | `sage.1234` | MySQL Password |
| `--mysql_database` | `SAGE_MYSQL_DATABASE` | `sage` | MySQL Database Name |

### 5. Embedding and Search Configuration

| Command Line Argument | Environment Variable | Description |
| :--- | :--- | :--- |
| `--embedding_api_key` | `SAGE_EMBEDDING_API_KEY` | Embedding API Key |
| `--embedding_base_url` | `SAGE_EMBEDDING_BASE_URL` | Embedding Base URL |
| `--embedding_model` | `SAGE_EMBEDDING_MODEL` | Embedding Model Name (Default: text-embedding-3-large) |
| `--es_url` | `SAGE_ELASTICSEARCH_URL` | Elasticsearch URL |
| `--es_api_key` | `SAGE_ELASTICSEARCH_API_KEY` | Elasticsearch API Key |
| `--es_username` | `SAGE_ELASTICSEARCH_USERNAME` | Elasticsearch Username |
| `--es_password` | `SAGE_ELASTICSEARCH_PASSWORD` | Elasticsearch Password |

### 6. RustFS Object Storage Configuration

| Command Line Argument | Environment Variable | Description |
| :--- | :--- | :--- |
| `--s3_endpoint` | `SAGE_S3_ENDPOINT` | RustFS Service Address |
| `--s3_access_key` | `SAGE_S3_ACCESS_KEY` | Access Key |
| `--s3_secret_key` | `SAGE_S3_SECRET_KEY` | Secret Key |
| `--s3_bucket_name` | `SAGE_S3_BUCKET_NAME` | Bucket Name |
| `--s3_secure` | `SAGE_S3_SECURE` | Whether to use HTTPS (Default False) |

### 7. Observability (Jaeger) Configuration

Sage integrates Jaeger for distributed tracing to facilitate performance bottleneck and error troubleshooting.

| Command Line Argument | Environment Variable | Description |
| :--- | :--- | :--- |
| `--trace_jaeger_url` | `SAGE_TRACE_JAEGER_URL` | Jaeger OTLP HTTP Endpoint (e.g., `http://localhost:4318/v1/traces`) |
| `--enable_trace` | `SAGE_ENABLE_TRACE` | Whether to enable tracing (Default: True) |

---

### 3. Verify Deployment

Check if the container is running normally:

```bash
# View container status
docker ps

# View container logs
docker logs sage-server

# Test if service is accessible
curl http://localhost:8080/health
# or
curl http://localhost:8080
```
