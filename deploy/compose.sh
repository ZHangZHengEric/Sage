#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEPLOY_DIR="$ROOT_DIR/deploy"
DEPLOY_ENV="${DEPLOY_ENV:-prod}"

usage() {
  cat <<'EOF'
Usage: deploy/compose.sh [dev|prod|test] [docker compose args...]

Examples:
  deploy/compose.sh dev up -d
  deploy/compose.sh prod pull
  deploy/compose.sh test down

The script runs:
  docker compose --env-file deploy/<env>/.env -f deploy/<env>/docker-compose.yml ...
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

if [ ! -f "$COMPOSE_FILE" ]; then
  echo "Compose file not found: $COMPOSE_FILE" >&2
  exit 1
fi

if [ ! -f "$ENV_FILE" ]; then
  echo "Env file not found: $ENV_FILE" >&2
  echo "Create it from: $DEPLOY_DIR/$DEPLOY_ENV/.env.example" >&2
  exit 1
fi

docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" "$@"
