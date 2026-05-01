---
layout: default
title: CLI 使用指南
parent: 应用入口
nav_order: 2
description: "使用 Sage CLI 进行本地开发、验证和会话操作"
lang: zh
ref: cli-guide
---

{% include lang_switcher.html %}

# Sage CLI 使用指南

Sage CLI 是本地验证运行时改动最快的入口，不需要先经过 Web 或桌面端。

本指南聚焦当前 app 层 CLI 入口：

- `sage run`
- `sage chat`
- `sage resume`
- `sage doctor`
- `sage config`
- `sage sessions`
- `sage skills`

## 什么时候用 CLI

适合这些场景：

- 验证本地模型和运行时配置
- 快速执行单次任务
- 继续之前的会话
- 针对指定工作目录测试
- 显式启用某个 skill
- 在开发过程中查看最近会话

## 安装

如果你要获得完整的本地开发 / 运行环境，先安装仓库依赖：

```bash
pip install -r requirements.txt
```

如果你还希望当前仓库直接提供 `sage` 命令入口，再在仓库根目录执行：

```bash
pip install -e .
```

如果你暂时不想安装可编辑包，也可以直接执行：

```bash
python -m app.cli.main --help
```

## 最小配置

CLI 现在默认和 desktop 共用 `~/.sage/` 本地数据目录。

默认行为是：

- 如果存在，先读取 `~/.sage/.sage_env`
- 本地数据默认存到 `~/.sage/`
- 开发时如果仓库内有 `.env`，则再用本地 `.env` 覆盖共享配置

可以通过下面的命令查看实际生效的配置文件和加载顺序：

```bash
sage config show
```

最小可用配置通常是：

```bash
export SAGE_DEFAULT_LLM_API_KEY="your-api-key"
export SAGE_DEFAULT_LLM_API_BASE_URL="https://api.deepseek.com/v1"
export SAGE_DEFAULT_LLM_MODEL_NAME="deepseek-chat"
export SAGE_DB_TYPE="file"
```

也可以直接生成一份最小本地配置：

```bash
sage config init
```

默认会写到：

```text
~/.sage/.sage_env
```

然后查看 CLI 当前实际读取到的配置：

```bash
sage doctor
sage config show
sage config show --json
```

## 用户解析顺序

CLI 保留了用户概念，以便和其它 Sage 应用入口保持一致。

解析顺序为：

1. `--user-id`
2. `SAGE_CLI_USER_ID`
3. `SAGE_DESKTOP_USER_ID`
4. `default_user`

示例：

```bash
sage doctor
sage run --user-id alice --stats "用一句话介绍你自己。"
```

## 核心命令

### `sage doctor`

当 CLI 表现异常时，优先执行这个命令。

它会输出：

- Python 路径
- 当前工作目录
- 实际生效的环境文件路径和是否存在
- auth mode 和 db type
- 当前解析出的 `session_history` 与 `file_memory` memory backend
- 当前解析出的 `session_history` 检索策略
- `agents_dir`、`session_dir`、`logs_dir` 等关键目录
- `session_dir` 下的 SQLite session registry 路径
- 依赖是否可用
- 运行时错误、警告和建议下一步

示例：

```bash
sage doctor
```

### `sage config`

用于查看或生成 CLI 配置。

示例：

```bash
sage config show
sage config show --json
sage config init
sage config init --path ./my-sage.env
sage config init --force
```

`sage config show` 也会展示当前默认解析到的 memory backend：

- `session_history`
- `file_memory`

它也会展示当前默认解析到的 `session_history` 检索策略。

对应的环境变量是：

- `SAGE_SESSION_MEMORY_STRATEGY`

如果 memory backend 或 strategy 配置成了不支持的值，`sage doctor` 和
`sage config show` 也不会直接崩溃，而是会在对应的 `memory_backends.*`
或 `memory_strategies.*` 字段里返回结构化校验错误。

`sage config init` 生成的 env 模板里也会带上注释形式的 memory-search
可选覆盖项，方便在一个文件里调整 backend 或 strategy。

### `sage run`

执行一次单轮请求并输出最终结果。

示例：

```bash
sage run "用一句话介绍你自己。"
sage run --stats "用一句话介绍你自己。"
sage run --json --stats "用一句话介绍你自己。"
sage run --workspace /path/to/project --stats "简单分析一下这个仓库。"
```

常用参数：

- `--user-id`
- `--agent-id`
- `--agent-mode`
- `--workspace`
- `--skill`（可重复）
- `--max-loop-count`
- `--json`
- `--stats`
- `--verbose`

### `sage chat`

启动一个本地交互式会话。

说明：
- `sage chat` 按单行输入工作；一次粘贴多行内容会被视为多轮输入。
- 如果不传 `--workspace`，写文件类工具会使用默认 agent workspace：`~/.sage/agents/<user>/<agent_id>/...`。

示例：

```bash
sage chat
sage chat --stats
sage chat --workspace /path/to/project
sage chat --skill my_skill
```

内置命令：

- `/help`：查看内置命令帮助
- `/session`：输出当前 session id
- `/exit`：退出会话
- `/quit`：退出会话的兼容别名

### `sage resume`

通过 session id 恢复一个已有会话。

示例：

```bash
sage resume <session_id>
sage resume --stats <session_id>
sage resume --workspace /path/to/project <session_id>
```

如果当前数据库里有该会话的元信息，CLI 会在进入会话前先打印一段简短摘要。

### `sage sessions`

查看当前 CLI 用户最近的会话。

示例：

```bash
sage sessions
sage sessions --json
sage sessions --limit 10
sage sessions --search debug
sage sessions --agent-id my-agent
```

查看某个具体会话的详情：

```bash
sage sessions inspect <session_id>
sage sessions inspect latest
sage sessions inspect --json <session_id>
sage sessions inspect --agent-id my-agent latest
sage sessions inspect --messages 8 <session_id>
```

`inspect` 视图会输出：

- 会话摘要信息，例如标题、agent、时间戳、消息数
- 最近一条用户消息和助手消息摘要（如果存在）
- 最近几条消息预览
- 可选的 JSON 输出，便于调试和脚本处理

### `sage skills`

查看 CLI 当前可见的 skills。

示例：

```bash
sage skills
sage skills --json
sage skills --workspace /path/to/project
sage skills --agent-id my-agent
```

输出会包含：

- 当前用户 id
- 可选的 agent id
- 可选的 workspace
- 当前可见 skill 总数
- 每个 source 下的数量
- skill 名称和描述
- source 层面的错误信息（如果有）

当传入 `--agent-id` 时，CLI 会按当前 Agent 实际可用的 skill 集合来展示结果，而不是只看本地可见 skill。

### `sage provider`

通过 CLI 查看和管理本地 LLM Provider。

当前支持的子命令：

- `list`
- `inspect`
- `verify`
- `create`
- `update`
- `delete`

示例：

```bash
sage provider list
sage provider list --default-only
sage provider list --model deepseek-chat
sage provider list --name-contains deepseek

sage provider inspect <provider_id>

sage provider verify --base-url https://api.deepseek.com/v1 --model deepseek-chat --api-key <key>
sage provider verify --json
sage provider verify --base-url https://api.deepseek.com/v1 --model deepseek-chat --api-key <key> --json

sage provider create --user-id alice --base-url https://api.deepseek.com/v1 --model deepseek-chat --api-key <key> --set-default
sage provider create --user-id alice --name "CLI Default Provider" --json

sage provider update <provider_id> --user-id alice --model deepseek-reasoner
sage provider update <provider_id> --user-id alice --set-default

sage provider delete <provider_id> --user-id alice
```

需要注意的行为：

- `verify` 只做连通性探测，不会保存。
- `create` 和 `update` 都要求 probe 成功后才允许保存。
- `create` / `verify` 如果没有传 `--base-url`、`--api-key`、`--model`，会回退到当前 CLI 环境里的默认值。
- 如果这些默认值本身缺失，`create` / `verify` 会直接返回 CLI 错误，并给出明确的下一步提示。
- `update` 会拒绝空的 `--api-key`，如果没有传任何可更新字段，也会直接失败。
- CLI 输出会对 API key 做脱敏，只显示简短预览。
- 同一个用户最多只能有一个默认 provider；把某个 provider 设成默认时，会自动清掉该用户下其他 provider 的默认标记。
- `delete` 仍然不允许删除当前默认 provider。

## CLI 中的 Skill

CLI 现在支持在这些命令上显式传入 skill：

- `run`
- `chat`
- `resume`

示例：

```bash
sage run --skill my_skill --stats "用一句话介绍你自己。"
sage run --skill my_skill --skill another_skill --max-loop-count 5 --stats "用一句话介绍你自己。"
sage chat --skill my_skill
```

如果传入的 skill 当前不可见，CLI 会在进入运行时之前直接失败，并提示你先执行 `sage skills` 查看当前可见 skill。

## 结构化输出

对开发和调试来说，有两种很有用的输出模式：

### `--stats`

命令执行完成后，追加一段面向人的执行摘要。

当前摘要包含：

- `session_id`
- `user_id`
- `agent_id`
- `agent_mode`
- `workspace`
- `requested_skills`
- `max_loop_count`
- 总耗时
- 首次输出耗时
- 使用到的工具
- token 使用情况
- 如果可用，还会输出每个 step 的 usage

### `--json`

以结构化流事件的方式输出，而不是仅输出纯文本。

现在的 JSON 流可以分成四层：

- 会话初始化事件：`cli_session`
- 原始运行时事件，例如 `assistant`、`analysis`、`tool_call`、`tool_result`
- CLI 控制事件，例如 `cli_phase` 和 `cli_tool`
- 如果启用了 `--stats`，结尾追加一个 `cli_stats` 事件

建议按下面这套 contract 来消费：

- `cli_session`：在流式运行输出前先发出，包含最终解析后的 `session_id`、`command_mode`、`session_state`、`user_id`、`agent_id`、`agent_mode`、`workspace`、`workspace_source`、requested skills、`max_loop_count`、`has_prior_messages`、`prior_message_count`，以及用于 resume hydration 的可选 `session_summary`
- `cli_phase`：CLI 检测到阶段切换时发出，例如 `planning`、`tool`、`assistant_text`
- `cli_tool`：工具 step 开始或结束时发出，包含 `action`、`step`、`tool_name`、`tool_call_id`、`status`
- `cli_stats`：只在结束时发出一次，包含最终 `tool_steps`、`phase_timings`、时延摘要和 token 摘要

对前端消费者来说，`cli_session`、`cli_phase` 和 `cli_tool` 应该作为首选的 UI contract；原始 `tool_call` / `tool_result` 更适合作为兼容输入，而不是主要展示协议。`cli_session.session_id` 从首个事件开始就应该是稳定的，即使这次请求没有显式传 `--session-id` 也是如此。`session_state`、`has_prior_messages` 和 `prior_message_count` 用来让前端直接判断这是新会话还是接在已有会话上，而不必自己再从 `command_mode` 和 `session_summary` 里推断。如果传了 `--workspace`，事件里输出的 `workspace` 也应该是 backend 实际使用的规范化绝对路径。

当和 `--stats` 一起使用时，CLI 会在结尾追加一个 `cli_stats` JSON 事件：

```bash
sage run --json --stats "用一句话介绍你自己。"
```

这适合：

- shell 脚本处理
- 对比不同运行结果
- 抽取 token usage
- 在首个 assistant chunk 到来前先初始化 UI 状态
- 判断 tool/skill 是否真的生效

如果想看一份完整的端到端示例，可以参考 `tests/app/cli/fixtures/stream_contract_round_trip.jsonl`。

## Workspace 用法

使用 `--workspace` 可以让 CLI 针对指定本地目录工作：

```bash
sage run --workspace /path/to/project --stats "简单分析一下这个仓库。"
sage chat --workspace /path/to/project
sage resume --workspace /path/to/project <session_id>
sage skills --workspace /path/to/project
```

这对文件型任务和 workspace 下 `skills/` 目录的发现尤其有用。

如果不传 `--workspace`，交互式 chat 或写文件类任务会落到默认 agent workspace：`~/.sage/agents/<user>/<agent_id>/...`，而不是当前仓库目录。

## 推荐冒烟测试

想快速验证本地 CLI 是否可用，可以执行：

```bash
sage doctor
sage config show
sage skills
sage run --stats "用一句话介绍你自己。"
sage run --json --stats "用一句话介绍你自己。"
```

重点检查：

- doctor 是否显示运行时健康
- config 是否和你的预期一致
- skills 是否反映当前本地可见 skill
- stats 是否带上了正确的 user/workspace/skill 上下文
- JSON 模式是否先发出了 `cli_session`，并在运行中发出 `cli_phase` / `cli_tool`
- JSON 模式最后是否有 `cli_stats` 事件

## 维护者验证

如果你改了 provider 管理或 CLI 错误处理，建议再跑一遍真实集成测试：

```bash
/opt/miniconda3/envs/sage_dev/bin/python tests/app/cli/test_provider_integration.py
```

说明：

- 默认系统 Python 如果缺少 `sqlalchemy`、`aiosqlite` 或 `loguru`，这个用例会被跳过
- 这个测试会基于临时 file DB 走一遍 `provider create -> inspect -> update -> delete`
- 同时会校验默认 provider 切换，以及认证失败、模型不存在、超时这几类 probe 错误的友好 JSON 输出

## 相关文档

- [快速开始](GETTING_STARTED.md)
- [配置](CONFIGURATION.md)
- [应用入口](README.md)
- [故障排查](TROUBLESHOOTING.md)
