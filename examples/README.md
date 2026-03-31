# Sage Examples

This directory contains the standalone examples for the Sage project.

## Prerequisites

- Python 3.10 or newer
- Project dependencies installed from the repository root with `python3 -m pip install -r requirements.txt`

The default config files are already included:

- `mcp_setting.json`
- `preset_running_agent_config.json`
- `preset_running_config.json`

Edit them in place if you want to enable MCP servers or customize agent behavior.

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
