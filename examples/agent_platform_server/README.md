# Docker 部署指南 - Sage Server

本文档提供了使用 Docker 部署 Sage Server的详细步骤说明。

## 前置要求

- Docker 已安装并正在运行
- 确保您在 Sage 项目的根目录下

## 部署步骤

### 1. 构建 Docker 镜像

在项目根目录下执行以下命令构建 Docker 镜像：

```bash
docker build -f examples/agent_platform_server/docker/Dockerfile -t sage-server:latest .
```

### 2. 运行 Docker 容器

构建完成后，使用以下命令运行容器：

```bash
docker run -d \
  --name agent-platform-server \
  -p 30050:8001 \
  -v /data/agent-platform/agent_workspace:/app/agent_workspace \
  -v /data/agent-platform/logs:/app/logs \
  -v /data/agent-platform/data:/app/data \
  sage-server:latest \
  --default_llm_api_key your_api_key \
  --default_llm_model_name deepseek-v3 \
  --default_llm_api_base_url https://dashscope.aliyuncs.com/compatible-mode/v1/ 
```

** 可选参数说明：**

#### LLM 配置参数
- `--default_llm_api_key`：默认LLM API Key，用于访问大语言模型服务
- `--default_llm_api_base_url`：默认LLM API Base URL，指定大语言模型服务的基础地址
- `--default_llm_model_name`：默认LLM模型名称，如 `qwen-plus`、`gpt-4` 等
- `--default_llm_max_tokens`：默认LLM API最大令牌数，默认值：4096
- `--default_llm_temperature`：默认LLM API温度参数，控制输出随机性，默认值：0.2
- `--default_llm_max_model_len`：默认LLM最大上下文长度，默认值：54000

#### 服务器配置参数
- `--host`：服务器主机地址，默认值：0.0.0.0
- `--port`：服务器端口号，默认值：8001

#### 功能配置参数
- `--mcp-config`：MCP配置文件路径，默认值：mcp_setting.json
- `--workspace`：工作空间目录，默认值：agent_workspace
- `--logs-dir`：日志目录，默认值：logs
- `--preset_running_config`：预设配置文件路径，包含system_context和workflow配置，与接口传入的参数合并使用，默认值：preset_running_config.json
- `--memory_root`：记忆存储根目录（可选参数）
- `--daemon`：以守护进程模式运行（布尔标志）
- `--pid-file`：PID文件路径，默认值：sage_stream.pid
- `--force_summary`：是否强制总结（布尔标志，默认值：False）
- `--db_path`：数据库文件路径，默认值：/app/data/agent_platform.db
**使用示例：**

```bash
# 基础运行
docker run -d \
  --name sage-server \
  -p 8001:8001 \
  sage-server:latest \
  --default_llm_api_key your_api_key \
  --default_llm_model_name qwen-plus \
  --default_llm_api_base_url https://dashscope.aliyuncs.com/compatible-mode/v1/

# 完整配置运行
docker run -d \
  --name sage-server \
  -p 8001:8001 \
  -v $(pwd)/workspace:/app/agent_workspace \
  -v $(pwd)/logs:/app/logs \
  sage-server:latest \
  --default_llm_api_key your_api_key \
  --default_llm_model_name qwen-plus \
  --default_llm_api_base_url https://dashscope.aliyuncs.com/compatible-mode/v1/ \
  --default_llm_max_tokens 8192 \
  --default_llm_temperature 0.3 \
  --host 0.0.0.0 \
  --port 8001 \
  --workspace agent_workspace \
  --logs-dir logs \
  --force_summary
```



### 3. 验证部署

检查容器是否正常运行：

```bash
# 查看容器状态
docker ps

# 查看容器日志
docker logs sage-server

# 测试服务是否可访问
curl http://localhost:8001