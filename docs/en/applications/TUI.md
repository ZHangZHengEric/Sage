---
layout: default
title: TUI Guide
parent: Applications
nav_order: 3
description: "Use Sage Terminal TUI"
lang: en
ref: tui-guide
---

{% include lang_switcher.html %}

# Sage Terminal TUI Guide

`sage tui` is Sage's terminal UI entrypoint. It starts the Rust Terminal TUI through the Sage Python CLI launcher.

This page documents the user-facing command and the source-run workflow used during development.

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

## Install And Run

When Sage is installed from a package that includes the Terminal TUI binary, users start it without installing Rust:

```bash
sage tui
sage tui coding --workspace /path/to/repo
```

The Python CLI acts as a launcher: it finds the packaged Terminal TUI binary and forwards the remaining arguments to it.

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

## Build And Run During Development

```bash
cd app/terminal
cargo build --release
./target/release/sage-terminal
```

The compiled binary is:

- `app/terminal/target/release/sage-terminal`

The compiled binary is an implementation detail for development and packaging. The user-facing entrypoint remains `sage tui`.

## Supported Startup Commands

Currently supported startup forms:

```bash
sage tui
sage tui --display compact
sage tui --display verbose
sage tui --sandbox-type local
sage tui --agent-id agent_demo
sage tui coding --workspace /path/to/project
sage tui coding --sandbox-type local --workspace /path/to/project
sage tui --agent-config coding --workspace /path/to/project
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

When using `cargo run`, pass arguments after `--`:

```bash
cargo run --quiet --offline -- resume
```

## In-App Commands

The current TUI preview includes these core commands:

- `/help`
- `/agent`
- `/mode`
- `/display`
- `/workspace`
- `/sandbox`
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

## Agent Selection

The TUI can override the runtime agent without taking over agent configuration management.

Supported entrypoints:

- startup flags:
  - `--agent-id <id>`
  - `--agent-config <path|coding>`
  - `--agent-mode <simple|multi|fibre>`
  - `--display <compact|verbose>`
- in-app commands:
  - `/agent`
  - `/agent set <agent_id>`
  - `/agent config <path|coding>`
  - `/agent clear`
  - `/mode`
  - `/mode set <simple|multi|fibre>`
  - `/display`
  - `/display set <compact|verbose>`

`/agent set <agent_id>` and `/agent config <path|coding>` are mutually exclusive for the current TUI session. Setting one clears the other so the next backend request uses a single source of agent configuration. At startup, `--agent-config` also takes precedence over `--agent-id` if both are supplied. Agent config paths are session-scoped and are not saved as persistent defaults.

When an agent config is active, the TUI shows it directly as `agent_config: coding` or `agent: config coding`. Config-owned mode and loop settings are shown as `config default`. An explicit startup `--agent-mode` or in-session `/mode set <simple|multi|fibre>` still overrides the config's mode for the current session.

The actual agent definition, tools, skills, and behavior still come from the Sage runtime's stored agent configuration or the explicit `--agent-config` JSON used for this session.

### Coding Agent Preset

The repository includes an importable coding-oriented agent config:

- `examples/coding_agent_config.json`

It enables code search, file read/write, shell, lint, todo, memory search, and webpage fetching tools by default.

The TUI can start the current session directly from this preset; importing it through the Web or desktop app first is not required. Use the built-in `coding` alias for the bundled JSON:

```bash
sage tui coding --workspace /path/to/repo
sage tui --agent-config coding --workspace /path/to/repo
```

`sage tui coding --workspace /path/to/repo` is the direct TUI shortcut. It is equivalent to passing `--agent-config coding`.

The bundled `coding` preset requires an explicit workspace. If you set it inside TUI with `/agent config coding`, also set the repository with `/workspace set /path/to/repo` before sending coding tasks.

The same preset can also be used with the plain CLI:

```bash
sage chat --agent-config coding --workspace /path/to/repo
sage run --agent-config coding --workspace /path/to/repo "inspect this repo"
```

Use the full path, `--agent-config examples/coding_agent_config.json`, when you want to copy and customize the JSON.

If the config has already been saved as an agent, `--agent-id <agent_id>` remains supported.

## Persistent Defaults

The terminal now remembers these local defaults across launches:

- selected `agent_id`
- selected `agent_mode`
- selected `display` mode
- selected `workspace` override

Runtime commands such as `/agent set`, `/mode set`, `/display set`, and `/workspace set` update those saved defaults.

Startup flags still win for the current launch. For example, if you have a saved verbose display mode, running:

```bash
sage tui --display compact
```

will use `compact` only for that invocation.

## Display Modes

Terminal transcript rendering supports two presentation modes:

- `compact`: the default. Internal tool chatter is hidden, summaries are collapsed, and phase names are mapped to shorter user-facing labels.
- `verbose`: restores internal tool steps, step numbers, and raw phase names for debugging.

You can choose the mode either at startup or inside the TUI:

```bash
sage tui --display verbose
```

```text
/display set compact
/display set verbose
```

## Workspace Control

You can inspect or change the current terminal workspace from inside the TUI:

```text
/workspace
/workspace show
/workspace set /path/to/project
/workspace clear
```

## Run Control

The terminal now supports basic in-session run control:

- `/interrupt`: stop the active request without quitting the TUI
- `/retry`: replay the last submitted task in the current session
- `Ctrl+C` while a request is running: interrupt the request instead of exiting

When an interruption happens, the transcript keeps any partial output that already arrived and adds a retry hint so the current turn can be resumed manually.

## Workspace Behavior

By default, `sage tui` does not force the current repository into `--workspace`.

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
