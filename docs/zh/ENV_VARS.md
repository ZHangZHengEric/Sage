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

## 1. LLM 与默认模型

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `SAGE_DEFAULT_LLM_API_KEY` | — | 默认模型 API Key（OpenAI 兼容） |
| `SAGE_DEFAULT_LLM_API_BASE_URL` | — | 默认模型 base URL |
| `SAGE_DEFAULT_LLM_MODEL_NAME` | — | 默认模型名 |

## 2. 服务端口与目录

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `SAGE_HOST` | `0.0.0.0` | 服务端监听地址 |
| `SAGE_PORT` | `8001`（server）/ 桌面端动态 | 服务端口 |
| `SAGE_ROOT` | `~/.sage` | 全局根目录，下设 sessions/agents/logs |
| `SAGE_SESSIONS_PATH` | `$SAGE_ROOT/sessions` | 会话持久化目录 |
| `SAGE_AGENTS_PATH` | `$SAGE_ROOT/agents` | Agent 配置目录 |
| `SAGE_MCP_CONFIG_PATH` | `$SAGE_ROOT/mcp.json` | MCP 服务配置文件路径 |

## 3. 用户身份

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `SAGE_DESKTOP_USER_ID` | `desktop_default_user` | 桌面端默认用户 ID |
| `SAGE_DESKTOP_USER_ROLE` | `user` | 桌面端默认用户角色 |
| `SAGE_CLI_USER_ID` | `cli_default_user` | CLI 默认用户 ID |
| `SAGE_TASK_SCHEDULER_USER_ID` | — | 计划任务执行身份 |

## 4. 沙箱与执行

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `SAGE_SANDBOX_MODE` | `passthrough` | `passthrough` / `local` / `remote` |
| `SAGE_REMOTE_PROVIDER` | — | 远程沙箱 provider 名 |
| `SAGE_SANDBOX_MOUNT_PATHS` | — | 额外挂载路径，分号/换行分隔 |
| `SAGE_SANDBOX_RUNTIME_DIR` | — | 沙箱运行时目录 |
| `SAGE_SHARED_SANDBOX_RUNTIME_DIR` | — | 共享沙箱运行时根 |
| `SAGE_SHARED_PYTHON_ENV` | `false` | 是否共享 Python 环境 |
| `SAGE_SHARED_PYTHON_ENV_DIR` | — | 共享 Python venv 目录 |
| `SAGE_LOCAL_CPU_TIME_LIMIT` | — | 本地沙箱 CPU 时限（秒） |
| `SAGE_LOCAL_MEMORY_LIMIT_MB` | — | 本地沙箱内存上限（MB） |
| `SAGE_LOCAL_LINUX_ISOLATION` | `false` | Linux 命名空间隔离开关 |
| `SAGE_LOCAL_MACOS_ISOLATION` | `false` | macOS sandbox-exec 隔离开关 |
| `SAGE_USE_CLAW_MODE` | `true` | 是否启用 IDENTITY/AGENT/SOUL/USER/MEMORY md 注入 |
| `SAGE_BUNDLED_NODE_BIN` | — | 内置 Node 可执行文件路径（桌面端打包） |
| `SAGE_NODE_HOST` | — | 内置 Node 服务地址 |
| `SAGE_NODE_MODULES_DIR` | — | 共享 node_modules 目录 |

### 4.1 OpenSandbox（远程）

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `OPENSANDBOX_URL` | — | OpenSandbox 服务地址 |
| `OPENSANDBOX_API_KEY` | — | API Key |
| `OPENSANDBOX_IMAGE` | — | 默认镜像 |
| `OPENSANDBOX_TIMEOUT` | — | 超时时间（秒） |
| `SAGE_OPENSANDBOX_APPEND_MAX_BYTES` | — | append 接口单次最大字节数 |
| `SAGE_APPEND_PATH` / `SAGE_APPEND_B64` | — | append 工具内部传参 |

## 5. Agent 主循环 & Prompt Cache

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `SAGE_AGENT_STATUS_PROTOCOL_ENABLED` | `true` | 是否启用 Agent 本轮状态协议（注入 `turn_status` 并要求模型显式报告状态） |
| `SAGE_CLI_MAX_LOOP_COUNT` | — | CLI 单轮最大循环次数 |
| `SAGE_SPLIT_SYSTEM` | `true` | 是否把 system message 拆成 stable / semi_stable / volatile 多段以提升 prompt cache 命中 |
| `SAGE_STABLE_TOOLS_ORDER` | `true` | 是否对 `tools` 字段按 name 字典序排序，稳定 cache key |
| `SAGE_AUTO_LINT` | `true` | `file_write/file_update` 完成后是否自动 lint 并 inline 返回诊断 |
| `SAGE_EMIT_TOOL_CALL_ON_COMPLETE` | `true` | LLM 完整产出后是否补发 tool_call chunk |
| `SAGE_ECHO_SHELL_OUTPUT` | `false` | 后台 shell 输出是否回显到主流 |
| `SAGE_FORCE_TOOL_CHOICE_REQUIRED` | `false` | 是否对所有带 tools 的 LLM 调用强制 `tool_choice=required`。默认关闭，避免 OpenAI o1/o3 等不支持该参数的模型报错；显式设为 `1/true/yes/on` 后启用 |
| `SAGE_TOOL_PROGRESS_ENABLED` | `true` | 是否启用工具实时过程通道（NDJSON `type=tool_progress` 事件，仅给前端 UI，不进 MessageManager / 不喂 LLM） |
| `SAGE_TOOL_PROGRESS_FLUSH_INTERVAL_MS` | `50` | 工具过程合并时间窗（毫秒）。同 `(tool_call, stream)` 维度下窗口内的多次 emit 合并成一条事件下发；设 `0` 关闭合并立即推送 |
| `SAGE_TOOL_PROGRESS_FLUSH_BYTES` | `16384` | 单 stream 累计字节阈值，达到即立即 flush（防极快产生输出的命令挤爆通道） |

## 6. Memory

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `SAGE_DB_TYPE` | — | 数据库类型 |
| `SAGE_SESSION_MEMORY_BACKEND` | — | 会话记忆后端实现 |
| `SAGE_SESSION_MEMORY_STRATEGY` | — | 会话记忆压缩 / 召回策略 |
| `SAGE_FILE_MEMORY_BACKEND` | — | 文件记忆后端实现 |
| `MEMORY_ROOT_PATH` | — | 文件记忆根目录 |
| `ENABLE_REDIS_LOCK` | `false` | 是否启用 Redis 分布式锁 |
| `MEMORY_LOCK_EXPIRE_SECONDS` | — | Redis 锁过期时间 |
| `REDIS_URL` | — | Redis 连接串 |

## 7. MCP / AnyTool

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `SAGE_DEFAULT_ANYTOOL_TIMEOUT` | — | AnyTool 调用超时时间 |
| `SAGE_LS_PATH` | — | `list_dir` 工具默认根（mcp 内部） |
| `SAGE_LS_HIDDEN` | `false` | `list_dir` 是否包含隐藏文件 |

## 8. 桌面端 / 安装期

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `SAGE_HOST_PID` | — | 父进程 PID（用于桌面壳监控） |
| `SAGE_UPDATE_URL` | — | 桌面端自动更新地址 |
| `HOST_WEBDAV_SERVER_ROOT` | — | 文件服务 WebDAV 根 |
| `ENABLE_DEBUG_WEBDAV` | `false` | 调试 WebDAV 开关 |

## 9. 开发 / 调试

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `TESTING` | `false` | 测试模式开关，部分背景任务会跳过 |
| `SAGENTS_PROFILING_TOOL_DECORATOR` | `false` | 是否对 @tool 装饰器做调用计时 |
| `PYTHON_BIN` / `CONDA_PYTHON_EXE` / `CONDA_PREFIX` / `CONDA_ROOT` | — | Python 解释器探测，安装期使用 |

## 10. 系统标准变量（仅引用，不由 Sage 设置）

`HOME`、`USERPROFILE`、`PATH`、`NODE_PATH`、`SSL_CERT_FILE`：跨平台路径与证书探测时读取，按操作系统语义处理。

---

修改任何上表行为前，先在代码中搜索 `os.environ.get('VARIABLE_NAME')`
确认实际默认值与处理分支，避免与文档表述出现偏差。
