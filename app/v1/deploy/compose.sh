#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
DEPLOY_DIR="$ROOT_DIR/app/v1/deploy"
DEPLOY_ENV="${DEPLOY_ENV:-prod}"

usage() {
  cat <<'EOF'
Usage: app/v1/deploy/compose.sh [dev|prod] [docker compose args...]

Deploy Sage Server v1 and Web using separately deployed infrastructure.
Default environment: prod

Examples:
  app/v1/deploy/compose.sh up -d
  app/v1/deploy/compose.sh dev up -d --build
  app/v1/deploy/compose.sh dev up -d sage-server
  app/v1/deploy/compose.sh prod logs -f sage-server
  app/v1/deploy/compose.sh config --services
  app/v1/deploy/compose.sh prod down

The script reads app/v1/deploy/<env>/.env, falling back to the repo root .env.
Override with ENV_FILE=/path/to/.env.
Default project: sage_<env>; override with SAGE_COMPOSE_PROJECT_NAME.
For dev, sage-server and sage-web are mapped to their environment names.
Docker Compose v2 is preferred, with docker-compose as a fallback.
EOF
}

case "${1:-}" in
  dev|prod)
    DEPLOY_ENV="$1"
    shift
    ;;
  test)
    echo "Unsupported deployment environment: $1. Use dev or prod." >&2
    exit 1
    ;;
esac

case "$DEPLOY_ENV" in
  dev|prod) ;;
  *) echo "Unsupported deployment environment: $DEPLOY_ENV" >&2; exit 1 ;;
esac

if [ "$#" -eq 0 ] || [ "${1:-}" = "--help" ] || [ "${1:-}" = "-h" ]; then
  usage
  exit 0
fi

COMPOSE_FILE="$DEPLOY_DIR/$DEPLOY_ENV/docker-compose.yml"
ENV_PROJECT_NAME="${SAGE_COMPOSE_PROJECT_NAME:-${COMPOSE_PROJECT_NAME:-sage_$DEPLOY_ENV}}"
SHARED_NETWORK="${SAGE_SHARED_NETWORK:-sage_shared_default}"
LING_SHARED_NETWORK="${LING_SHARED_NETWORK:-ling_shared_default}"

if [ -z "${ENV_FILE:-}" ]; then
  ENV_FILE="$DEPLOY_DIR/$DEPLOY_ENV/.env"
  if [ ! -f "$ENV_FILE" ]; then
    ENV_FILE="$ROOT_DIR/.env"
  fi
fi
case "$ENV_FILE" in
  /*) ;;
  *) ENV_FILE="$PWD/$ENV_FILE" ;;
esac

if [ ! -f "$ENV_FILE" ]; then
  echo "Env file not found: $ENV_FILE" >&2
  echo "Create it from: $DEPLOY_DIR/$DEPLOY_ENV/.env.example" >&2
  exit 1
fi

if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
  COMPOSE_COMMAND=(docker compose)
elif command -v docker-compose >/dev/null 2>&1; then
  COMPOSE_COMMAND=(docker-compose)
else
  echo "Docker Compose not found. Install Docker Compose v2 or docker-compose." >&2
  exit 1
fi

ensure_network() {
  if ! docker network inspect "$1" >/dev/null 2>&1; then
    docker network create "$1" >/dev/null
  fi
}

if [ "${1:-}" = "up" ]; then
  ensure_network "$SHARED_NETWORK"
  ensure_network "$LING_SHARED_NETWORK"
fi

COMPOSE_ARGS=()
for arg in "$@"; do
  case "$DEPLOY_ENV:$arg" in
    dev:sage-server|dev:sage-web) COMPOSE_ARGS+=("$arg-dev") ;;
    *) COMPOSE_ARGS+=("$arg") ;;
  esac
done

export SAGE_COMPOSE_ENV_FILE="$ENV_FILE"
export SAGE_SHARED_NETWORK="$SHARED_NETWORK"
export LING_SHARED_NETWORK
export COMPOSE_IGNORE_ORPHANS="${COMPOSE_IGNORE_ORPHANS:-true}"
exec "${COMPOSE_COMMAND[@]}" \
  --env-file "$ENV_FILE" -p "$ENV_PROJECT_NAME" -f "$COMPOSE_FILE" \
  "${COMPOSE_ARGS[@]}"
