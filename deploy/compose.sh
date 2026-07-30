#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEPLOY_DIR="$ROOT_DIR/deploy"
DEPLOY_ENV="${DEPLOY_ENV:-prod}"

usage() {
  cat <<'EOF'
Usage: deploy/compose.sh [dev|prod|test] [docker compose args...]

Examples:
  deploy/compose.sh prod up -d --build
  deploy/compose.sh dev up -d sage-server
  deploy/compose.sh test down

Only two services are defined: sage-server and sage-web.
If deploy/<env>/.env does not exist, the script falls back to the repo-root .env.
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

COMPOSE_FILE="$DEPLOY_DIR/$DEPLOY_ENV/docker-compose.yml"
ENV_FILE="${ENV_FILE:-$DEPLOY_DIR/$DEPLOY_ENV/.env}"
PROJECT_NAME="${SAGE_COMPOSE_PROJECT_NAME:-sage_$DEPLOY_ENV}"

if [ ! -f "$ENV_FILE" ]; then
  ENV_FILE="$ROOT_DIR/.env"
fi
if [ ! -f "$ENV_FILE" ]; then
  echo "Env file not found. Create deploy/$DEPLOY_ENV/.env from its .env.example." >&2
  exit 1
fi
if [ ! -f "$COMPOSE_FILE" ]; then
  echo "Compose file not found: $COMPOSE_FILE" >&2
  exit 1
fi

if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
  COMPOSE_COMMAND=(docker compose)
elif command -v docker-compose >/dev/null 2>&1; then
  COMPOSE_COMMAND=(docker-compose)
else
  echo "Docker Compose not found." >&2
  exit 1
fi

ARGS=("$@")
if [ "${1:-}" = "up" ]; then
  has_target=false
  has_no_deps=false
  for arg in "${ARGS[@]}"; do
    case "$arg" in
      sage-server|sage-web) has_target=true ;;
      --no-deps) has_no_deps=true ;;
    esac
  done
  if [ "$has_target" = true ] && [ "$has_no_deps" = false ]; then
    ARGS+=(--no-deps)
  fi
fi

SAGE_COMPOSE_ENV_FILE="$ENV_FILE" \
  exec "${COMPOSE_COMMAND[@]}" \
  --env-file "$ENV_FILE" \
  -p "$PROJECT_NAME" \
  -f "$COMPOSE_FILE" \
  "${ARGS[@]}"
