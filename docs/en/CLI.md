---
layout: default
title: CLI Guide
nav_order: 3
description: "Use the Sage CLI for local development, validation, and session workflows"
lang: en
ref: cli-guide
---

{% include lang_switcher.html %}

# Sage CLI Guide

The Sage CLI is the fastest way to validate local runtime changes without going through the web or desktop surfaces.

This guide focuses on the current app-level CLI entrypoint:

- `sage run`
- `sage chat`
- `sage resume`
- `sage doctor`
- `sage config`
- `sage sessions`
- `sage skills`

## When To Use The CLI

Use the CLI when you want to:

- verify local model/runtime configuration
- run a one-off task quickly
- keep working in a previous session
- test a specific workspace
- enable a skill explicitly
- inspect recent sessions during development

## Install

From the repository root:

```bash
pip install -e .
```

If you do not want to install an editable package yet, you can also use:

```bash
python -m app.cli.main --help
```

## Minimum Configuration

The CLI still uses the existing Sage runtime configuration model. The simplest usable setup is:

```bash
export SAGE_DEFAULT_LLM_API_KEY="your-api-key"
export SAGE_DEFAULT_LLM_API_BASE_URL="https://api.deepseek.com/v1"
export SAGE_DEFAULT_LLM_MODEL_NAME="deepseek-chat"
export SAGE_DB_TYPE="file"
```

You can also initialize a minimal local config file:

```bash
sage config init
```

Then inspect what the CLI is actually using:

```bash
sage doctor
sage config show
sage config show --json
```

## User Resolution

The CLI keeps a user concept for consistency with other Sage application surfaces.

Resolution order:

1. `--user-id`
2. `SAGE_CLI_USER_ID`
3. `SAGE_DESKTOP_USER_ID`
4. `default_user`

Examples:

```bash
sage doctor
sage run --user-id alice --stats "Say hello briefly."
```

## Core Commands

### `sage doctor`

Use this first when the CLI does not behave as expected.

It reports:

- Python path
- current working directory
- `.env` path and existence
- auth mode and DB type
- important directories such as `agents_dir`, `session_dir`, and `logs_dir`
- dependency availability
- runtime errors, warnings, and suggested next steps

Example:

```bash
sage doctor
```

### `sage config`

Inspect or generate CLI configuration.

Examples:

```bash
sage config show
sage config show --json
sage config init
sage config init --path ./my-sage.env
sage config init --force
```

### `sage run`

Run a single request and print the final response.

Examples:

```bash
sage run "Say hello briefly."
sage run --stats "Say hello briefly."
sage run --json --stats "Say hello briefly."
sage run --workspace /path/to/project --stats "Analyze this repository briefly."
```

Useful options:

- `--user-id`
- `--agent-id`
- `--agent-mode`
- `--workspace`
- `--skill` (repeatable)
- `--max-loop-count`
- `--json`
- `--stats`
- `--verbose`

### `sage chat`

Start an interactive local chat session.

Examples:

```bash
sage chat
sage chat --stats
sage chat --workspace /path/to/project
sage chat --skill my_skill
```

Built-in chat commands:

- `/help`: show built-in commands
- `/session`: print the current session id
- `/exit`: leave the session
- `/quit`: compatibility alias for leaving the session

### `sage resume`

Resume an existing session by id.

Examples:

```bash
sage resume <session_id>
sage resume --stats <session_id>
sage resume --workspace /path/to/project <session_id>
```

When session metadata is available, the CLI prints a short summary before entering the session.

### `sage sessions`

List recent sessions for the current CLI user.

Examples:

```bash
sage sessions
sage sessions --json
sage sessions --limit 10
sage sessions --search debug
sage sessions --agent-id my-agent
```

### `sage skills`

Inspect skills currently visible to the CLI.

Examples:

```bash
sage skills
sage skills --json
sage skills --workspace /path/to/project
```

The output includes:

- current user id
- optional workspace
- total visible skills
- per-source counts
- skill names and descriptions
- source-level errors, if any

## Skills In CLI

The CLI now supports explicit skill selection on:

- `run`
- `chat`
- `resume`

Examples:

```bash
sage run --skill my_skill --stats "Say hello briefly."
sage run --skill my_skill --skill another_skill --max-loop-count 5 --stats "Say hello briefly."
sage chat --skill my_skill
```

If a requested skill is not visible, the CLI fails early and tells you to inspect the current skill set with `sage skills`.

## Structured Output

There are two useful output modes for development work:

### `--stats`

Adds a human-readable execution summary after the command finishes.

The current summary includes:

- `session_id`
- `user_id`
- `agent_id`
- `agent_mode`
- `workspace`
- `requested_skills`
- `max_loop_count`
- elapsed time
- first output time
- tools used
- token usage
- per-step usage when available

### `--json`

Prints structured stream events instead of plain text.

When used together with `--stats`, the CLI appends a final `cli_stats` JSON event for post-run analysis:

```bash
sage run --json --stats "Say hello briefly."
```

This is useful for:

- shell scripting
- comparing runs
- extracting token usage
- checking whether tools or skills were actually used

## Workspace Usage

Use `--workspace` when you want the CLI to operate against a specific local directory:

```bash
sage run --workspace /path/to/project --stats "Analyze this repository briefly."
sage chat --workspace /path/to/project
sage resume --workspace /path/to/project <session_id>
sage skills --workspace /path/to/project
```

This is especially useful for file-oriented agent tasks and skill discovery under a workspace-specific `skills/` directory.

## Recommended Smoke Test

For a quick local CLI validation, run:

```bash
sage doctor
sage config show
sage skills
sage run --stats "Say hello briefly."
sage run --json --stats "Say hello briefly."
```

Then verify:

- doctor reports a valid runtime
- config values look correct
- skills output matches what is visible locally
- stats include the expected user/workspace/skill context
- JSON mode ends with a `cli_stats` event

## Related Docs

- [Getting Started](GETTING_STARTED.md)
- [Configuration](CONFIGURATION.md)
- [Applications](APPLICATIONS.md)
- [Troubleshooting](TROUBLESHOOTING.md)
