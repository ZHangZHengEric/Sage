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
  docker compose --env-file deploy/<env>/.env -f deploy/<env>/docker-compose.yml ...

For `up`, shared services are reused when they are already running in another
environment. Otherwise they are started under the shared compose project
`sage_shared` first, then the selected environment is started.

Observability services (prometheus, grafana, cadvisor, loki, alloy) are defined
in deploy/docker-compose.observability.yml and are not started unless
--observability is set.

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
OBSERVABILITY_COMPOSE_FILE="$DEPLOY_DIR/docker-compose.observability.yml"
SHARED_PROJECT_NAME="${SAGE_SHARED_PROJECT_NAME:-sage_shared}"
SHARED_CONTAINER_PREFIX="${SAGE_SHARED_CONTAINER_PREFIX:-sage-shared}"

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

if [ "$ENABLE_OBSERVABILITY" = "true" ] && [ ! -f "$OBSERVABILITY_COMPOSE_FILE" ]; then
  echo "Observability compose file not found: $OBSERVABILITY_COMPOSE_FILE" >&2
  exit 1
fi

if [ ! -f "$ENV_FILE" ]; then
  echo "Env file not found: $ENV_FILE" >&2
  echo "Create it from: $DEPLOY_DIR/$DEPLOY_ENV/.env.example or $ROOT_DIR/.env.example" >&2
  exit 1
fi

COMPOSE_ARGS=(--env-file "$ENV_FILE" -f "$COMPOSE_FILE" -f "$SHARED_COMPOSE_FILE")
ENV_COMPOSE_ARGS=(--env-file "$ENV_FILE" -f "$COMPOSE_FILE")
SHARED_COMPOSE_ARGS=(--env-file "$ENV_FILE" -p "$SHARED_PROJECT_NAME" -f "$SHARED_COMPOSE_FILE")
OBSERVABILITY_COMPOSE_ARGS=(--env-file "$ENV_FILE" -p "$SHARED_PROJECT_NAME" -f "$OBSERVABILITY_COMPOSE_FILE")
if [ "$ENABLE_OBSERVABILITY" = "true" ]; then
  COMPOSE_ARGS+=(-f "$OBSERVABILITY_COMPOSE_FILE")
fi

env_value() {
  local key="$1"
  awk -F= -v key="$key" '
    $0 ~ /^[[:space:]]*(#|$)/ { next }
    {
      line=$0
      sub(/^[[:space:]]*export[[:space:]]+/, "", line)
      split(line, parts, "=")
      name=parts[1]
      gsub(/^[[:space:]]+|[[:space:]]+$/, "", name)
      if (name == key) {
        sub(/^[^=]*=/, "", line)
        sub(/[[:space:]]+#.*$/, "", line)
        gsub(/^[[:space:]]+|[[:space:]]+$/, "", line)
        gsub(/^["'\''"]|["'\''"]$/, "", line)
        print line
        exit
      }
    }
  ' "$ENV_FILE"
}

CURRENT_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-$(env_value COMPOSE_PROJECT_NAME)}"

shared_container_for_project() {
  local project="$1"
  if [ -z "$project" ]; then
    return 0
  fi
  docker ps \
    --filter "status=running" \
    --filter "label=com.docker.compose.service=sage-rustfs" \
    --filter "label=com.docker.compose.project=$project" \
    --format '{{.ID}}' \
    | head -n 1
}

shared_container_outside_current_project() {
  docker ps \
    --filter "status=running" \
    --filter "label=com.docker.compose.service=sage-rustfs" \
    --format '{{.ID}} {{.Label "com.docker.compose.project"}}' \
    | awk -v current="$CURRENT_PROJECT_NAME" '$2 != current { print $1; exit }'
}

network_for_container() {
  local container_id="$1"
  docker inspect \
    --format '{{range $name, $_ := .NetworkSettings.Networks}}{{println $name}}{{end}}' \
    "$container_id" \
    | head -n 1
}

run_compose() {
  local shared_network="${1:-}"
  shift || true

  SAGE_REPO_ROOT="$ROOT_DIR" \
  SAGE_DEPLOY_DIR="$DEPLOY_DIR" \
  SAGE_COMPOSE_ENV_FILE="$ENV_FILE" \
  SAGE_SHARED_NETWORK="$shared_network" \
  COMPOSE_IGNORE_ORPHANS="${COMPOSE_IGNORE_ORPHANS:-true}" \
    docker compose "$@"
}

start_observability() {
  local shared_network="$1"

  COMPOSE_PROJECT_NAME="$SHARED_PROJECT_NAME" \
  SAGE_CONTAINER_PREFIX="$SHARED_CONTAINER_PREFIX" \
    run_compose "$shared_network" "${OBSERVABILITY_COMPOSE_ARGS[@]}" up -d
}

if [ "${1:-}" = "up" ]; then
  if current_shared_id="$(shared_container_for_project "$CURRENT_PROJECT_NAME")" && [ -n "$current_shared_id" ]; then
    shared_network="$(network_for_container "$current_shared_id")"
    if [ -z "$shared_network" ]; then
      echo "Shared service is running but its Docker network could not be detected." >&2
      exit 1
    fi
    run_compose "$shared_network" "${ENV_COMPOSE_ARGS[@]}" "$@"
    if [ "$ENABLE_OBSERVABILITY" = "true" ]; then
      start_observability "$shared_network"
    fi
    exit $?
  fi

  if shared_id="$(shared_container_outside_current_project)" && [ -n "$shared_id" ]; then
    shared_network="$(network_for_container "$shared_id")"
    if [ -z "$shared_network" ]; then
      echo "Shared service is running but its Docker network could not be detected." >&2
      exit 1
    fi
    run_compose "$shared_network" "${ENV_COMPOSE_ARGS[@]}" "$@"
    if [ "$ENABLE_OBSERVABILITY" = "true" ]; then
      start_observability "$shared_network"
    fi
    exit $?
  fi

  COMPOSE_PROJECT_NAME="$SHARED_PROJECT_NAME" \
  SAGE_CONTAINER_PREFIX="$SHARED_CONTAINER_PREFIX" \
    run_compose "" "${SHARED_COMPOSE_ARGS[@]}" up -d
  run_compose "${SHARED_PROJECT_NAME}_default" "${ENV_COMPOSE_ARGS[@]}" "$@"
  if [ "$ENABLE_OBSERVABILITY" = "true" ]; then
    start_observability "${SHARED_PROJECT_NAME}_default"
  fi
  exit $?
fi

run_compose "" "${COMPOSE_ARGS[@]}" "$@"
