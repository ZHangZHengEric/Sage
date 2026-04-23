---
layout: default
title: Getting Started
parent: Applications
nav_order: 1
description: "Install Sage and run the main entry points"
lang: en
ref: getting-started
---

{% include lang_switcher.html %}

# Getting Started

## One-Command Startup (Recommended)

**Best for:** Local development, quick testing

```bash
# 1. Clone the repository
git clone https://github.com/ZHangZHengEric/Sage.git
cd Sage

# 2. Configure LLM API Key
export SAGE_DEFAULT_LLM_API_KEY="your-api-key"
export SAGE_DEFAULT_LLM_API_BASE_URL="https://api.deepseek.com/v1"
export SAGE_DEFAULT_LLM_MODEL_NAME="deepseek-chat"

# 3. Run the startup script
./scripts/dev-up.sh
```

**First run?** The script will prompt you to choose a configuration mode:

- **Minimal mode** (recommended for beginners): SQLite, no external dependencies
  - Template: `.env.example.minimal`
  - Best for: Quick local development
- **Full mode**: MySQL + Elasticsearch + RustFS
  - Template: `.env.example`
  - Best for: Production-like environment

**After successful startup:**
- Frontend: http://localhost:5173
- Backend API: http://localhost:8080
- Health check: http://localhost:8080/api/health

## Configuration Files

The startup script will automatically create these configuration files:

### Backend Configuration

- **Location:** Root directory `.env`
- **Templates:**
  - `.env.example.minimal` - Minimal config (SQLite, no external dependencies)
  - `.env.example` - Full config (MySQL + ES + RustFS)
- **Purpose:** Python backend service configuration
- **Key settings:**
  - `SAGE_DB_TYPE` - Database type (sqlite/mysql)
  - `SAGE_AUTH_MODE` - Authentication mode (native/trusted_proxy/oauth)
  - `SAGE_DEFAULT_LLM_API_KEY` - LLM API key (required)
  - `SAGE_PORT` - Backend port (default 8080)

### Frontend Configuration

- **Location:** `app/server/web/.env.development`
- **Template:** `app/server/web/.env.example`
- **Purpose:** Vite frontend build configuration
- **Key settings:**
  - `VITE_SAGE_API_BASE_URL` - Backend API URL
  - `VITE_SAGE_WEB_BASE_PATH` - Web base path

---

## Manual Startup (Advanced)

If you need manual control over the startup process, follow these steps.

### Prerequisites

- Python 3.10 or newer
- Node.js for the web client and some desktop workflows
- A valid LLM API key for the model provider you plan to use

Install Python dependencies from the repository root:

```bash
pip install -r requirements.txt
```

If you plan to run the web client, install Node.js dependencies separately under `app/server/web/`.

## Minimum Environment

Sage can start with only the default LLM settings configured:

```bash
export SAGE_DEFAULT_LLM_API_KEY="your-api-key"
export SAGE_DEFAULT_LLM_API_BASE_URL="https://api.deepseek.com/v1"
export SAGE_DEFAULT_LLM_MODEL_NAME="deepseek-chat"
```

If you keep a local `.env`, both `app/server/main.py` and `app/desktop/core/main.py` load it automatically.

## Choose an Auth Deployment Mode

Current supported authentication deployments are intentionally narrowed to three modes:

- `trusted_proxy`: business requests coming from `SAGE_TRUSTED_IDENTITY_PROXY_IPS` bypass Sage end-user auth, admins can still log in with built-in credentials, and an upstream proxy may optionally pass `X-Sage-Internal-UserId`
- `oauth`: Sage redirects users to an upstream OAuth/OIDC provider configured through `SAGE_AUTH_PROVIDERS`
- `native`: Sage uses its built-in username/password login

Minimal trusted proxy example:

```bash
export SAGE_AUTH_MODE="trusted_proxy"
export SAGE_TRUSTED_IDENTITY_PROXY_IPS="10.0.0.0/8,127.0.0.1/32"
```

Minimal OAuth example:

```bash
export SAGE_AUTH_MODE="oauth"
export SAGE_AUTH_PROVIDERS='[{"id":"corp-sso","type":"oidc","name":"Corp SSO","discovery_url":"https://sso.example.com/.well-known/openid-configuration","client_id":"sage","client_secret":"secret"}]'
```

Minimal native auth example:

```bash
export SAGE_AUTH_MODE="native"
```

For local development, the default `SAGE_ENV` is `development`. If you set `SAGE_ENV=production` or `SAGE_ENV=staging`, you must also provide explicit values for:

- `SAGE_JWT_KEY`
- `SAGE_REFRESH_TOKEN_SECRET`
- `SAGE_SESSION_SECRET`

Production-like mode also forces secure session cookies.

## Run the CLI

For the fastest runtime smoke test:

You should be able to complete at least one of these checks:

- CLI starts and accepts a prompt
- `python -m app.server.main` starts successfully
- `curl http://127.0.0.1:8080/api/health` returns a healthy response
- the web UI loads after `npm run dev`

The fastest way to validate the runtime is the CLI:

```bash
pip install -r requirements.txt
pip install -e .
sage doctor
sage run "Help me analyze the current repository"
sage chat
```

For a dedicated command-line usage guide, see [CLI Guide](CLI.md).

## Manually Start Web Services

### Start Backend

Start the primary FastAPI service:

```bash
python -m app.server.main
```

By default the server listens on `0.0.0.0:${SAGE_PORT:-8080}`.

Health check:

```bash
curl http://127.0.0.1:8080/api/health
```

### Start Frontend

In a second terminal:

```bash
cd app/server/web
npm install
npm run dev
```

For the web UI, the commonly relevant frontend variables are:

- `VITE_SAGE_API_BASE_URL`
- `VITE_SAGE_WEB_BASE_PATH`

---

## Other Demos & Tools

```bash
streamlit run examples/sage_demo.py -- \
  --default_llm_api_key "$SAGE_DEFAULT_LLM_API_KEY" \
  --default_llm_api_base_url "$SAGE_DEFAULT_LLM_API_BASE_URL" \
  --default_llm_model_name "$SAGE_DEFAULT_LLM_MODEL_NAME"
```

## Run the Standalone Example Server

```bash
python examples/sage_server.py \
  --default_llm_api_key "$SAGE_DEFAULT_LLM_API_KEY" \
  --default_llm_api_base_url "$SAGE_DEFAULT_LLM_API_BASE_URL" \
  --default_llm_model_name "$SAGE_DEFAULT_LLM_MODEL_NAME"
```

Use this only when you want the lightweight example service, not the full `app/server` stack.

The example configs that ship with `examples/` are:

- `examples/mcp_setting.json`
- `examples/preset_running_agent_config.json`
- `examples/preset_running_config.json`

### Streamlit Demo

```bash
streamlit run examples/sage_demo.py -- \
  --default_llm_api_key "$SAGE_DEFAULT_LLM_API_KEY" \
  --default_llm_api_base_url "$SAGE_DEFAULT_LLM_API_BASE_URL" \
  --default_llm_model_name "$SAGE_DEFAULT_LLM_MODEL_NAME"
```

---

## Build Desktop App from Source

```bash
app/desktop/scripts/build.sh release
```

Windows source build:

```powershell
./app/desktop/scripts/build_windows.ps1 release
```

## Recommended Reading After Setup

1. [Core Concepts](CORE_CONCEPTS.md)
2. [Architecture](architecture/README.md)
3. [Configuration](CONFIGURATION.md)

If something fails during startup, go next to [Troubleshooting](TROUBLESHOOTING.md).
