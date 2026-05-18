---
layout: default
title: TUI 使用指南
parent: 应用入口
nav_order: 3
description: "从源码运行 Rust 版 Sage Terminal 预览"
lang: zh
ref: tui-guide
---

{% include lang_switcher.html %}

# Sage Terminal TUI 使用指南

`sage tui` 是 Sage 当前的 Rust 终端 UI 预览入口；底层二进制仍然叫 `sage-terminal`。

本文档只说明当前的源码运行方式，不涉及打包安装。

## 它依赖什么

TUI 不是另一套独立智能体实现，而是现有 Sage runtime 的终端前端：

- Rust 负责终端渲染和交互
- 本仓库里的 Sage Python CLI/backend 负责真正运行
- 会话数据与普通 Sage CLI 共用 `~/.sage/`
- runtime workspace 默认也沿用普通 Sage CLI 的 `~/.sage/...`

所以更准确地说，它是 Sage 的另一个本地使用入口，不是单独一套 agent。

## 前置条件

先在仓库根目录让本地 Python CLI 可用：

```bash
pip install -e .
```

再准备最小运行配置：

```bash
export SAGE_DEFAULT_LLM_API_KEY="your-api-key"
export SAGE_DEFAULT_LLM_API_BASE_URL="https://api.deepseek.com/v1"
export SAGE_DEFAULT_LLM_MODEL_NAME="deepseek-chat"
export SAGE_DB_TYPE="file"
```

如果普通 CLI 还没准备好，先检查它：

```bash
sage doctor
```

## 从源码运行

在仓库根目录执行：

```bash
cargo run --quiet --offline --manifest-path app/terminal/Cargo.toml
```

或者进入 crate 目录执行：

```bash
cd app/terminal
cargo run --quiet --offline
```

## 构建并运行二进制

```bash
cd app/terminal
cargo build --release
./target/release/sage-terminal
```

编译后的二进制位置是：

- `app/terminal/target/release/sage-terminal`

## 当前支持的启动方式

目前支持这些启动形式：

```bash
sage tui
sage tui --display compact
sage tui --display verbose
sage tui --agent-id agent_demo
sage tui --agent-config coding
sage tui --agent-id agent_demo --agent-mode fibre
sage tui --workspace /path/to/project
sage tui run "inspect this repo"
sage tui --workspace /path/to/project run "inspect this repo"
sage tui chat "hello"
sage tui config init
sage tui config init /tmp/.sage_env --force
sage tui doctor
sage tui doctor probe-provider
sage tui provider verify
sage tui provider verify model=deepseek-chat base=https://api.deepseek.com/v1
sage tui sessions
sage tui sessions 25
sage tui sessions inspect latest
sage tui sessions inspect <session_id>
sage tui resume
sage tui resume latest
sage tui resume <session_id>
sage tui --help
```

如果通过 `cargo run` 传参数，记得在中间加 `--`：

```bash
cargo run --quiet --offline -- resume
```

## TUI 内置命令

当前这版预览主要包含这些命令：

- `/help`
- `/agent`
- `/mode`
- `/display`
- `/workspace`
- `/interrupt`
- `/retry`
- `/new`
- `/sessions`
- `/resume`
- `/skills`
- `/skill`
- `/config`
- `/doctor`
- `/providers`
- `/provider`
- `/model`
- `/status`
- `/transcript`
- `/welcome`
- `/exit`

## Agent 选择

TUI 现在可以覆盖运行时使用的 agent，但不会自己接管 agent 配置管理。

目前支持：

- 启动参数：
  - `--agent-id <id>`
  - `--agent-mode <simple|multi|fibre>`
  - `--display <compact|verbose>`
- TUI 内命令：
  - `/agent`
  - `/agent set <agent_id>`
  - `/agent clear`
  - `/mode`
  - `/mode set <simple|multi|fibre>`
  - `/display`
  - `/display set <compact|verbose>`

真正的 agent 定义、工具、skills 和行为仍然来自 Sage runtime 已保存的 agent 配置。

### Coding Agent 预设

仓库提供了一个可导入的 coding 场景 Agent 配置：

- `examples/preset_running_coding_agent_config.json`

它面向仓库代码阅读、终端调试、文件编辑、代码 review 和迭代验证，行为参考 Codex CLI：读取仓库指引、保护脏工作区、做最小根因修复，并用最小相关检查验证。配置里的 `systemContext` 分成几块：

- `codexCliDesignReference`：记录 Codex CLI 到 Sage TUI 的设计映射，包括 profile-like 配置、workspace-oriented 执行、工具 allow-list、search/edit/verify loop、轻量 planning、review mode 和 context management。
- `codingAgentOperatingContract`：把启动检查、planning、编辑、命令执行、验证、review 和最终回复拆成更明确的行为规则。
- `sageToolPlaybook`：说明如何优先使用 Sage 已有工具，比如 `grep`、`glob`、`list_dir`、`file_update`、`execute_shell_command`、`await_shell`、`read_lints`、`todo_write` 和 `search_memory`。

它也说明 Codex 的 sandbox、approval、config layering、MCP approval、apply_patch 等 runtime 能力在当前 Sage JSON 预设里只能作为软约束。这个预设默认启用代码搜索、文件读写、shell、lint、todo、记忆搜索和网页抓取等工具。

TUI 可以直接从这个预设启动本次会话，不需要先去 Web 或桌面端导入。内置 JSON 可以用 `coding` 短别名：

```bash
sage tui --agent-config coding --workspace /path/to/repo
```

同一个预设也可以直接用于普通 CLI：

```bash
sage chat --agent-config coding --workspace /path/to/repo
sage run --agent-config coding --workspace /path/to/repo "inspect this repo"
```

如果要复制并自定义 JSON，仍然可以使用完整路径：`--agent-config examples/preset_running_coding_agent_config.json`。

如果已经把配置保存成 Agent，也可以继续用 `--agent-id <agent_id>` 选择已保存的 Agent。

## 持久化默认值

Terminal 现在会跨启动记住这些本地默认值：

- 当前选择的 `agent_id`
- 当前选择的 `agent_mode`
- 当前选择的 `display` 模式
- 当前选择的 `workspace` override

像 `/agent set`、`/mode set`、`/display set`、`/workspace set` 这类运行时命令，会同时更新保存下来的默认值。

启动参数仍然优先于已保存默认值。比如你已经保存了 `verbose`，但这次执行：

```bash
sage tui --display compact
```

则只会在当前这次启动里使用 `compact`。

## Display 模式

Terminal transcript 现在支持两种展示模式：

- `compact`：默认模式。隐藏内部工具噪音、压缩摘要，并把 phase 名映射成更短的用户视角标签。
- `verbose`：用于排查问题。会恢复内部工具步骤、step 编号和原始 phase 名。

你可以在启动时指定，也可以在 TUI 内切换：

```bash
sage tui --display verbose
```

```text
/display set compact
/display set verbose
```

## Workspace 控制

你现在可以直接在 TUI 内查看或切换当前 workspace：

```text
/workspace
/workspace show
/workspace set /path/to/project
/workspace clear
```

## 运行控制

现在 terminal 已经支持基础的会话内运行控制：

- `/interrupt`：中断当前正在运行的请求，但不退出 TUI
- `/retry`：在当前 session 里重新执行上一次提交的任务
- 请求运行过程中按 `Ctrl+C`：中断当前请求，而不是直接退出程序

发生中断时，transcript 会尽量保留已经收到的部分输出，并附带 retry 提示，方便继续当前轮次。

## Workspace 行为

默认情况下，`sage tui` 不会强制把当前仓库目录透传成 `--workspace`。

这意味着：

- 普通终端会话继续使用 `~/.sage/...` 下的默认 Sage workspace
- `AGENT.md`、`MEMORY.md`、`.sage-docs` 这类文件，只有在你显式传入 `--workspace <path>` 时才会写进仓库目录

只有当你明确需要 repo-local 文件访问或 workspace-local skill 发现时，才建议传 `--workspace`。

## 当前定位

这版 TUI 当前主要用于：

- 本地开发
- 预览试用
- 验证终端工作流

目前还不包含打包安装和二进制分发说明。
