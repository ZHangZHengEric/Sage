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

`sage-terminal` 是 Sage 当前的 Rust 终端 UI 预览版。

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
sage-terminal
sage-terminal --display compact
sage-terminal --display verbose
sage-terminal --agent-id agent_demo
sage-terminal --agent-id agent_demo --agent-mode fibre
sage-terminal --workspace /path/to/project
sage-terminal run "inspect this repo"
sage-terminal --workspace /path/to/project run "inspect this repo"
sage-terminal chat "hello"
sage-terminal config init
sage-terminal config init /tmp/.sage_env --force
sage-terminal doctor
sage-terminal doctor probe-provider
sage-terminal provider verify
sage-terminal provider verify model=deepseek-chat base=https://api.deepseek.com/v1
sage-terminal sessions
sage-terminal sessions 25
sage-terminal sessions inspect latest
sage-terminal sessions inspect <session_id>
sage-terminal resume
sage-terminal resume latest
sage-terminal resume <session_id>
sage-terminal --help
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
- `/goal`
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

## Session 行为

Terminal 现在不会在启动瞬间就立刻占用一个本地 `local-000xxx` session。

- welcome 卡片初始显示的是 `session: new`
- 只有真正提交第一条任务时，才会 materialize 一个本地 session id
- 执行 `/new` 后，也会回到这个待创建的 `new` 状态，直到下一条任务真正提交

这样会更接近 Sage 的 workspace-first 行为，而不是一启动就抢占一个本地 session 编号。

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

## 持久化默认值

Terminal 现在会跨启动记住这些本地默认值：

- 当前选择的 `agent_id`
- 当前选择的 `agent_mode`
- 当前选择的 `display` 模式
- 当前选择的 `workspace` override

像 `/agent set`、`/mode set`、`/display set`、`/workspace set` 这类运行时命令，会同时更新保存下来的默认值。

启动参数仍然优先于已保存默认值。比如你已经保存了 `verbose`，但这次执行：

```bash
sage-terminal --display compact
```

则只会在当前这次启动里使用 `compact`。

## Display 模式

Terminal transcript 现在支持两种展示模式：

- `compact`：默认模式。隐藏内部工具噪音、压缩摘要，并把 phase 名映射成更短的用户视角标签。
- `verbose`：用于排查问题。会恢复内部工具步骤、step 编号和原始 phase 名。

你可以在启动时指定，也可以在 TUI 内切换：

```bash
sage-terminal --display verbose
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

## Goal 控制

Terminal 现在可以携带共享 Sage runtime 的 session goal contract。

```text
/goal
/goal <objective>
/goal show
/goal set <objective>
/goal clear
/goal done
```

`/goal <objective>` 会设置当前会话目标，并立即把同一句 objective 作为下一条任务提交，行为上对齐 Codex 风格。

`/goal set` 仍然只会把目标排入当前 session 的下一次请求，本身不会立刻开始执行；等 backend 再次回传会话初始化事件后，terminal 会显示 runtime 最终解析出来的 goal 状态。

## 输入历史与 Slash Popup

Terminal 输入框现在支持类似 shell 的历史回溯：

- `Up`：回看上一条已提交输入
- `Down`：向前移动，或者恢复当前草稿

Slash 命令 popup 的回车行为也做了收紧：

- 如果 popup 可见，且当前输入还只是命令前缀，`Enter` 会先补全当前选中的命令
- 如果当前输入已经是完整命令，例如 `/interrupt`，`Enter` 会直接执行，而不是再次补全

## 运行控制

现在 terminal 已经支持基础的会话内运行控制：

- `/interrupt`：中断当前正在运行的请求，但不退出 TUI
- `/retry`：在当前 session 里重新执行上一次提交的任务
- 请求运行过程中按 `Ctrl+C`：中断当前请求，而不是直接退出程序

发生中断时，transcript 会尽量保留已经收到的部分输出，并附带 retry 提示，方便继续当前轮次。

## Workspace 行为

默认情况下，`sage-terminal` 不会强制把当前仓库目录透传成 `--workspace`。

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
