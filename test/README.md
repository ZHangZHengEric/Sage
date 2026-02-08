# 全链路压测指南

本目录包含针对 Sage `/api/stream` 接口的全链路压测方案。

## 方案说明

该方案使用 Docker Compose 编排三个服务：
1. **sage-server**: 被测服务，配置了 1CPU 和 1G 内存限制。
2. **mock-llm**: 模拟 LLM 提供商（如 OpenAI），提供流式响应，避免消耗真实 Token 和产生费用。
3. **load-generator**: 压测执行器，运行 Python 脚本并发请求。

## 文件结构

- `stress.py`: 压测脚本，使用 `aiohttp` 进行并发流式请求，统计 TTFT (首字时间) 和总耗时。
- `mock_llm.py`: 模拟的 LLM 服务。
- `docker-compose.yml`: 服务编排文件。
- `Dockerfile.mock`: Mock 服务镜像构建文件。

## 运行压测

### 前置条件
- 安装 Docker 和 Docker Compose。

### 步骤

1. **启动压测环境并运行测试**
   在 `stress_test` 目录下执行：
   ```bash
   docker-compose up --build
   ```
   或者如果使用的是较新版本的 Docker：
   ```bash
   docker compose up --build
   ```

2. **查看压测结果**
   测试运行完成后，`load-generator` 容器会输出统计结果。查看日志：
   ```bash
   docker-compose logs -f load-generator
   ```

   结果示例：
   ```
   === Load Test Results ===
   Total Requests: 100
   Successful: 100
   Failed: 0
   TTFT (avg): 0.1050s
   TTFT (p95): 0.1200s
   Total Duration (avg): 1.5030s
   ```

3. **清理环境**
   测试结束后关闭服务：
   ```bash
   docker-compose down
   ```

## 自定义配置

- **修改并发数**: 编辑 `docker-compose.yml` 中 `load-generator` 的 `command`，修改 `--qps` 和 `--requests` 参数。
- **修改资源限制**: 编辑 `docker-compose.yml` 中 `sage-server` 的 `deploy.resources.limits` 部分。
