# Sage Server

This branch contains only the Sage Server product surface:

- `app/server`: FastAPI application and Vue web console
- `common`: Server domain services, persistence, and infrastructure adapters
- `sagents`: Agent runtime
- `app/skills`: Bundled runtime skills
- `mcp_servers/anytool` and `mcp_servers/task_scheduler`: MCP capabilities required by the Server
- `deploy`: Docker deployment for `sage-server` and `sage-web`

Desktop, CLI/TUI, Terminal, browser extension, Wiki, and standalone optional MCP applications are intentionally excluded.

## Run locally

```bash
cp .env.example.minimal .env
python -m pip install -r requirements.txt
python -m app.server.main
```

In another terminal:

```bash
cd app/server/web
npm ci
npm run dev
```

## Deploy

Each environment Compose file defines exactly two services: `sage-server` and `sage-web`.

```bash
cp deploy/prod/.env.example deploy/prod/.env
deploy/compose.sh prod up -d --build
```

SQLite is the self-contained default. MySQL, Elasticsearch, S3-compatible object storage, OpenTelemetry, and remote sandbox providers remain supported as external services configured through environment variables; they are not deployed by this repository.

## Verify

```bash
python -m pytest tests/app/server tests/common tests/sagents
cd app/server/web && npm test -- --run && npm run build
docker compose --env-file deploy/prod/.env.example -f deploy/prod/docker-compose.yml config
```

See [deploy/README.md](deploy/README.md) for deployment details.
