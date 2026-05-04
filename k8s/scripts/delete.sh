#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
K8S_DIR="$ROOT_DIR/k8s"
ENV_FILE="${ENV_FILE:-$K8S_DIR/.env}"

load_env_file() {
  local env_file="$1"
  [ -f "$env_file" ] || return 0
  while IFS= read -r line || [ -n "$line" ]; do
    case "$line" in
      ''|\#*) continue ;;
    esac
    local key="${line%%=*}"
    local value="${line#*=}"
    [ "$key" = "$line" ] && continue
    export "$key=$value"
  done < "$env_file"
}

load_env_file "$ENV_FILE"

NAMESPACE="${NAMESPACE:-sage}"
DELETE_PVCS="${DELETE_PVCS:-false}"
DELETE_NAMESPACE="${DELETE_NAMESPACE:-false}"

kubectl -n "$NAMESPACE" delete ingress sage sage-wiki --ignore-not-found
kubectl -n "$NAMESPACE" delete statefulset sage-mysql --ignore-not-found
kubectl -n "$NAMESPACE" delete deployment sage-server sage-web sage-wiki sage-es sage-rustfs sage-jaeger --ignore-not-found
kubectl -n "$NAMESPACE" delete service sage-server sage-web sage-wiki sage-mysql sage-es sage-rustfs sage-jaeger --ignore-not-found
kubectl -n "$NAMESPACE" delete configmap sage-config sage-jaeger-config --ignore-not-found
kubectl -n "$NAMESPACE" delete secret sage-secrets --ignore-not-found

if [ "$DELETE_PVCS" = "true" ]; then
  kubectl -n "$NAMESPACE" delete pvc \
    sage-server-sessions \
    sage-server-agents \
    sage-server-logs \
    sage-server-data \
    sage-server-skills \
    sage-server-users \
    sage-mysql-data \
    sage-mysql-conf \
    sage-es-data \
    sage-rustfs-data \
    --ignore-not-found
else
  echo "PVCs were preserved. Re-run with DELETE_PVCS=true to delete persistent data."
fi

if [ "$DELETE_NAMESPACE" = "true" ]; then
  kubectl delete namespace "$NAMESPACE" --ignore-not-found
fi
