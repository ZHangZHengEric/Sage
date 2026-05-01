---
layout: default
title: TUI Guide
parent: Applications
nav_order: 3
description: "Run the Rust Sage Terminal preview from source"
lang: en
ref: tui-guide
---

{% include lang_switcher.html %}

# Sage Terminal TUI Guide

`sage-terminal` is the Rust terminal UI preview for Sage.

This page documents the current source-run workflow. It is not packaged yet.

## What It Depends On

The TUI is a frontend shell over the existing Sage runtime:

- Rust handles terminal rendering and interaction
- the local Sage Python CLI/backend handles runtime execution
- session data is shared with the normal Sage CLI under `~/.sage/`
- runtime workspace also defaults to the normal Sage CLI location under `~/.sage/...`

That means you should treat the TUI as another local Sage entry surface, not as a separate agent stack.

## Prerequisites

From the repository root, make sure the local Python CLI is available:

```bash
pip install -e .
```

Set the minimum runtime configuration:

```bash
export SAGE_DEFAULT_LLM_API_KEY="your-api-key"
export SAGE_DEFAULT_LLM_API_BASE_URL="https://api.deepseek.com/v1"
export SAGE_DEFAULT_LLM_MODEL_NAME="deepseek-chat"
export SAGE_DB_TYPE="file"
```

If the normal CLI is not ready, fix that first:

```bash
sage doctor
```

## Run From Source

From the repository root:

```bash
cargo run --quiet --offline --manifest-path app/terminal/Cargo.toml
```

Or from the crate directory:

```bash
cd app/terminal
cargo run --quiet --offline
```

## Build And Run

```bash
cd app/terminal
cargo build --release
./target/release/sage-terminal
```

The compiled binary is:

- `app/terminal/target/release/sage-terminal`

## Supported Startup Commands

Currently supported startup forms:

```bash
sage-terminal
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

When using `cargo run`, pass arguments after `--`:

```bash
cargo run --quiet --offline -- resume
```

## In-App Commands

The current TUI preview includes these core commands:

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

## Agent Selection

The TUI can override the runtime agent without taking over agent configuration management.

Supported entrypoints:

- startup flags:
  - `--agent-id <id>`
  - `--agent-mode <simple|multi|fibre>`
- in-app commands:
  - `/agent`
  - `/agent set <agent_id>`
  - `/agent clear`
  - `/mode`
  - `/mode set <simple|multi|fibre>`

The actual agent definition, tools, skills, and behavior still come from the Sage runtime's stored agent configuration.

## Workspace Behavior

By default, `sage-terminal` does not force the current repository into `--workspace`.

That means:

- normal terminal sessions keep using the default Sage workspace under `~/.sage/...`
- files such as `AGENT.md`, `MEMORY.md`, and `.sage-docs` are only created inside a repository when you explicitly pass `--workspace <path>`

Use `--workspace` when you intentionally want repo-local file access and workspace-local skill discovery.

## Current Scope

The current TUI is intended for:

- local development
- preview usage
- validating terminal-first workflows

It does not yet document packaged installation or binary distribution.
