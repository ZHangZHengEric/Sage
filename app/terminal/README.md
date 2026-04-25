# Sage Terminal

`sage-terminal` is the Rust TUI for Sage.

Current status:

- preview / source-run only
- no packaged installer yet
- depends on the local Sage Python CLI/backend from this repository

## What It Uses

The TUI is not a separate agent implementation.

It currently works as:

- Rust handles terminal UI, input, popup, overlay, and transcript rendering
- Python handles the Sage runtime through the local CLI entrypoints
- local sessions are shared with the main Sage CLI under `~/.sage/`

## Run From Source

From the repository root:

```bash
pip install -e .

export SAGE_DEFAULT_LLM_API_KEY="your-api-key"
export SAGE_DEFAULT_LLM_API_BASE_URL="https://api.deepseek.com/v1"
export SAGE_DEFAULT_LLM_MODEL_NAME="deepseek-chat"
export SAGE_DB_TYPE="file"

cargo run --quiet --offline --manifest-path app/terminal/Cargo.toml
```

Or from `app/terminal`:

```bash
cd app/terminal
cargo run --quiet --offline
```

## Build The Binary

```bash
cd app/terminal
cargo build --release
./target/release/sage-terminal
```

## Startup Commands

Currently supported startup forms:

```bash
sage-terminal
sage-terminal resume
sage-terminal resume latest
sage-terminal resume <session_id>
sage-terminal --help
```

## In-App Commands

Common slash commands:

- `/help`
- `/new`
- `/sessions`
- `/resume`
- `/skills`
- `/skill`
- `/config`
- `/providers`
- `/provider`
- `/model`
- `/status`
- `/transcript`
- `/welcome`
- `/exit`

## Notes

- This preview is intended for local development and dogfooding.
- Packaging and one-command installation are not included yet.
- The TUI currently relies on the Sage CLI/backend behavior, so CLI runtime configuration must be valid first.
