# Sage Server-only deployment

The deployment contains exactly two services:

- `sage-server`: FastAPI API and Agent Runtime
- `sage-web`: built Web UI served by Nginx

SQLite is the default database and is persisted under
`${SAGE_ROOT}/sage-server/data`. MySQL, Elasticsearch, S3-compatible object
storage, OpenTelemetry collectors, and remote sandbox providers are optional
external adapters. This repository does not deploy them.

## Start

```bash
cp deploy/prod/.env.example deploy/prod/.env
# Replace all change_this_* values before production use.
deploy/compose.sh prod up -d --build
```

Development and test environments use the same two-service topology:

```bash
cp deploy/dev/.env.example deploy/dev/.env
deploy/compose.sh dev up -d --build

cp deploy/test/.env.example deploy/test/.env
deploy/compose.sh test up -d --build
```

The default endpoints are:

- production Web: `http://127.0.0.1:30051/sage/`
- production API: `http://127.0.0.1:30050`
- development Web: `http://127.0.0.1:30151/sage/`
- development API: `http://127.0.0.1:30150`

## Operations

```bash
deploy/compose.sh prod ps
deploy/compose.sh prod logs -f sage-server
deploy/compose.sh prod up -d --build sage-server
deploy/compose.sh prod down
```

Targeted `up` commands automatically receive `--no-deps`, so rebuilding the
server does not restart the Web container.

## External adapters

Configure external services in `deploy/<env>/.env` only when the corresponding
feature is required:

- `SAGE_S3_*` for object storage and knowledge-base uploads
- `SAGE_ELASTICSEARCH_*` for Elasticsearch-backed search
- `SAGE_TRACE_JAEGER_URL` for OTLP export
- `SAGE_REMOTE_PROVIDER` and provider-specific variables for remote sandboxes

Leaving these values empty keeps the core Server + Web deployment independent
of those systems.
