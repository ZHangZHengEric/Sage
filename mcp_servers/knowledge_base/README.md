# Knowledge Base MCP Server

一个基于 FastAPI + FastMCP 的文档检索与管理微服务，使用 OpenAI 向量嵌入与 Elasticsearch 存储与检索。

## 功能
- 文档分段与向量化（OpenAI Embeddings）
- Elasticsearch 索引创建、插入、删除、清空
- BM25 与向量检索混合，提供后处理融合与重叠合并
- 通过 MCP 暴露为可调用的工具接口

## 安装
- 进入目录：`mcp_servers/knowledge_base`
- 安装依赖：`pip install -r requirements.txt`

## 环境变量
- `OPENAI_API_KEY` 或 `KB_EMBEDDING_API_KEY`：嵌入 API 密钥
- `OPENAI_BASE_URL` 或 `KB_EMBEDDING_BASE_URL`：嵌入 API 基础地址（可选）
- `EMBEDDING_MODEL` 或 `KB_EMBEDDING_MODEL`：嵌入模型（默认 `text-embedding-3-large`）
- `EMBEDDING_DIMS` 或 `KB_EMBEDDING_DIMS`：向量维度（默认 `1024`）
- `ELASTICSEARCH_URL` 或 `ES_URL`：Elasticsearch 地址（默认 `http://localhost:9200`）
- `ELASTICSEARCH_API_KEY` 或 `ES_API_KEY`：Elasticsearch API Key（可选）
- `ELASTICSEARCH_USERNAME`/`PASSWORD` 或 `ES_USERNAME`/`ES_PASSWORD`：Elasticsearch 账号（可选）
- `KB_PORT`：服务端口（默认 `34003`）

## 启动
- 直接运行：`python main.py`
- 或使用 Uvicorn：`uvicorn main:app --host 0.0.0.0 --port 34003`

## 暴露的工具
- `doc_document_insert(index_name, docs)`：写入分段后的文档
- `doc_document_delete(index_name, doc_ids)`：删除指定文档
- `doc_index_clear(index_name)`：清空索引
- `doc_retrieve(index_name, question, query_size)`：检索并后处理返回结果


## 目录结构
- `main.py`：服务入口与 MCP 工具注册
- `config/settings.py`：环境变量读取
- `core/`：嵌入与 ES 客户端、分段与后处理
- `es/`：文档模型与索引/检索逻辑
- `service/`：业务服务封装

## 备注
- 当索引不存在时的检查与操作已做容错处理，避免 400/404 导致失败