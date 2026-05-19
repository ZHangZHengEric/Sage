#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEPLOY_DIR="$ROOT_DIR/deploy"
DEPLOY_ENV="${DEPLOY_ENV:-prod}"

usage() {
  cat <<'EOF'
Usage: deploy/compose.sh [dev|prod|test] [docker compose args...]
       deploy/compose.sh [dev|prod|test] --observability [docker compose args...]

Default environment: prod

Examples:
  deploy/compose.sh up -d
  deploy/compose.sh --observability up -d
  deploy/compose.sh dev --observability up -d
  deploy/compose.sh dev up -d
  deploy/compose.sh prod pull
  deploy/compose.sh test down

The script runs:
  docker compose --env-file deploy/<env>/.env -f deploy/<env>/docker-compose.yml -f deploy/docker-compose.shared.yml ...

Observability services (prometheus, grafana, cadvisor, loki, alloy) are behind the
`observability` compose profile and are not started unless --observability is set
or COMPOSE_PROFILES already includes observability.

If deploy/<env>/.env is missing, it falls back to .env in the repo root.
EOF
}

case "${1:-}" in
  -h|--help)
    usage
    exit 0
    ;;
  dev|prod|test)
    DEPLOY_ENV="$1"
    shift
    ;;
esac

ENABLE_OBSERVABILITY="${ENABLE_OBSERVABILITY:-false}"
if [ "${1:-}" = "--observability" ]; then
  ENABLE_OBSERVABILITY="true"
  shift
fi

COMPOSE_FILE="$DEPLOY_DIR/$DEPLOY_ENV/docker-compose.yml"
SHARED_COMPOSE_FILE="$DEPLOY_DIR/docker-compose.shared.yml"

if [ -z "${ENV_FILE:-}" ]; then
  ENV_FILE="$DEPLOY_DIR/$DEPLOY_ENV/.env"
  if [ ! -f "$ENV_FILE" ]; then
    ENV_FILE="$ROOT_DIR/.env"
  fi
fi

case "$ENV_FILE" in
  /*)
    ;;
  *)
    ENV_FILE="$(pwd)/$ENV_FILE"
    ;;
esac

if [ ! -f "$COMPOSE_FILE" ]; then
  echo "Compose file not found: $COMPOSE_FILE" >&2
  exit 1
fi

if [ ! -f "$SHARED_COMPOSE_FILE" ]; then
  echo "Shared compose file not found: $SHARED_COMPOSE_FILE" >&2
  exit 1
fi

if [ ! -f "$ENV_FILE" ]; then
  echo "Env file not found: $ENV_FILE" >&2
  echo "Create it from: $DEPLOY_DIR/$DEPLOY_ENV/.env.example or $ROOT_DIR/.env.example" >&2
  exit 1
fi

COMPOSE_ARGS=(--env-file "$ENV_FILE" -f "$COMPOSE_FILE" -f "$SHARED_COMPOSE_FILE")
if [ "$ENABLE_OBSERVABILITY" = "true" ]; then
  COMPOSE_ARGS+=(--profile observability)
fi

SAGE_REPO_ROOT="$ROOT_DIR" \
SAGE_DEPLOY_DIR="$DEPLOY_DIR" \
SAGE_COMPOSE_ENV_FILE="$ENV_FILE" \
  docker compose "${COMPOSE_ARGS[@]}" "$@"
