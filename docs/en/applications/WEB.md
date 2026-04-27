---

## layout: default
title: Web Application
parent: Applications
nav_order: 4
description: "Run the browser-based Sage stack: dev script, manual backend + Vite, and Docker Compose"
lang: en
ref: web-app

{% include lang_switcher.html %}

# Web Application

The **Web** product is the FastAPI server (`app/server/`) plus the Vue 3 client (`app/server/web/`). Use it when you need the full in-browser experience: auth, agents, tools, knowledge base, and the visual workbench.


| Path                                                                 | Best for                                                              |
| -------------------------------------------------------------------- | --------------------------------------------------------------------- |
| [One-command startup](#one-command-startup)                          | Local development (same as [Getting Started](GETTING_STARTED.md))     |
| [Manual: backend + Vite dev server](#manual-start-backend--frontend) | Split terminals, custom ports, or debugging one side only             |
| [Docker Compose](#docker-compose-full-stack)                         | Containerized full stack (MySQL, Elasticsearch, RustFS, Jaeger, etc.) |


## One-command startup

```bash
git clone https://github.com/ZHangZHengEric/Sage.git
cd Sage
export SAGE_DEFAULT_LLM_API_KEY="your-api-key"
export SAGE_DEFAULT_LLM_API_BASE_URL="https://api.deepseek.com/v1"
export SAGE_DEFAULT_LLM_MODEL_NAME="deepseek-chat"
./scripts/dev-up.sh
```

After startup (defaults):

- **Web UI (Vite dev):** [http://localhost:5173](http://localhost:5173)
- **Backend API:** [http://localhost:8080](http://localhost:8080)
- **Health:** [http://localhost:8080/api/health](http://localhost:8080/api/health)

The script may offer **Minimal** (SQLite) vs **Full** dependencies — choose Minimal for the fastest first run. For generated `.env` layout and env vars, see [Getting Started — Configuration](GETTING_STARTED.md#configuration-files) and [Configuration](../CONFIGURATION.md).

## Manual start: backend + frontend

Use this when you do not use `dev-up.sh` or you want to run processes separately.

1. **Install deps** (from repo root)

```bash
pip install -r requirements.txt
cd app/server/web && npm install && cd ../../..
```

1. **Backend**

```bash
export SAGE_DEFAULT_LLM_API_KEY="your-api-key"
# plus other env from .env if needed
python -m app.server.main
```

Listens on `0.0.0.0:${SAGE_PORT:-8080}`.

1. **Frontend** (second terminal)

```bash
cd app/server/web
npm run dev
```

1. **Configure the SPA** — see `app/server/web/.env.example` and `VITE_SAGE_API_BASE_URL` (must point at your running API).

## Docker Compose (full stack)

The root `[docker-compose.yml](https://github.com/ZHangZHengEric/Sage/blob/main/docker-compose.yml)` starts a **full** platform profile: `sage-server`, static `sage-web`, optional `sage-wiki`, MySQL, Elasticsearch, RustFS (S3-compatible), and Jaeger. It is intended for **production-like** or integrated demos, not the lightest dev loop (for that, prefer `./scripts/dev-up.sh` in Minimal mode).

**What gets exposed (defaults in the compose file):**


| Service       | Host port (typical)          | Notes                                      |
| ------------- | ---------------------------- | ------------------------------------------ |
| `sage-server` | 30050 → 8080                 | Primary HTTP API                           |
| `sage-web`    | 30051 → 80                   | Pre-built web assets behind nginx in image |
| `sage-wiki`   | 30057 → 80                   | Wiki front-end (depends on API)            |
| `sage-mysql`  | 30052 → 3306                 |                                            |
| `sage-es`     | 30053 → 9200                 |                                            |
| `sage-rustfs` | 30054 (API), 30055 (console) |                                            |


### Prerequisites

- Docker with **Compose v2** (`docker compose`)
- Sufficient host resources (the compose file sets a **16G** memory limit on `sage-server`; adjust in `docker-compose.yml` if needed)
- A valid `.env` at the **repository root** (Compose reads `env_file: .env`). Copy from `[.env.example](https://github.com/ZHangZHengEric/Sage/blob/main/.env.example)` and set at least **LLM** and **DB/ES/S3**-related variables. The example file is aligned with **in-cluster** hostnames: `sage-mysql`, `sage-es`, `sage-rustfs`, etc.

`SAGE_ROOT` must point to a directory on the host used for **persistent volumes** (MySQL data, `sage-server` sessions/agents/logs, ES data, RustFS data, etc.).

### Run

```bash
cd /path/to/Sage
export SAGE_ROOT=/path/to/sage-data   # or e.g. $(pwd)/data
cp .env.example .env
# edit .env: SAGE_DEFAULT_LLM_API_KEY, secrets, SAGE_MYSQL_PASSWORD, SAGE_ELASTICSEARCH_PASSWORD, SAGE_S3_* as needed
docker compose up -d --build
```

**Logs:**

```bash
docker compose logs -f sage-server
docker compose logs -f sage-web
```

**Health check (API):**

```bash
curl -sS http://127.0.0.1:30050/api/health
```

**Open the web UI** — the default example uses a base path (`SAGE_WEB_BASE_PATH`, often `/sage`). With the sample `.env.example` values, try:

- `http://127.0.0.1:30051` (then navigate using your configured base path, e.g. `/sage/`), *or* the exact URL your team documents for the deployed nginx route.

`SAGE_API_BASE_URL` in `.env` must match how the **browser** reaches the API (e.g. `http://127.0.0.1:30050` when developing locally against published ports).

### Stop

```bash
docker compose down
```

**Port conflicts:** If another process uses 30050–30057, change the `ports:` mappings in `docker-compose.yml` and update `.env` so API URLs and `SAGE_API_BASE_URL` stay consistent.

## See also

- [Getting Started](GETTING_STARTED.md) — first-run script and config overview
- [Server architecture](../architecture/ARCHITECTURE_APP_SERVER.md)
- [Configuration](../CONFIGURATION.md) · [Environment variables](../ENV_VARS.md)
- [Troubleshooting](../TROUBLESHOOTING.md)

