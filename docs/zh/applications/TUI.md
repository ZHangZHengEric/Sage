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
sage-terminal --agent-id agent_demo
sage-terminal --agent-id agent_demo --agent-mode fibre
sage-terminal run "inspect this repo"
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
- TUI 内命令：
  - `/agent`
  - `/agent set <agent_id>`
  - `/agent clear`
  - `/mode`
  - `/mode set <simple|multi|fibre>`

真正的 agent 定义、工具、skills 和行为仍然来自 Sage runtime 已保存的 agent 配置。

## 当前定位

这版 TUI 当前主要用于：

- 本地开发
- 预览试用
- 验证终端工作流

目前还不包含打包安装和二进制分发说明。
