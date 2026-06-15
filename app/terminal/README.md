# Sage Terminal

`sage tui` is Sage's user-facing Terminal TUI entrypoint. The Rust implementation binary is named `sage-terminal` and is launched by the Sage Python CLI.

Current status:

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
- runtime workspace also defaults to the normal Sage CLI location under `~/.sage/...`; only pass `--workspace <path>` when you explicitly want repo-local file access

## Install And Run

When the Sage Python package includes the Terminal binary, users do not need a Rust toolchain:

```bash
sage tui
sage tui coding --workspace /path/to/repo
```

The Python CLI acts as a thin launcher. It resolves packaged binaries from `app/terminal/bin/<platform>/sage-terminal` before falling back to `SAGE_TERMINAL_BIN`, `PATH`, and source checkout build outputs.

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

## Build The Binary During Development

```bash
cd app/terminal
cargo build --release
./target/release/sage-terminal
```

## Startup Commands

User-facing startup forms:

```bash
sage tui
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

## In-App Commands

Common slash commands:

- `/help`
- `/agent`
- `/mode`
- `/display`
- `/workspace`
- `/sandbox`
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

Agent config commands:

```text
/agent config coding
/agent config /path/to/agent-config.json
/agent set agent_demo
/agent clear
```

Sandbox commands:

```text
/sandbox
/sandbox set local
/sandbox set remote
/sandbox set passthrough
/sandbox clear
```

## Notes

- This preview is intended for local development and dogfooding.
- Packaging and one-command installation are not included yet.
- The TUI currently relies on the Sage CLI/backend behavior, so CLI runtime configuration must be valid first.
- Agent selection is still lightweight: the TUI can override `agent_id`, `agent_mode`, or pass a session-scoped `--agent-config <path|coding>`, but the actual agent behavior remains owned by the Sage CLI/runtime and its stored or explicit agent config.
- `--agent-id` and `--agent-config` are mutually exclusive in practice. If both are provided at startup, `--agent-config` wins and the saved agent id is ignored for backend requests.
- Session-scoped `--agent-config` is used for chat backend requests. Auxiliary views such as `/sessions` and `/skills` still use the saved `agent_id` contract when one is active.
- The bundled `coding` agent config requires an explicit repo workspace. Start with `--workspace /path/to/repo` or run `/workspace set /path/to/repo` before sending coding tasks.
- `--sandbox-type` and `/sandbox set ...` configure the client-side sandbox mode passed to the Sage backend through `SAGE_SANDBOX_MODE`; enforcement remains owned by the Sage runtime sandbox.
- By default the TUI does not force the current directory into `--workspace`, so it will not create `AGENT.md` / `MEMORY.md` / `.sage-docs` inside your repository unless you opt into a workspace override.
- Runtime lookup now supports explicit CLI/Python overrides, bundled `sage` / Python fallbacks, and packaged-layout state roots as a first distribution step.
- The repo now also includes a minimal launcher wrapper at `scripts/run-sage-terminal.sh` and a distribution smoke script at `scripts/smoke-runtime-distribution.sh`.
