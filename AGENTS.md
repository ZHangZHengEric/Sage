# AGENTS.md

## Cursor Cloud specific instructions

Sage is a multi-agent platform. The primary dev target is the **Web product**: a
FastAPI backend (`app/server/main.py`) plus a Vue 3 + Vite SPA (`app/server/web`).
CLI/desktop/TUI/extension are alternate front-ends over the same Python kernel
(`sagents/`, `common/`, `mcp_servers/`).

Dependencies (Python `requirements.txt`, `app/server/web`, `app/desktop/ui`) are
installed by the startup update script — do not reinstall them by hand.

### Running the Web app (dev)
- Backend: `python -m app.server.main` (needs a `.env`; create with
  `cp .env.example.minimal .env` if missing). Health check: `GET /api/health`.
- Frontend: `cd app/server/web && npm run dev` → http://localhost:5173
- Logs from the helper script go to `logs/server.log`.

### Non-obvious gotchas (important)
- **Backend must run on port 30050 for the dev web UI.** `app/server/web/vite.config.js`
  hardcodes its `/prod-api` proxy target to `http://127.0.0.1:30050`. The
  `VITE_*` values that `scripts/dev-up.sh` writes into `.env.development` are NOT
  read by this vite config. So set `SAGE_PORT=30050` in `.env` (the `sage` backend
  otherwise defaults to 8080).
- **`.env.example.minimal` has a broken DB setting.** It sets `SAGE_DB_TYPE=sqlite`
  + `SAGE_SQLITE_PATH`, but the code only supports `file`, `memory`, `mysql`
  (`common/core/client/db.py`). Use `SAGE_DB_TYPE=file` and `SAGE_DB_FILE=./data/sage.db`
  instead, or the backend fails to start with "不支持的数据库类型".
- **Agent chat needs an LLM provider.** Login and the whole UI work without it, but
  a first-login modal ("完善配置信息") blocks the chat input until an LLM provider is
  configured. Set `SAGE_DEFAULT_LLM_API_KEY` (+ `SAGE_DEFAULT_LLM_API_BASE_URL`,
  `SAGE_DEFAULT_LLM_MODEL_NAME`) in `.env`, or add a provider via that modal with a
  real key. There is no LLM key in the environment by default.
- **Default login:** username `admin`, password `admin.1234` (from
  `SAGE_BOOTSTRAP_ADMIN_*` in `.env`). Self-registration is disabled by default.
- **pip user scripts are not on PATH.** `ruff`, `pytest`, etc. install to
  `~/.local/bin`. Invoke via modules: `python3 -m ruff ...`, `python3 -m pytest ...`.

### Lint / test / build (see CI in `.github/workflows/ci-tests.yml`)
- Lint: `python3 -m ruff check .` and `python3 -m ruff format --check .`
- Python tests — run each suite **separately** (as CI does):
  `python3 -m pytest tests/app`, `... tests/common`, `... tests/sagents`.
  Running all suites in one `pytest` invocation triggers a pre-existing
  pandas/`pytz` import-order collection error; the separated runs pass.
- Web: `cd app/server/web && npm run check:i18n && npm test -- --run`
- Desktop UI i18n: `cd app/desktop/ui && npm run check:i18n`
