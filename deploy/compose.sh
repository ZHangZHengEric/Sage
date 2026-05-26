#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEPLOY_DIR="$ROOT_DIR/deploy"
DEPLOY_ENV="${DEPLOY_ENV:-prod}"
SAGE_DEPLOY_OUTPUT="${SAGE_DEPLOY_OUTPUT:-progress}"
FILTER_COMPOSE_OUTPUT="false"

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

`up` 部署流程默认隐藏 Docker Compose 原生输出，改为打印部署进度。
设置 SAGE_DEPLOY_OUTPUT=raw 可直接显示 Docker Compose 原生输出。
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

timestamp() {
  date '+%Y-%m-%d %H:%M:%S'
}

format_elapsed() {
  local elapsed="$1"
  local minutes=$((elapsed / 60))
  local seconds=$((elapsed % 60))

  if [ "$minutes" -gt 0 ]; then
    printf '%dm%02ds' "$minutes" "$seconds"
  else
    printf '%ds' "$seconds"
  fi
}

log_line() {
  if [ "$SAGE_DEPLOY_OUTPUT" = "progress" ]; then
    printf '[%s] [Sage 部署] %s\n' "$(timestamp)" "$*" >&2
  fi
}

log_step() {
  log_line "开始：$*"
}

log_done() {
  local message="$1"
  local elapsed="${2:-}"

  if [ -n "$elapsed" ]; then
    log_line "完成：${message}（耗时 ${elapsed}）"
  else
    log_line "完成：${message}"
  fi
}

log_fail() {
  local message="$1"
  local elapsed="${2:-}"

  if [ -n "$elapsed" ]; then
    log_line "失败：${message}（耗时 ${elapsed}）"
  else
    log_line "失败：${message}"
  fi
}

format_targets() {
  if [ "$#" -eq 0 ]; then
    printf '全部'
    return 0
  fi

  printf '%s' "$*"
}

up_action_label() {
  local arg
  for arg in "${UP_ARGS[@]}"; do
    if [ "$arg" = "--build" ]; then
      printf '构建并启动'
      return 0
    fi
  done

  printf '启动'
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

compose_config_services() {
  local shared_network="${1:-$SHARED_NETWORK}"
  shift || true
  local compose_env=(
    "SAGE_REPO_ROOT=$ROOT_DIR"
    "SAGE_DEPLOY_DIR=$DEPLOY_DIR"
    "SAGE_COMPOSE_ENV_FILE=$ENV_FILE"
    "SAGE_SHARED_NETWORK=$shared_network"
    "COMPOSE_IGNORE_ORPHANS=${COMPOSE_IGNORE_ORPHANS:-true}"
  )

  env "${compose_env[@]}" docker compose "$@" config --services 2>/dev/null
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

  if [ "$FILTER_COMPOSE_OUTPUT" != "true" ] || [ "$SAGE_DEPLOY_OUTPUT" = "raw" ]; then
    env "${compose_env[@]}" docker compose "$@"
    return
  fi

  local log_file
  log_file="$(mktemp "${TMPDIR:-/tmp}/sage-compose.XXXXXX")"

  if env "${compose_env[@]}" docker compose --ansi never --progress quiet "$@" >"$log_file" 2>&1; then
    rm -f "$log_file"
    return 0
  else
    local status=$?
    log_line "Docker Compose 执行失败，原始输出如下："
    cat "$log_file" >&2
    rm -f "$log_file"
    return "$status"
  fi
}

ordered_group_services() {
  local group="$1"
  shift
  local services=("$@")
  local preferred=()
  local service

  case "$group" in
    env)
      preferred=(sage-mysql sage-es sage-server sage-web)
      ;;
    shared)
      preferred=(sage-redis sage-rustfs sage-wiki)
      ;;
    observability)
      preferred=(sage-cadvisor sage-loki sage-jaeger sage-prometheus sage-alloy sage-grafana)
      ;;
  esac

  for service in "${preferred[@]}"; do
    if contains_service "$service" "${services[@]}"; then
      printf '%s\n' "$service"
    fi
  done

  for service in "${services[@]}"; do
    if ! contains_service "$service" "${preferred[@]}"; then
      printf '%s\n' "$service"
    fi
  done
}

configured_group_services() {
  local group="$1"
  local shared_network="$2"
  shift 2
  local services=()
  local service

  while IFS= read -r service; do
    if [ -n "$service" ]; then
      services+=("$service")
    fi
  done < <(compose_config_services "$shared_network" "$@")

  ordered_group_services "$group" "${services[@]}"
}

run_group_services() {
  local group="$1"
  local group_label="$2"
  local shared_network="$3"
  shift 3
  local services=("$@")
  local action
  local service
  local service_start
  local elapsed

  action="$(up_action_label)"

  for service in "${services[@]}"; do
    service_start=$SECONDS
    log_step "${group_label}服务 ${service}（${action}）"
    case "$group" in
      env)
        if run_compose "$shared_network" "${ENV_COMPOSE_ARGS[@]}" "${UP_ARGS[@]}" "$service"; then
          elapsed="$(format_elapsed "$((SECONDS - service_start))")"
          log_done "${group_label}服务 $service" "$elapsed"
        else
          elapsed="$(format_elapsed "$((SECONDS - service_start))")"
          log_fail "${group_label}服务 $service" "$elapsed"
          return 1
        fi
        ;;
      shared)
        if start_shared "$shared_network" "${UP_ARGS[@]}" "$service"; then
          elapsed="$(format_elapsed "$((SECONDS - service_start))")"
          log_done "${group_label}服务 $service" "$elapsed"
        else
          elapsed="$(format_elapsed "$((SECONDS - service_start))")"
          log_fail "${group_label}服务 $service" "$elapsed"
          return 1
        fi
        ;;
      observability)
        if start_observability "$shared_network" "${UP_ARGS[@]}" "$service"; then
          elapsed="$(format_elapsed "$((SECONDS - service_start))")"
          log_done "${group_label}服务 $service" "$elapsed"
        else
          elapsed="$(format_elapsed "$((SECONDS - service_start))")"
          log_fail "${group_label}服务 $service" "$elapsed"
          return 1
        fi
        ;;
    esac
  done
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
  FILTER_COMPOSE_OUTPUT="true"
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

  network_start=$SECONDS
  log_step "共享网络 ${SHARED_NETWORK}（准备）"
  ensure_shared_network
  log_done "共享网络 ${SHARED_NETWORK}" "$(format_elapsed "$((SECONDS - network_start))")"
  shared_network="$SHARED_NETWORK"

  if [ "$RUN_SHARED_UP" = "true" ]; then
    if [ "$UP_HAS_TARGETS" = "true" ]; then
      SHARED_RUN_TARGETS=("${UP_SHARED_TARGETS[@]}")
    else
      SHARED_RUN_TARGETS=()
      while IFS= read -r service; do
        SHARED_RUN_TARGETS+=("$service")
      done < <(configured_group_services shared "$shared_network" "${SHARED_COMPOSE_ARGS[@]}")
    fi

    run_group_services shared 共享 "$shared_network" "${SHARED_RUN_TARGETS[@]}"
  elif [ "$RUN_ENV_UP" = "true" ] || [ "$RUN_OBSERVABILITY_UP" = "true" ]; then
    SHARED_RUN_TARGETS=()
    while IFS= read -r service; do
      SHARED_RUN_TARGETS+=("$service")
    done < <(configured_group_services shared "$shared_network" "${SHARED_COMPOSE_ARGS[@]}")

    run_group_services shared 共享 "$shared_network" "${SHARED_RUN_TARGETS[@]}"
  fi

  if [ "$RUN_ENV_UP" = "true" ]; then
    if [ "$UP_HAS_TARGETS" = "true" ]; then
      ENV_RUN_TARGETS=("${UP_ENV_TARGETS[@]}")
    else
      ENV_RUN_TARGETS=()
      while IFS= read -r service; do
        ENV_RUN_TARGETS+=("$service")
      done < <(configured_group_services env "$shared_network" "${ENV_COMPOSE_ARGS[@]}")
    fi

    run_group_services env "$DEPLOY_ENV 环境" "$shared_network" "${ENV_RUN_TARGETS[@]}"
  fi
  if [ "$RUN_OBSERVABILITY_UP" = "true" ]; then
    if [ "$UP_HAS_TARGETS" = "true" ]; then
      OBSERVABILITY_RUN_TARGETS=("${UP_OBSERVABILITY_TARGETS[@]}")
    else
      OBSERVABILITY_RUN_TARGETS=()
      while IFS= read -r service; do
        OBSERVABILITY_RUN_TARGETS+=("$service")
      done < <(configured_group_services observability "$shared_network" "${OBSERVABILITY_COMPOSE_ARGS[@]}")
    fi

    run_group_services observability 观测 "$shared_network" "${OBSERVABILITY_RUN_TARGETS[@]}"
  fi
  exit 0
fi

run_compose "" "${COMPOSE_ARGS[@]}" "$@"
