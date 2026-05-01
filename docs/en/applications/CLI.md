---
layout: default
title: CLI Guide
parent: Applications
nav_order: 2
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

For a complete local development/runtime environment, install the repository requirements first:

```bash
pip install -r requirements.txt
```

If you also want the `sage` entrypoint available from the current checkout, add the editable install from the repository root:

```bash
pip install -e .
```

If you do not want to install an editable package yet, you can also use:

```bash
python -m app.cli.main --help
```

## Minimum Configuration

The CLI now defaults to the same local storage root as desktop: `~/.sage/`.

By default it:

- reads shared local environment variables from `~/.sage/.sage_env` when present
- stores local data under `~/.sage/`
- lets a repository-local `.env` override the shared file for development

You can inspect the effective file and load order with:

```bash
sage config show
```

The simplest usable setup is:

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

By default this writes to:

```text
~/.sage/.sage_env
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
- effective env file path and existence
- auth mode and DB type
- resolved memory backends for `session_history` and `file_memory`
- resolved session-history strategy for `session_history`
- important directories such as `agents_dir`, `session_dir`, and `logs_dir`
- the SQLite session registry path under `session_dir`
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

`sage config show` also reports the currently resolved memory backend defaults for:

- `session_history`
- `file_memory`

It also reports the currently resolved session-history retrieval strategy for:

- `session_history`

The corresponding environment variable is:

- `SAGE_SESSION_MEMORY_STRATEGY`

If a memory backend or strategy is configured with an unsupported value, `sage doctor`
and `sage config show` keep returning structured diagnostics and surface the validation
error in the corresponding `memory_backends.*` or `memory_strategies.*` entry instead of
crashing.

`sage config init` also writes commented optional memory-search overrides into the
generated env template so local backend or strategy changes can be made in one place.

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

Notes:
- `sage chat` is line-oriented. Pasting multiple newline-separated lines will be treated as multiple turns.
- If you do not pass `--workspace`, file-writing tool calls use the default agent workspace under `~/.sage/agents/<user>/<agent_id>/...`.

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

Inspect one session in more detail:

```bash
sage sessions inspect <session_id>
sage sessions inspect latest
sage sessions inspect --json <session_id>
sage sessions inspect --agent-id my-agent latest
sage sessions inspect --messages 8 <session_id>
```

The inspect view includes:

- session summary fields such as title, agent, timestamps, and message counts
- last user and assistant message summaries when available
- recent message previews
- optional JSON output for scripting or debugging

### `sage skills`

Inspect skills currently visible to the CLI.

Examples:

```bash
sage skills
sage skills --json
sage skills --workspace /path/to/project
sage skills --agent-id my-agent
```

The output includes:

- current user id
- optional agent id
- optional workspace
- total visible skills
- per-source counts
- skill names and descriptions
- source-level errors, if any

When `--agent-id` is provided, the CLI shows the skills currently available to that specific agent after the newer agent-skill sync logic is applied.

### `sage provider`

Inspect and manage local LLM providers from the CLI.

Supported subcommands:

- `list`
- `inspect`
- `verify`
- `create`
- `update`
- `delete`

Examples:

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

Important behavior:

- `verify` probes connectivity but does not save anything.
- `create` and `update` both require a successful probe before saving.
- omitted `--base-url`, `--api-key`, and `--model` values on `create`/`verify` fall back to the current CLI defaults from env.
- when those fallback defaults are missing, `create`/`verify` fail early with a CLI error and concrete next steps.
- `update` rejects empty `--api-key` values and also fails fast when no update fields are supplied.
- provider output masks API keys and only shows a short preview.
- each user can have at most one default provider; setting one provider as default clears the other default flags for that same user.
- `delete` still refuses to remove the current default provider.

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

The JSON stream now has four layers:

- a session envelope event: `cli_session`
- raw runtime events such as `assistant`, `analysis`, `tool_call`, and `tool_result`
- CLI control events such as `cli_phase` and `cli_tool`
- a final `cli_stats` event when `--stats` is enabled

The intended contract is:

- `cli_session`: emitted before streamed runtime output; includes the resolved `session_id`, `command_mode`, `session_state`, `user_id`, `agent_id`, `agent_mode`, `workspace`, `workspace_source`, requested skills, `max_loop_count`, `has_prior_messages`, `prior_message_count`, and optional `session_summary` for resume hydration
- `cli_phase`: emitted when the CLI detects a phase transition such as `planning`, `tool`, or `assistant_text`
- `cli_tool`: emitted when a tool step starts or finishes; includes `action`, `step`, `tool_name`, `tool_call_id`, and `status`
- `cli_stats`: emitted once at the end; includes final `tool_steps`, `phase_timings`, timing summary, and token summary

Consumers should treat `cli_session`, `cli_phase`, and `cli_tool` as the preferred UI contract, and treat raw `tool_call` / `tool_result` lines as compatibility input rather than the primary surface. `cli_session.session_id` is intended to be stable from the first event onward, including requests that did not receive an explicit `--session-id`. `session_state`, `has_prior_messages`, and `prior_message_count` are provided so frontends can hydrate new-vs-existing session state without re-deriving it from `command_mode` and `session_summary`. When `--workspace` is provided, the emitted workspace path is the normalized absolute path that the backend actually uses.

When used together with `--stats`, the CLI appends a final `cli_stats` JSON event for post-run analysis:

```bash
sage run --json --stats "Say hello briefly."
```

This is useful for:

- shell scripting
- comparing runs
- extracting token usage
- hydrating UI state before the first assistant chunk arrives
- checking whether tools or skills were actually used

For a concrete end-to-end sample, see `tests/app/cli/fixtures/stream_contract_round_trip.jsonl`.

## Workspace Usage

Use `--workspace` when you want the CLI to operate against a specific local directory:

```bash
sage run --workspace /path/to/project --stats "Analyze this repository briefly."
sage chat --workspace /path/to/project
sage resume --workspace /path/to/project <session_id>
sage skills --workspace /path/to/project
```

This is especially useful for file-oriented agent tasks and skill discovery under a workspace-specific `skills/` directory.

Without `--workspace`, interactive chat/file-writing tasks will use the default agent workspace under `~/.sage/agents/<user>/<agent_id>/...` instead of your current repository.

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
- JSON mode emits `cli_session` first, then `cli_phase` / `cli_tool` during the run
- JSON mode ends with a `cli_stats` event

## Maintainer Validation

When you change provider management or CLI error handling, also run the real integration test:

```bash
/opt/miniconda3/envs/sage_dev/bin/python tests/app/cli/test_provider_integration.py
```

Notes:

- the default system Python may skip this suite if `sqlalchemy`, `aiosqlite`, or `loguru` are not installed
- this test exercises `provider create -> inspect -> update -> delete` against a temporary file DB
- it also verifies default-provider switching and friendly JSON errors for auth, model-not-found, and timeout probe failures

## Related Docs

- [Getting Started](GETTING_STARTED.md)
- [Configuration](CONFIGURATION.md)
- [Applications](README.md)
- [Troubleshooting](TROUBLESHOOTING.md)
