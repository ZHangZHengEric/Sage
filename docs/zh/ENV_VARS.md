---
layout: default
title: 环境变量速查
nav_order: 6
description: "Sage 所有环境变量的权威清单与默认值"
lang: zh
ref: env_vars
---

{% include lang_switcher.html %}

# 环境变量速查

> 本文档由代码扫描归纳，覆盖 `sagents/`、`app/`、`common/`、`mcp_servers/` 中所有
> `os.environ.get` / `os.getenv` 调用。配置项语义以代码注释为准，本表只做摘要。
> 默认值列写 "—" 表示未读到默认值（必填或动态推导）。

## 0. 部署示例口径

`deploy/dev|test|prod/.env.example` 采用最小必填口径：只保留 Compose/应用运行通常需要修改的部署参数、密钥、账号和外部地址。Kubernetes 专属配置放在 `deploy/k8s/env/*.env.example`，不混入通用环境模板。稳定默认值由代码、Compose 或 K8s 部署脚本提供。

示例中保留的重点变量：

| 类型 | 变量 |
| --- | --- |
| 环境与入口 | `SAGE_ENV`、`SAGE_ROOT` |
| 密钥与账号 | `SAGE_JWT_KEY`、`SAGE_REFRESH_TOKEN_SECRET`、`SAGE_SESSION_SECRET`、MySQL/S3/Grafana 密码、LLM/Embedding/视频分析 API Key、邮件 AK/SK |
| 外部地址 | `SAGE_TRACE_JAEGER_PUBLIC_URL`、`SAGE_GRAFANA_PUBLIC_URL`、`SAGE_S3_PUBLIC_BASE_URL`、`SAGE_ELASTICSEARCH_URL` |

Kubernetes 模板单独保留 `NAMESPACE`、`SAGE_HOST`、`SAGE_PUBLIC_URL`、`IMAGE_REGISTRY`、`IMAGE_PULL_POLICY`、`K8S_IMAGE_TARGET`、`CTR_BIN`、`CTR_NAMESPACE`、`STORAGE_CLASS`、`INGRESS_CLASS_NAME`、`TLS_SECRET_NAME`、`ENABLE_INGRESS`、`SAGE_WEB_SERVICE_TYPE`、`SAGE_WIKI_SERVICE_TYPE`、`SAGE_WEB_NODE_PORT`、`SAGE_WIKI_NODE_PORT`。

高级可覆盖变量不放入 `.env.example`，除非部署确实需要覆盖。常见项包括 Compose 项目名和端口覆盖、`SAGE_WEB_BASE_PATH`、`SAGE_TRACE_JAEGER_URL`、`SAGE_LOKI_PUSH_URL`、`SAGE_MCP_*`、`OPENSANDBOX_IMAGE`、`OPENSANDBOX_TIMEOUT`、`SAGE_OPENSANDBOX_APPEND_MAX_BYTES`、默认 LLM/Embedding 模型参数、视频分析模型参数、邮件固定默认项。

## 1. LLM 与默认模型


| 变量                              | 默认值 | 说明                      |
| ------------------------------- | --- | ----------------------- |
| `SAGE_DEFAULT_LLM_API_KEY`      | —   | 默认模型 API Key（OpenAI 兼容） |
| `SAGE_DEFAULT_LLM_API_BASE_URL` | `https://dashscope.aliyuncs.com/compatible-mode/v1/` | 默认模型 base URL |
| `SAGE_DEFAULT_LLM_MODEL_NAME`   | `deepseek-v3` | 默认模型名 |
| `SAGE_DEFAULT_LLM_MAX_TOKENS`   | `4096` | 默认最大输出 token |
| `SAGE_DEFAULT_LLM_TEMPERATURE`  | `0.2` | 默认采样温度 |
| `SAGE_DEFAULT_LLM_MAX_MODEL_LEN` | `52000` | 默认上下文长度 |
| `SAGE_DEFAULT_LLM_TOP_P` | `1.0` | 默认 nucleus sampling 参数 |
| `SAGE_DEFAULT_LLM_PRESENCE_PENALTY` | `0.0` | 默认 presence penalty |
| `SAGE_REASONING_EFFORT_OFF` | `low` | thinking 关闭时，OpenAI reasoning 模型使用的 reasoning effort；可设为 provider 支持的 `minimal` / `low` / `medium` / `high` 等 |


## 2. 服务端口与目录


| 变量                     | 默认值                   | 说明                            |
| ---------------------- | --------------------- | ----------------------------- |
| `SAGE_HOST`            | —                     | 部署对外访问域名/IP，主要用于 K8s 地址派生；不是服务端监听地址 |
| `SAGE_ENV`             | `development`         | 应用环境名 |
| `SAGE_AUTH_MODE`       | `native`              | 服务端认证模式 |
| `SAGE_LOG_LEVEL`       | `info`                | 服务端日志级别 |
| `SAGE_PORT`            | `8001`（server）/ 桌面端动态 | 服务端口                          |
| `SAGE_ROOT`            | `~/.sage`             | 全局根目录，下设 sessions/agents/logs |
| `SAGE_SESSION_DIR`     | `$SAGE_ROOT/sessions` | server / terminal 会话目录 |
| `SAGE_LOGS_DIR_PATH`   | `$SAGE_ROOT/logs`     | 日志目录 |
| `SAGE_AGENTS_DIR`      | `$SAGE_ROOT/agents`   | server / terminal Agent 目录 |
| `SAGE_USER_DIR`        | `$SAGE_ROOT/users`    | 用户数据目录 |
| `SAGE_DB_FILE`         | `$SAGE_ROOT/sage.db`  | SQLite / file 数据库路径 |
| `SAGE_SKILL_WORKSPACE` | `$SAGE_ROOT/skills`   | Skill 工作区目录 |
| `SAGE_SESSIONS_PATH`   | `$SAGE_ROOT/sessions` | 会话持久化目录                       |
| `SAGE_AGENTS_PATH`     | `$SAGE_ROOT/agents`   | Agent 配置目录                    |
| `SAGE_MCP_CONFIG_PATH` | `$SAGE_ROOT/mcp.json` | MCP 服务配置文件路径                  |
| `SAGE_PRESET_RUNNING_CONFIG_PATH` | — | 可选的预置运行配置路径 |


## 3. 用户身份


| 变量                            | 默认值                    | 说明          |
| ----------------------------- | ---------------------- | ----------- |
| `SAGE_DESKTOP_USER_ID`        | `desktop_default_user` | 桌面端默认用户 ID  |
| `SAGE_DESKTOP_USER_ROLE`      | `user`                 | 桌面端默认用户角色   |
| `SAGE_CLI_USER_ID`            | `cli_default_user`     | CLI 默认用户 ID |
| `SAGE_TASK_SCHEDULER_USER_ID` | —                      | 计划任务执行身份    |

## 3.1 服务端认证、Cookie 与 CORS

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `SAGE_AUTH_PROVIDERS` | — | 上游认证 provider JSON 数组 |
| `SAGE_TRUSTED_IDENTITY_PROXY_IPS` | — | 可信身份代理 IP，逗号分隔 |
| `SAGE_BOOTSTRAP_ADMIN_USERNAME` | `admin` | 初始管理员用户名 |
| `SAGE_BOOTSTRAP_ADMIN_PASSWORD` | — | 初始管理员密码 |
| `SAGE_JWT_KEY` | — | JWT 签名密钥 |
| `SAGE_JWT_EXPIRE_HOURS` | `24` | JWT 过期时间（小时） |
| `SAGE_REFRESH_TOKEN_SECRET` | — | refresh token 签名密钥 |
| `SAGE_SESSION_SECRET` | — | 服务端 session 密钥 |
| `SAGE_SESSION_COOKIE_NAME` | `sage_session` | session cookie 名 |
| `SAGE_SESSION_COOKIE_SECURE` | `false` | session cookie 是否仅 HTTPS |
| `SAGE_SESSION_COOKIE_SAME_SITE` | `lax` | session cookie SameSite 策略 |
| `SAGE_CORS_ALLOWED_ORIGINS` | — | CORS 允许来源 |
| `SAGE_CORS_ALLOW_CREDENTIALS` | `true` | CORS 是否允许 credentials |
| `SAGE_CORS_ALLOW_METHODS` | — | CORS 允许方法 |
| `SAGE_CORS_ALLOW_HEADERS` | — | CORS 允许请求头 |
| `SAGE_CORS_EXPOSE_HEADERS` | — | CORS 暴露响应头 |
| `SAGE_CORS_MAX_AGE` | `600` | CORS preflight 缓存时间 |
| `SAGE_WEB_BASE_PATH` | `/` | Web 应用 base path |


## 4. 沙箱与执行


| 变量                                | 默认值           | 说明                                         |
| --------------------------------- | ------------- | ------------------------------------------ |
| `SAGE_SANDBOX_MODE`               | `passthrough` | `passthrough` / `local` / `remote`         |
| `SAGE_REMOTE_PROVIDER`            | —             | 远程沙箱 provider 名                            |
| `SAGE_SANDBOX_MOUNT_PATHS`        | —             | 额外挂载路径，分号/换行分隔                             |
| `SAGE_SANDBOX_RUNTIME_DIR`        | —             | 沙箱运行时目录                                    |
| `SAGE_SHARED_SANDBOX_RUNTIME_DIR` | —             | 共享沙箱运行时根                                   |
| `SAGE_SHARED_PYTHON_ENV`          | `false`       | 是否共享 Python 环境                             |
| `SAGE_SHARED_PYTHON_ENV_DIR`      | —             | 共享 Python venv 目录                          |
| `SAGE_LOCAL_CPU_TIME_LIMIT`       | —             | 本地沙箱 CPU 时限（秒）                             |
| `SAGE_LOCAL_MEMORY_LIMIT_MB`      | —             | 本地沙箱内存上限（MB）                               |
| `SAGE_LOCAL_LINUX_ISOLATION`      | `false`       | Linux 命名空间隔离开关                             |
| `SAGE_LOCAL_MACOS_ISOLATION`      | `false`       | macOS sandbox-exec 隔离开关                    |
| `SAGE_USE_CLAW_MODE`              | `true`        | 是否启用 IDENTITY/AGENT/SOUL/USER/MEMORY md 注入 |
| `SAGE_BUNDLED_NODE_BIN`           | —             | 内置 Node 可执行文件路径（桌面端打包）                     |
| `SAGE_NODE_HOST`                  | —             | 内置 Node 服务地址                               |
| `SAGE_NODE_MODULES_DIR`           | —             | 共享 node_modules 目录                         |
| `SAGE_NODE_PATH`                  | —             | 桌面端内置 Node 模块查找路径 |
| `SAGE_NODE_EXECUTABLE` / `SAGE_NPM_CLI` | — | 桌面端 Node/npm 可执行文件覆盖 |
| `SAGE_PYTHON`                     | —             | 桌面端 / terminal launcher 使用的 Python 可执行文件覆盖 |


### 4.1 OpenSandbox（远程）


| 变量                                     | 默认值 | 说明               |
| -------------------------------------- | --- | ---------------- |
| `OPENSANDBOX_URL`                      | —   | OpenSandbox 服务地址 |
| `OPENSANDBOX_API_KEY`                  | —   | API Key          |
| `OPENSANDBOX_IMAGE`                    | `opensandbox/code-interpreter:v1.0.2` | 默认镜像 |
| `OPENSANDBOX_TIMEOUT`                  | `1800` | 超时时间（秒） |
| `SAGE_OPENSANDBOX_APPEND_MAX_BYTES`    | `262144` | append 接口单次最大字节数 |
| `SAGE_APPEND_PATH` / `SAGE_APPEND_B64` | —   | append 工具内部传参    |

## 4.2 Embedding 默认

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `SAGE_EMBEDDING_API_KEY` | — | Embedding API Key |
| `SAGE_EMBEDDING_BASE_URL` | `https://dashscope.aliyuncs.com/compatible-mode/v1/` | Embedding base URL |
| `SAGE_EMBEDDING_MODEL` | `text-embedding-v4` | Embedding 模型 |
| `SAGE_EMBEDDING_DIMS` | `1024` | 向量维度 |

## 4.3 存储、可观测性与集成

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `SAGE_S3_ENDPOINT` / `SAGE_S3_ACCESS_KEY` / `SAGE_S3_SECRET_KEY` | — | S3 兼容对象存储连接 |
| `SAGE_S3_SECURE` | `false` | S3 兼容存储是否使用 HTTPS |
| `SAGE_S3_BUCKET_NAME` | — | 对象存储 bucket |
| `SAGE_S3_PUBLIC_BASE_URL` | — | 对象公开访问 base URL |
| `SAGE_MYSQL_HOST` / `SAGE_MYSQL_PORT` / `SAGE_MYSQL_USER` / `SAGE_MYSQL_PASSWORD` / `SAGE_MYSQL_DATABASE` | — | MySQL 连接配置 |
| `SAGE_ELASTICSEARCH_URL` / `SAGE_ELASTICSEARCH_API_KEY` / `SAGE_ELASTICSEARCH_USERNAME` / `SAGE_ELASTICSEARCH_PASSWORD` | — | Elasticsearch 连接配置 |
| `SAGE_TRACE_JAEGER_URL` | — | 内部 Jaeger 查询地址 |
| `SAGE_TRACE_JAEGER_ENDPOINT` | — | Jaeger OTLP endpoint |
| `SAGE_TRACE_JAEGER_PUBLIC_URL` | `http://127.0.0.1:30051/jaeger` | 对外 Jaeger 地址 |
| `SAGE_GRAFANA_PUBLIC_URL` | — | 部署环境对外 Grafana 地址 |
| `SAGE_LOKI_PUSH_URL` | — | Loki push endpoint |
| `SAGE_KB_MCP_URL` / `SAGE_KB_MCP_API_KEY` | — | 知识库 MCP 集成 |
| `SAGE_OAUTH2_CLIENTS` / `SAGE_OAUTH2_ISSUER` / `SAGE_OAUTH2_ACCESS_TOKEN_EXPIRES_IN` | — | 内置 OAuth2 provider 配置 |
| `SAGE_EML_ENDPOINT` / `SAGE_EML_ACCESS_KEY_ID` / `SAGE_EML_ACCESS_KEY_SECRET` / `SAGE_EML_SECURITY_TOKEN` | — | 邮件 provider 凭据 |
| `SAGE_EML_ACCOUNT_NAME` / `SAGE_EML_TEMPLATE_ID` / `SAGE_EML_REGISTER_SUBJECT` / `SAGE_EML_ADDRESS_TYPE` / `SAGE_EML_REPLY_TO_ADDRESS` | — | 邮件发送账号 / 模板默认值 |


## 5. Agent 主循环 & Prompt Cache


| 变量                                             | 默认值     | 说明                                                                                                                                                                           |
| ---------------------------------------------- | ------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `SAGE_TASK_COMPLETION_MODE`                    | `turn_status` | SimpleAgent 的任务完成判定模式。`turn_status` 会暴露 `turn_status` 协议工具，由模型报告 `task_done` / `need_user_input` / `blocked` / `continue_work`；`llm_judge` 不暴露 `turn_status`，回退到旧的“规则优先 + LLM `task_complete_judge`”完成判断；`no_tool_call` 不暴露 `turn_status`，当 LLM 输出不包含工具调用时判定本轮完成。 |
| `SAGE_RUNTIME_CONTEXT_IN_USER`                 | `true`  | 将动态 runtime context（`system_context`、workspace files、活跃 ToDo）从 system message 移出，并冻结到最新 user 的 inference metadata 中。仅在兼容旧行为时设为 `false`，此时动态上下文仍进入 system。 |
| `SAGE_CLI_MAX_LOOP_COUNT`                      | —       | CLI 单轮最大循环次数                                                                                                                                                                 |
| `SAGE_CONTEXT_HISTORY_RATIO` / `SAGE_CONTEXT_ACTIVE_RATIO` / `SAGE_CONTEXT_MAX_NEW_MESSAGE_RATIO` / `SAGE_CONTEXT_RECENT_TURNS` | 代码默认值 | 上下文预算分配参数 |
| `SAGE_TOOL_SUGGESTION_DIRECT_THRESHOLD`        | `15`    | 可用工具数小于等于该值时跳过 LLM 工具推荐调用，直接透传所有可用工具                                                                                                                                            |
| `SAGE_EMIT_TOOL_CALL_ON_COMPLETE`              | `true`  | LLM 完整产出后是否补发 tool_call chunk                                                                                                                                                |
| `SAGE_ECHO_SHELL_OUTPUT`                       | `false` | 后台 shell 输出是否回显到主流                                                                                                                                                           |
| `SAGE_FORCE_TOOL_CHOICE_REQUIRED`             | `false` | 是否对所有带 tools 的 LLM 调用强制 `tool_choice=required`。默认关闭，避免 OpenAI o1/o3 等不支持该参数的模型报错；显式设为 `1/true/yes/on` 后启用                                                                 |
| `SAGE_TOOL_PROGRESS_ENABLED`                   | `true`  | 是否启用工具实时过程通道（NDJSON `type=tool_progress` 事件，仅给前端 UI，不进 MessageManager / 不喂 LLM）                                                                                          |
| `SAGE_TOOL_PROGRESS_FLUSH_INTERVAL_MS`         | `50`    | 工具过程合并时间窗（毫秒）。同 `(tool_call, stream)` 维度下窗口内的多次 emit 合并成一条事件下发；设 `0` 关闭合并立即推送                                                                                          |
| `SAGE_TOOL_PROGRESS_FLUSH_BYTES`               | `16384` | 单 stream 累计字节阈值，达到即立即 flush（防极快产生输出的命令挤爆通道）                                                                                                                       |

## 6. Memory


| 变量                             | 默认值     | 说明              |
| ------------------------------ | ------- | --------------- |
| `SAGE_DB_TYPE`                 | —       | 数据库类型           |
| `SAGE_SESSION_MEMORY_BACKEND`  | —       | 会话记忆后端实现        |
| `SAGE_SESSION_MEMORY_STRATEGY` | —       | 会话记忆压缩 / 召回策略   |
| `SAGE_FILE_MEMORY_BACKEND`     | —       | 文件记忆后端实现        |
| `MEMORY_ROOT_PATH`             | —       | 文件记忆根目录         |
| `ENABLE_REDIS_LOCK`            | `false` | 是否启用 Redis 分布式锁 |
| `MEMORY_LOCK_EXPIRE_SECONDS`   | —       | Redis 锁过期时间     |
| `REDIS_URL`                    | —       | Redis 连接串       |


## 7. MCP / AnyTool


| 变量                             | 默认值     | 说明                       |
| ------------------------------ | ------- | ------------------------ |
| `SAGE_DEFAULT_ANYTOOL_TIMEOUT` | —       | AnyTool 调用超时时间           |
| `SAGE_LS_PATH`                 | —       | `list_dir` 工具默认根（mcp 内部） |
| `SAGE_LS_HIDDEN`               | `false` | `list_dir` 是否包含隐藏文件      |
| `SAGE_MCP_PER_CONNECTION_CONCURRENCY` | `100` | 每个 MCP pooled connection 的最大并发调用数 |
| `SAGE_MCP_MAX_CONNECTIONS_PER_SERVER` | `0` | 每个 MCP server 的最大连接数；`0` 表示不固定限制 |
| `SAGE_MCP_SESSION_IDLE_TTL_SECONDS` | `1800` | MCP pooled session 空闲 TTL |
| `SAGE_MCP_REFRESH_DRAIN_TIMEOUT_SECONDS` | `30` | MCP 连接刷新时 draining 宽限时间 |
| `SAGE_MCP_CALL_TIMEOUT_SECONDS` | `1800` | MCP 工具调用超时 |
| `SAGE_MCP_LIST_TOOLS_RETRY_ON_CONNECTION_ERROR` | `true` | MCP `list_tools` 遇到连接类错误时重试一次 |
| `SAGE_MCP_CALL_RETRY_ON_CONNECTION_ERROR` | `true` | MCP 工具调用遇到连接类错误时重试一次 |


## 8. 桌面端 / 安装期


| 变量                        | 默认值     | 说明               |
| ------------------------- | ------- | ---------------- |
| `SAGE_HOST_PID`           | —       | 父进程 PID（用于桌面壳监控） |
| `SAGE_UPDATE_URL`         | —       | 桌面端自动更新地址        |
| `SAGE_INTERNAL_DESKTOP_PROCESS` | — | 桌面端内部进程标记 |
| `SAGE_TERMINAL_BIN` | — | Terminal 二进制覆盖 |
| `SAGE_TERMINAL_CLI` | — | Terminal launcher CLI 覆盖 |
| `SAGE_TERMINAL_RUNTIME_ROOT` | — | Terminal 打包 runtime 根目录 |
| `SAGE_TERMINAL_STATE_ROOT` | — | Terminal 状态根目录 |
| `SAGE_TERMINAL_DEBUG_LAUNCH` | `0` | 打印 terminal launcher 诊断信息 |
| `HOST_WEBDAV_SERVER_ROOT` | —       | 文件服务 WebDAV 根    |
| `ENABLE_DEBUG_WEBDAV`     | `false` | 调试 WebDAV 开关     |


## 9. 开发 / 调试


| 变量                                                                | 默认值     | 说明                 |
| ----------------------------------------------------------------- | ------- | ------------------ |
| `TESTING`                                                         | `false` | 测试模式开关，部分背景任务会跳过   |
| `SAGENTS_PROFILING_TOOL_DECORATOR`                                | `false` | 是否对 @tool 装饰器做调用计时 |
| `SAGE_DISABLE_SAGENTS_FILE_LOGGING`                               | `false` | 关闭 sagents 文件日志 |
| `AGENT_BROWSER_HEADED`                                            | 桌面端 core 中为 `1` | 内置浏览器自动化是否 headed |
| `SAGE_TERMINAL_TEST_PERSIST_PREFERENCES`                          | —       | Terminal 测试专用 preferences 持久化开关 |
| `VITE_SAGE_API_BASE_URL` / `VITE_BACKEND_API_PREFIX` / `VITE_SAGE_GRAFANA_URL` | — | 前端构建 / 运行时 API 地址覆盖 |
| `PYTHON_BIN` / `CONDA_PYTHON_EXE` / `CONDA_PREFIX` / `CONDA_ROOT` | —       | Python 解释器探测，安装期使用 |

## 9.1 已废弃 / 兼容变量

| 变量 | 替代方案 / 状态 |
| --- | --- |
| `SAGE_COMPLETE_ON_NO_TOOL_CALL` | 已移除并忽略。请使用 `SAGE_TASK_COMPLETION_MODE=no_tool_call`。 |
| `SAGE_SPLIT_SYSTEM` | 已废弃且忽略。system message 拆分现在固定开启。 |
| `SAGE_STABLE_TOOLS_ORDER` | 已废弃且忽略。LLM 请求前 tools 固定按 `function.name` 排序。 |
| `SAGE_AUTO_LINT` | 已废弃且忽略。file tool lint 固定开启。 |
| `SAGE_SESSION_DIR_PATH` | `SAGE_SESSION_DIR` 的旧兼容别名，仅 CLI stream 代码读取。 |
| `LLM_API_KEY` / `LLM_API_BASE_URL` / `LLM_MODEL_NAME` | 旧名称；请使用 `SAGE_DEFAULT_LLM_API_KEY` / `SAGE_DEFAULT_LLM_API_BASE_URL` / `SAGE_DEFAULT_LLM_MODEL_NAME`。 |


## 10. 系统标准变量（仅引用，不由 Sage 设置）

`HOME`、`USERPROFILE`、`PATH`、`NODE_PATH`、`SSL_CERT_FILE`：跨平台路径与证书探测时读取，按操作系统语义处理。

---

修改任何上表行为前，先在代码中搜索 `os.environ.get('VARIABLE_NAME')`
确认实际默认值与处理分支，避免与文档表述出现偏差。
