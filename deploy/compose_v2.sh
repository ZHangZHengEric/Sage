#!/usr/bin/env bash
set -euo pipefail

DEPLOY_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ "$#" -eq 0 ] || [ "${1:-}" = "--help" ] || [ "${1:-}" = "-h" ]; then
  cat <<'EOF'
Usage: deploy/compose_v2.sh [docker compose args...]

Starts Sage Server v2 and its Web UI, using separately deployed MySQL.

Examples:
  deploy/compose_v2.sh up -d --build
  deploy/compose_v2.sh down
  deploy/compose_v2.sh logs -f sage-server
  deploy/compose_v2.sh config --services

Default env file: deploy/standalone/.env
Override with ENV_FILE=/path/to/.env.
Default project: sage_standalone
Override with SAGE_COMPOSE_PROJECT_NAME.
EOF
  exit 0
fi

ENV_FILE="${ENV_FILE:-$DEPLOY_DIR/standalone/.env}"
case "$ENV_FILE" in
  /*) ;;
  *) ENV_FILE="$PWD/$ENV_FILE" ;;
esac

if [ ! -f "$ENV_FILE" ]; then
  echo "Env file not found: $ENV_FILE" >&2
  echo "Create it from: $DEPLOY_DIR/standalone/.env.example" >&2
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

export SAGE_COMPOSE_ENV_FILE="$ENV_FILE"
exec "${COMPOSE_COMMAND[@]}" \
  --env-file "$ENV_FILE" \
  -f "$DEPLOY_DIR/standalone/docker-compose.yml" \
  -p "${SAGE_COMPOSE_PROJECT_NAME:-sage_standalone}" \
  "$@"
