# Sage Examples

This directory contains the standalone examples for the Sage project.

## Prerequisites

- Python 3.10 or newer
- Project dependencies installed from the repository root with `python3 -m pip install -r requirements.txt`

The default config files are already included:

- `mcp_setting.json`
- `preset_running_agent_config.json`
- `preset_running_coding_agent_config.json`
- `preset_running_config.json`

Edit them in place if you want to enable MCP servers or customize agent behavior.

`preset_running_coding_agent_config.json` is a Codex-style coding preset for repository work, shell-driven debugging, targeted edits, code review, and iterative verification in Sage Terminal TUI. It includes:

- `codexCliDesignReference`: maps Codex CLI concepts to Sage TUI behavior, including profile-like config, workspace-oriented execution, repo guidance files, dirty-worktree safety, tool allow-lists, search/edit/verify loops, lightweight planning, review mode, and context management.
- `codingAgentOperatingContract`: gives the agent concrete startup, planning, editing, command, verification, review, and final-response rules.
- `sageToolPlaybook`: explains how the preset expects the agent to use Sage's existing coding tools, such as `grep`, `glob`, `list_dir`, `file_update`, `execute_shell_command`, `await_shell`, `read_lints`, `todo_write`, and `search_memory`.

This preset does not add Codex runtime features to Sage. Sandbox mode, approval policy, config layering, MCP approval, and apply_patch remain runtime concerns; the preset documents them as soft constraints and steers the coding agent toward conservative behavior using Sage's existing agent config fields.

For Sage Terminal TUI, pass the bundled preset through the unified CLI entrypoint:

```bash
sage tui --agent-config coding --workspace /path/to/repo
```

For non-TUI CLI runs, the same preset can be used with:

```bash
sage chat --agent-config coding --workspace /path/to/repo
sage run --agent-config coding --workspace /path/to/repo "inspect this repo"
```

Use `--agent-config examples/preset_running_coding_agent_config.json` when you want to run a copied or edited JSON file directly.

For the standalone example CLI script, point it at the file with `--preset_running_agent_config_path`.

## CLI

```bash
python3 examples/sage_cli.py \
  --default_llm_api_key YOUR_API_KEY \
  --default_llm_api_base_url https://api.deepseek.com/v1 \
  --default_llm_model_name deepseek-chat
```

## Streamlit Demo

```bash
streamlit run examples/sage_demo.py -- \
  --default_llm_api_key YOUR_API_KEY \
  --default_llm_api_base_url https://api.deepseek.com/v1 \
  --default_llm_model_name deepseek-chat
```

## HTTP Server

```bash
python3 examples/sage_server.py \
  --default_llm_api_key YOUR_API_KEY \
  --default_llm_api_base_url https://api.deepseek.com/v1 \
  --default_llm_model_name deepseek-chat
```

## Build Script

```bash
python3 examples/build_exec/build_simple.py --dry-run
python3 examples/build_exec/build_simple.py
```

The build script packages `examples/sage_server.py` and writes artifacts to `examples/build_exec/build/`.
