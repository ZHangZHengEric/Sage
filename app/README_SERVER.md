# Sage Server 部署指南

Sage Server 是一个基于 FastAPI 的流式 Agent 平台后端服务，支持多种 LLM 模型、记忆管理、工具调用以及灵活的配置选项。

本文档提供了使用 Docker 部署 Sage Server 的详细说明，包括环境配置、启动参数及最佳实践。

## 前置要求

- Docker 已安装并正在运行
- 确保您在 Sage 项目的根目录下

## 部署步骤

### 1. 构建 Docker 镜像

在项目根目录下执行以下命令构建 Docker 镜像：

```bash
docker build -f app/server/docker/Dockerfile -t sage-server:latest .
```

### 2. 运行 Docker 容器

构建完成后，您可以根据需求选择环境变量或命令行参数的方式运行容器。

#### 基础运行示例

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

#### 完整配置示例（使用命令行参数）

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

## 本地源码部署

如果您希望在本地开发或直接运行源码，请按照以下步骤操作。

### 1. 环境准备

- Python 3.10+
- 建议使用虚拟环境

### 2. 安装依赖

在项目根目录下执行：

```bash
# 创建并激活虚拟环境 (可选)
python -m venv venv
source venv/bin/activate  # Linux/macOS
# venv\Scripts\activate   # Windows

# 安装依赖
pip install -r app/server/requirements.txt
```

### 3. 启动服务

使用模块化方式启动服务：

```bash
# 基础启动 (使用默认配置)
python -m app.server.main

# 带参数启动
python -m app.server.main \
  --port 8080 \
  --workspace ./agent_workspace \
  --default_llm_model_name "deepseek-chat" \
  --default_llm_api_key "your_api_key"
```

> **注意**：请确保在 Sage 项目根目录下执行命令，以便正确解析模块路径。

---

## 配置详解

Sage Server 支持通过 **命令行参数** 或 **环境变量** 进行配置。命令行参数优先级高于环境变量。

### 1. 服务器基础配置

| 命令行参数 | 环境变量 | 默认值 | 说明 |
| :--- | :--- | :--- | :--- |
| `--port` | `SAGE_PORT` | `8080` | 服务器监听端口 |
| `--workspace` | `SAGE_WORKSPACE_PATH` | `agent_workspace` | 工作空间目录（存放文件、临时数据等） |
| `--logs-dir` | `SAGE_LOGS_DIR_PATH` | `logs` | 日志文件存放目录 |
| `--pid-file` | `SAGE_PID_FILE` | `sage_stream.pid` | PID 文件路径 |
| `--daemon` | `SAGE_DAEMON` | `False` | 是否以守护进程模式运行 |
| `--force_summary` | `SAGE_FORCE_SUMMARY` | `False` | 是否强制开启总结功能 |
| `--no_auth` | `SAGE_NO_AUTH` | `True` | 是否禁用认证（默认禁用，根据 user_id 获取数据） |
| `--preset_mcp_config` | `SAGE_MCP_CONFIG_PATH` | `mcp_setting.json` | MCP 配置文件路径 |
| `--preset_running_config` | `SAGE_PRESET_RUNNING_CONFIG_PATH` | `agent_setting.json` | 预设运行配置（system_context, workflow 等） |

### 2. LLM 模型配置

| 命令行参数 | 环境变量 | 默认值 | 说明 |
| :--- | :--- | :--- | :--- |
| `--default_llm_api_key` | `SAGE_DEFAULT_LLM_API_KEY` | - | 默认 LLM API Key |
| `--default_llm_api_base_url` | `SAGE_DEFAULT_LLM_API_BASE_URL` | `https://api.deepseek.com/v1` | 默认 LLM API Base URL |
| `--default_llm_model_name` | `SAGE_DEFAULT_LLM_MODEL_NAME` | `deepseek-chat` | 默认 LLM 模型名称 |
| `--default_llm_max_tokens` | `SAGE_DEFAULT_LLM_MAX_TOKENS` | `4096` | 最大生成 Token 数 |
| `--default_llm_temperature` | `SAGE_DEFAULT_LLM_TEMPERATURE` | `0.2` | 温度参数 (0.0 - 1.0) |
| `--default_llm_max_model_len` | `SAGE_DEFAULT_LLM_MAX_MODEL_LEN` | `54000` | 最大上下文长度 |
| `--default_llm_top_p` | `SAGE_DEFAULT_LLM_TOP_P` | `0.9` | Top P 采样参数 |
| `--default_llm_presence_penalty` | `SAGE_DEFAULT_LLM_PRESENCE_PENALTY` | `0.0` | 存在惩罚参数 |

### 3. 上下文与记忆配置

| 命令行参数 | 环境变量 | 默认值 | 说明 |
| :--- | :--- | :--- | :--- |
| `--context_history_ratio` | `SAGE_CONTEXT_HISTORY_RATIO` | `0.2` | 历史消息占总上下文的比例 |
| `--context_active_ratio` | `SAGE_CONTEXT_ACTIVE_RATIO` | `0.3` | 活跃消息占总上下文的比例 |
| `--context_max_new_message_ratio` | `SAGE_CONTEXT_MAX_NEW_MESSAGE_RATIO` | `0.5` | 新消息最大比例 |
| `--context_recent_turns` | `SAGE_CONTEXT_RECENT_TURNS` | `0` | 包含最近 N 轮对话 |
| `--memory_root` | `SAGE_MEMORY_ROOT` | - | 记忆存储根目录（可选） |

### 4. 数据库配置

| 命令行参数 | 环境变量 | 默认值 | 说明 |
| :--- | :--- | :--- | :--- |
| `--db_type` | `SAGE_DB_TYPE` | `memory` | 数据库类型 (`file`, `memory`, `mysql`) |
| `--db_path` | `SAGE_DB_PATH` | `./data/` | 数据库文件路径 (仅 file 模式) |
| `--mysql_host` | `SAGE_MYSQL_HOST` | `127.0.0.1` | MySQL 主机地址 |
| `--mysql_port` | `SAGE_MYSQL_PORT` | `3306` | MySQL 端口 |
| `--mysql_user` | `SAGE_MYSQL_USER` | `root` | MySQL 用户名 |
| `--mysql_password` | `SAGE_MYSQL_PASSWORD` | `sage.1234` | MySQL 密码 |
| `--mysql_database` | `SAGE_MYSQL_DATABASE` | `sage` | MySQL 数据库名 |

### 5. Embedding 与 搜索配置

| 命令行参数 | 环境变量 | 说明 |
| :--- | :--- | :--- |
| `--embedding_api_key` | `SAGE_EMBEDDING_API_KEY` | Embedding API Key |
| `--embedding_base_url` | `SAGE_EMBEDDING_BASE_URL` | Embedding Base URL |
| `--embedding_model` | `SAGE_EMBEDDING_MODEL` | Embedding 模型名称 (默认: text-embedding-3-large) |
| `--es_url` | `SAGE_ELASTICSEARCH_URL` | Elasticsearch URL |
| `--es_api_key` | `SAGE_ELASTICSEARCH_API_KEY` | Elasticsearch API Key |
| `--es_username` | `SAGE_ELASTICSEARCH_USERNAME` | Elasticsearch 用户名 |
| `--es_password` | `SAGE_ELASTICSEARCH_PASSWORD` | Elasticsearch 密码 |

### 6. MinIO 对象存储配置

| 命令行参数 | 环境变量 | 说明 |
| :--- | :--- | :--- |
| `--minio_endpoint` | `SAGE_MINIO_ENDPOINT` | MinIO 服务地址 |
| `--minio_access_key` | `SAGE_MINIO_ACCESS_KEY` | Access Key |
| `--minio_secret_key` | `SAGE_MINIO_SECRET_KEY` | Secret Key |
| `--minio_bucket_name` | `SAGE_MINIO_BUCKET_NAME` | Bucket 名称 |
| `--minio_secure` | `SAGE_MINIO_SECURE` | 是否使用 HTTPS (默认 False) |

---

### 3. 验证部署

检查容器是否正常运行：

```bash
# 查看容器状态
docker ps

# 查看容器日志
docker logs sage-server

# 测试服务是否可访问
curl http://localhost:8080/health
# 或
curl http://localhost:8080
```
