# Sage Terminal

`sage-terminal` is the Rust TUI for Sage.

Current status:

- preview / source-run only
- no packaged installer yet
- depends on the local Sage Python CLI/backend from this repository
- see `BOUNDARY.md` and `CLI_CONTRACT.md` for ownership and integration rules
- runtime lookup and future bundle assumptions are documented in `DISTRIBUTION.md` and `BUNDLE_LAYOUT.md`

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

## In-App Commands

Common slash commands:

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

## Notes

- This preview is intended for local development and dogfooding.
- Packaging and one-command installation are not included yet.
- The TUI currently relies on the Sage CLI/backend behavior, so CLI runtime configuration must be valid first.
- Agent selection is still lightweight: the TUI can override `agent_id` and `agent_mode`, but the actual agent configuration remains owned by the Sage CLI/runtime and its stored agent config.
- Runtime lookup now supports explicit CLI/Python overrides, bundled `sage` / Python fallbacks, and packaged-layout state roots as a first distribution step.
- The repo now also includes a minimal launcher wrapper at `scripts/run-sage-terminal.sh` and a distribution smoke script at `scripts/smoke-runtime-distribution.sh`.
