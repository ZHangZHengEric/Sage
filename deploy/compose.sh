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
  deploy/compose.sh --observability up -d sage-grafana
  deploy/compose.sh up -d sage-redis
  deploy/compose.sh dev --observability up -d
  deploy/compose.sh dev up -d
  deploy/compose.sh prod pull
  deploy/compose.sh test down

The script runs:
  docker compose --env-file deploy/<env>/.env -f deploy/<env>/docker-compose.yml ...

If Docker Compose v2 is unavailable, the script falls back to docker-compose.

For `up`, the script ensures the shared Docker network exists, starts shared
services under the `sage_shared` compose project first, then starts the selected
environment.

Observability services (prometheus, cadvisor, loki, alloy, jaeger) are defined
in deploy/docker-compose.observability.yml and are not started unless
--observability is set. Grafana is optional and only starts when explicitly
targeted.

If deploy/<env>/.env is missing, it falls back to .env in the repo root.

`up` 部署流程保留 Docker Compose 原生输出。
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
PROMETHEUS_BASE_CONFIG="$DEPLOY_DIR/monitoring/prometheus.yml"
PROMETHEUS_LOCAL_CONFIG="${SAGE_PROMETHEUS_LOCAL_CONFIG_FILE:-$DEPLOY_DIR/monitoring/prometheus.local.yml}"
PROMETHEUS_GENERATED_CONFIG="${SAGE_PROMETHEUS_GENERATED_CONFIG_FILE:-$DEPLOY_DIR/monitoring/prometheus.generated.yml}"
PROMETHEUS_CONFIG_FILE="$PROMETHEUS_BASE_CONFIG"
ENV_PROJECT_NAME="${SAGE_COMPOSE_PROJECT_NAME:-${COMPOSE_PROJECT_NAME:-sage_$DEPLOY_ENV}}"
SHARED_PROJECT_NAME="${SAGE_SHARED_PROJECT_NAME:-sage_shared}"
SHARED_NETWORK="${SAGE_SHARED_NETWORK:-sage_shared_default}"
COMPOSE_COMMAND=()

detect_compose_command() {
  if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
    COMPOSE_COMMAND=(docker compose)
    return 0
  fi

  if command -v docker-compose >/dev/null 2>&1; then
    COMPOSE_COMMAND=(docker-compose)
    return 0
  fi

  echo "Docker Compose not found. Install Docker Compose v2 or docker-compose." >&2
  exit 1
}

detect_compose_command

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

absolute_path() {
  case "$1" in
    /*)
      printf '%s' "$1"
      ;;
    *)
      printf '%s/%s' "$(pwd)" "$1"
      ;;
  esac
}

prepare_prometheus_config() {
  if [ -n "${SAGE_PROMETHEUS_CONFIG_FILE:-}" ]; then
    PROMETHEUS_CONFIG_FILE="$(absolute_path "$SAGE_PROMETHEUS_CONFIG_FILE")"
    return 0
  fi

  PROMETHEUS_LOCAL_CONFIG="$(absolute_path "$PROMETHEUS_LOCAL_CONFIG")"
  PROMETHEUS_GENERATED_CONFIG="$(absolute_path "$PROMETHEUS_GENERATED_CONFIG")"

  if [ ! -f "$PROMETHEUS_BASE_CONFIG" ]; then
    echo "Prometheus config not found: $PROMETHEUS_BASE_CONFIG" >&2
    exit 1
  fi

  if [ -s "$PROMETHEUS_LOCAL_CONFIG" ]; then
    local tmp_config
    tmp_config="${PROMETHEUS_GENERATED_CONFIG}.tmp"
    {
      cat "$PROMETHEUS_BASE_CONFIG"
      printf '\n\n# Local scrape jobs from %s\n' "$PROMETHEUS_LOCAL_CONFIG"
      cat "$PROMETHEUS_LOCAL_CONFIG"
      printf '\n'
    } > "$tmp_config"
    mv "$tmp_config" "$PROMETHEUS_GENERATED_CONFIG"
    PROMETHEUS_CONFIG_FILE="$PROMETHEUS_GENERATED_CONFIG"
  else
    PROMETHEUS_CONFIG_FILE="$PROMETHEUS_BASE_CONFIG"
  fi
}

if [ "$ENABLE_OBSERVABILITY" = "true" ]; then
  prepare_prometheus_config
fi

COMPOSE_ARGS=(--env-file "$ENV_FILE" -p "$ENV_PROJECT_NAME" -f "$COMPOSE_FILE" -f "$SHARED_COMPOSE_FILE")
ENV_COMPOSE_ARGS=(--env-file "$ENV_FILE" -p "$ENV_PROJECT_NAME" -f "$COMPOSE_FILE")
SHARED_COMPOSE_ARGS=(--env-file "$ENV_FILE" -p "$SHARED_PROJECT_NAME" -f "$SHARED_COMPOSE_FILE")
OBSERVABILITY_COMPOSE_ARGS=(--env-file "$ENV_FILE" -p "$SHARED_PROJECT_NAME" -f "$OBSERVABILITY_COMPOSE_FILE")
if [ "$ENABLE_OBSERVABILITY" = "true" ]; then
  COMPOSE_ARGS+=(-f "$OBSERVABILITY_COMPOSE_FILE")
fi
SHARED_SERVICES=(sage-wiki sage-rustfs sage-redis)
OBSERVABILITY_SERVICES=(sage-prometheus sage-grafana sage-cadvisor sage-loki sage-alloy sage-jaeger)

case "$DEPLOY_ENV" in
  prod)
    ENV_SERVICES=(sage-server sage-web sage-mysql sage-es)
    ENV_SERVICE_ORDER=(sage-mysql sage-es sage-server sage-web)
    ;;
  dev|test)
    ENV_SERVICES=("sage-server-$DEPLOY_ENV" "sage-web-$DEPLOY_ENV" "sage-mysql-$DEPLOY_ENV")
    ENV_SERVICE_ORDER=("sage-mysql-$DEPLOY_ENV" "sage-server-$DEPLOY_ENV" "sage-web-$DEPLOY_ENV")
    ;;
esac

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

normalize_env_service() {
  local service="$1"

  if contains_service "$service" "${ENV_SERVICES[@]}"; then
    printf '%s' "$service"
    return 0
  fi

  case "$DEPLOY_ENV:$service" in
    dev:sage-server|test:sage-server)
      printf 'sage-server-%s' "$DEPLOY_ENV"
      return 0
      ;;
    dev:sage-web|test:sage-web)
      printf 'sage-web-%s' "$DEPLOY_ENV"
      return 0
      ;;
    dev:sage-mysql|test:sage-mysql)
      printf 'sage-mysql-%s' "$DEPLOY_ENV"
      return 0
      ;;
  esac

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
  :
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

log_unchanged() {
  log_line "无更新：$*"
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
  for arg in "${ACTIVE_UP_ARGS[@]}"; do
    if [ "$arg" = "--build" ]; then
      printf '构建检查并启动'
      return 0
    fi
  done

  printf '启动'
}

append_up_arg() {
  local arg="$1"
  local env_service

  if env_service="$(normalize_env_service "$arg")"; then
    UP_HAS_TARGETS="true"
    UP_ENV_TARGETS+=("$env_service")
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
    "SAGE_PROMETHEUS_CONFIG_FILE=$PROMETHEUS_CONFIG_FILE"
    "COMPOSE_IGNORE_ORPHANS=${COMPOSE_IGNORE_ORPHANS:-true}"
  )

  env "${compose_env[@]}" "${COMPOSE_COMMAND[@]}" "$@" config --services 2>/dev/null
}

run_compose() {
  local shared_network="${1:-$SHARED_NETWORK}"
  shift || true
  local compose_env=(
    "SAGE_REPO_ROOT=$ROOT_DIR"
    "SAGE_DEPLOY_DIR=$DEPLOY_DIR"
    "SAGE_COMPOSE_ENV_FILE=$ENV_FILE"
    "SAGE_SHARED_NETWORK=$shared_network"
    "SAGE_PROMETHEUS_CONFIG_FILE=$PROMETHEUS_CONFIG_FILE"
    "COMPOSE_IGNORE_ORPHANS=${COMPOSE_IGNORE_ORPHANS:-true}"
  )

  env "${compose_env[@]}" "${COMPOSE_COMMAND[@]}" "$@"
}

ordered_group_services() {
  local group="$1"
  shift
  local services=("$@")
  local preferred=()
  local service

  case "$group" in
    env)
      preferred=("${ENV_SERVICE_ORDER[@]}")
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
      if [ "$group" = "observability" ] && [ "$service" = "sage-grafana" ]; then
        continue
      fi
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
  local elapsed_seconds
  local elapsed

  action="$(up_action_label)"

  for service in "${services[@]}"; do
    service_start=$SECONDS
    log_step "${group_label}服务 ${service}（${action}）"
    case "$group" in
      env)
        if run_compose "$shared_network" "${ENV_COMPOSE_ARGS[@]}" "${ACTIVE_UP_ARGS[@]}" "$service"; then
          elapsed_seconds=$((SECONDS - service_start))
          if [ "$elapsed_seconds" -eq 0 ]; then
            log_unchanged "${group_label}服务 $service"
          else
            elapsed="$(format_elapsed "$elapsed_seconds")"
            log_done "${group_label}服务 $service" "$elapsed"
          fi
        else
          elapsed="$(format_elapsed "$((SECONDS - service_start))")"
          log_fail "${group_label}服务 $service" "$elapsed"
          return 1
        fi
        ;;
      shared)
        if start_shared "$shared_network" "${ACTIVE_UP_ARGS[@]}" "$service"; then
          elapsed_seconds=$((SECONDS - service_start))
          if [ "$elapsed_seconds" -eq 0 ]; then
            log_unchanged "${group_label}服务 $service"
          else
            elapsed="$(format_elapsed "$elapsed_seconds")"
            log_done "${group_label}服务 $service" "$elapsed"
          fi
        else
          elapsed="$(format_elapsed "$((SECONDS - service_start))")"
          log_fail "${group_label}服务 $service" "$elapsed"
          return 1
        fi
        ;;
      observability)
        if start_observability "$shared_network" "${ACTIVE_UP_ARGS[@]}" "$service"; then
          elapsed_seconds=$((SECONDS - service_start))
          if [ "$elapsed_seconds" -eq 0 ]; then
            log_unchanged "${group_label}服务 $service"
          else
            elapsed="$(format_elapsed "$elapsed_seconds")"
            log_done "${group_label}服务 $service" "$elapsed"
          fi
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
  prepare_up_args "$@"
  ACTIVE_UP_ARGS=("${UP_ARGS[@]}")

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

if [ "$ENABLE_OBSERVABILITY" = "true" ] && [ "${1:-}" = "down" ]; then
  start_observability "$SHARED_NETWORK" "$@"
  exit 0
fi

run_compose "" "${COMPOSE_ARGS[@]}" "$@"
