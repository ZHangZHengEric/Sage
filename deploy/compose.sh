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
  deploy/compose.sh --observability up -d sage-jaeger
  deploy/compose.sh up -d sage-redis
  deploy/compose.sh dev --observability up -d
  deploy/compose.sh dev up -d
  deploy/compose.sh prod pull
  deploy/compose.sh test down

The script runs:
  docker compose --env-file deploy/<env>/.env -f deploy/<env>/docker-compose.yml ...

For `up`, the script ensures the shared Docker network exists, starts shared
services under the `sage_shared` compose project first, then starts the selected
environment.

Observability services (prometheus, grafana, cadvisor, loki, alloy, jaeger) are
defined in deploy/docker-compose.observability.yml and are not started unless
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
SHARED_NETWORK="${SAGE_SHARED_NETWORK:-sage_shared_default}"

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
ENV_SERVICES=(sage-server sage-web sage-mysql sage-es)
SHARED_SERVICES=(sage-wiki sage-rustfs sage-redis)
OBSERVABILITY_SERVICES=(sage-prometheus sage-grafana sage-cadvisor sage-loki sage-alloy sage-jaeger)

contains_service() {
  local service="$1"
  shift
  local item
  for item in "$@"; do
    if [ "$item" = "$service" ]; then
      return 0
    fi
  done
  return 1
}

append_up_arg() {
  local arg="$1"

  if contains_service "$arg" "${ENV_SERVICES[@]}"; then
    UP_HAS_TARGETS="true"
    UP_ENV_TARGETS+=("$arg")
    return 0
  fi

  if contains_service "$arg" "${SHARED_SERVICES[@]}"; then
    UP_HAS_TARGETS="true"
    UP_SHARED_TARGETS+=("$arg")
    return 0
  fi

  if contains_service "$arg" "${OBSERVABILITY_SERVICES[@]}"; then
    UP_HAS_TARGETS="true"
    UP_OBSERVABILITY_TARGETS+=("$arg")
    return 0
  fi

  UP_ARGS+=("$arg")
}

prepare_up_args() {
  UP_ARGS=(up)
  UP_ENV_TARGETS=()
  UP_SHARED_TARGETS=()
  UP_OBSERVABILITY_TARGETS=()
  UP_HAS_TARGETS="false"

  shift
  local arg
  for arg in "$@"; do
    append_up_arg "$arg"
  done
}

ensure_shared_network() {
  if docker network inspect "$SHARED_NETWORK" >/dev/null 2>&1; then
    return 0
  fi

  docker network create "$SHARED_NETWORK" >/dev/null
}

run_compose() {
  local shared_network="${1:-$SHARED_NETWORK}"
  shift || true
  local compose_env=(
    "SAGE_REPO_ROOT=$ROOT_DIR"
    "SAGE_DEPLOY_DIR=$DEPLOY_DIR"
    "SAGE_COMPOSE_ENV_FILE=$ENV_FILE"
    "SAGE_SHARED_NETWORK=$shared_network"
    "COMPOSE_IGNORE_ORPHANS=${COMPOSE_IGNORE_ORPHANS:-true}"
  )

  env "${compose_env[@]}" docker compose "$@"
}

start_shared() {
  local shared_network="$1"
  shift

  COMPOSE_PROJECT_NAME="$SHARED_PROJECT_NAME" \
    run_compose "$shared_network" "${SHARED_COMPOSE_ARGS[@]}" "$@"
}

start_observability() {
  local shared_network="$1"
  shift

  COMPOSE_PROJECT_NAME="$SHARED_PROJECT_NAME" \
    run_compose "$shared_network" "${OBSERVABILITY_COMPOSE_ARGS[@]}" "$@"
}

if [ "${1:-}" = "up" ]; then
  prepare_up_args "$@"

  if [ "${#UP_OBSERVABILITY_TARGETS[@]}" -gt 0 ] && [ "$ENABLE_OBSERVABILITY" != "true" ]; then
    echo "Observability service requested without --observability: ${UP_OBSERVABILITY_TARGETS[*]}" >&2
    exit 1
  fi

  RUN_ENV_UP="false"
  RUN_SHARED_UP="false"
  RUN_OBSERVABILITY_UP="false"

  if [ "$UP_HAS_TARGETS" = "false" ]; then
    RUN_ENV_UP="true"
    RUN_SHARED_UP="true"
    if [ "$ENABLE_OBSERVABILITY" = "true" ]; then
      RUN_OBSERVABILITY_UP="true"
    fi
  else
    if [ "${#UP_ENV_TARGETS[@]}" -gt 0 ]; then
      RUN_ENV_UP="true"
    fi
    if [ "${#UP_SHARED_TARGETS[@]}" -gt 0 ]; then
      RUN_SHARED_UP="true"
    fi
    if [ "${#UP_OBSERVABILITY_TARGETS[@]}" -gt 0 ]; then
      RUN_OBSERVABILITY_UP="true"
    fi
  fi

  ensure_shared_network
  shared_network="$SHARED_NETWORK"

  if [ "$RUN_SHARED_UP" = "true" ]; then
    if [ "$UP_HAS_TARGETS" = "true" ]; then
      start_shared "$shared_network" "${UP_ARGS[@]}" "${UP_SHARED_TARGETS[@]}"
    else
      start_shared "$shared_network" "${UP_ARGS[@]}"
    fi
  elif [ "$RUN_ENV_UP" = "true" ] || [ "$RUN_OBSERVABILITY_UP" = "true" ]; then
    start_shared "$shared_network" up -d
  fi

  if [ "$RUN_ENV_UP" = "true" ]; then
    if [ "$UP_HAS_TARGETS" = "true" ]; then
      run_compose "$shared_network" "${ENV_COMPOSE_ARGS[@]}" "${UP_ARGS[@]}" "${UP_ENV_TARGETS[@]}"
    else
      run_compose "$shared_network" "${ENV_COMPOSE_ARGS[@]}" "${UP_ARGS[@]}"
    fi
  fi
  if [ "$RUN_OBSERVABILITY_UP" = "true" ]; then
    if [ "$UP_HAS_TARGETS" = "true" ]; then
      start_observability "$shared_network" "${UP_ARGS[@]}" "${UP_OBSERVABILITY_TARGETS[@]}"
    else
      start_observability "$shared_network" "${UP_ARGS[@]}"
    fi
  fi
  exit 0
fi

run_compose "" "${COMPOSE_ARGS[@]}" "$@"
