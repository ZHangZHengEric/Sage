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
SAGE_HOST="${SAGE_HOST:-}"
SAGE_PUBLIC_URL="${SAGE_PUBLIC_URL:-}"
IMAGE_REGISTRY="${IMAGE_REGISTRY:-}"
IMAGE_TAG="${IMAGE_TAG:-v1.0}"
STORAGE_CLASS="${STORAGE_CLASS:-}"
INGRESS_CLASS_NAME="${INGRESS_CLASS_NAME:-nginx}"
TLS_SECRET_NAME="${TLS_SECRET_NAME:-}"

if [ -z "$SAGE_HOST" ]; then
  echo "SAGE_HOST is required. Set it in k8s/.env or pass SAGE_HOST=example.com." >&2
  exit 1
fi

if [ -z "$SAGE_PUBLIC_URL" ]; then
  SAGE_PUBLIC_URL="https://$SAGE_HOST"
  export SAGE_PUBLIC_URL
fi

export SAGE_ENV="${SAGE_ENV:-production}"
export SAGE_WEB_BASE_PATH="${SAGE_WEB_BASE_PATH:-/sage}"
export SAGE_TRACE_WEB_URL="${SAGE_TRACE_WEB_URL:-${SAGE_PUBLIC_URL}/jaeger/}"
export SAGE_TRACE_JAEGER_URL="${SAGE_TRACE_JAEGER_URL:-http://sage-jaeger:4317}"
export SAGE_TRACE_JAEGER_UI_URL="${SAGE_TRACE_JAEGER_UI_URL:-http://sage-jaeger:16686/jaeger}"
export SAGE_TRACE_JAEGER_PUBLIC_URL="${SAGE_TRACE_JAEGER_PUBLIC_URL:-${SAGE_PUBLIC_URL}/jaeger}"
export SAGE_TRACE_JAEGER_BASE_PATH="${SAGE_TRACE_JAEGER_BASE_PATH:-/api/observability/jaeger}"
export SAGE_API_BASE_URL="${SAGE_API_BASE_URL:-$SAGE_PUBLIC_URL}"
export SAGE_SANDBOX_MODE="${SAGE_SANDBOX_MODE:-local}"
export SAGE_SANDBOX_MOUNT_PATHS="${SAGE_SANDBOX_MOUNT_PATHS:-}"
export SAGE_LOCAL_CPU_TIME_LIMIT="${SAGE_LOCAL_CPU_TIME_LIMIT:-300}"
export SAGE_LOCAL_MEMORY_LIMIT_MB="${SAGE_LOCAL_MEMORY_LIMIT_MB:-4096}"
export SAGE_LOCAL_LINUX_ISOLATION="${SAGE_LOCAL_LINUX_ISOLATION:-subprocess}"
export SAGE_LOCAL_MACOS_ISOLATION="${SAGE_LOCAL_MACOS_ISOLATION:-seatbelt}"
export SAGE_REMOTE_PROVIDER="${SAGE_REMOTE_PROVIDER:-opensandbox}"
export OPENSANDBOX_URL="${OPENSANDBOX_URL:-}"
export OPENSANDBOX_API_KEY="${OPENSANDBOX_API_KEY:-}"
export OPENSANDBOX_IMAGE="${OPENSANDBOX_IMAGE:-opensandbox/code-interpreter:v1.0.2}"
export OPENSANDBOX_TIMEOUT="${OPENSANDBOX_TIMEOUT:-1800}"
export SAGE_OPENSANDBOX_APPEND_MAX_BYTES="${SAGE_OPENSANDBOX_APPEND_MAX_BYTES:-262144}"
export SAGE_AUTH_MODE="${SAGE_AUTH_MODE:-native}"
export SAGE_TRUSTED_IDENTITY_PROXY_IPS="${SAGE_TRUSTED_IDENTITY_PROXY_IPS:-127.0.0.1/32,10.0.0.0/8}"
export SAGE_BOOTSTRAP_ADMIN_USERNAME="${SAGE_BOOTSTRAP_ADMIN_USERNAME:-admin}"
export SAGE_BOOTSTRAP_ADMIN_PASSWORD="${SAGE_BOOTSTRAP_ADMIN_PASSWORD:-change_this_admin_password}"
export SAGE_AUTH_PROVIDERS="${SAGE_AUTH_PROVIDERS:-}"
export SAGE_JWT_KEY="${SAGE_JWT_KEY:-change_this_jwt_secret}"
export SAGE_REFRESH_TOKEN_SECRET="${SAGE_REFRESH_TOKEN_SECRET:-change_this_refresh_secret}"
export SAGE_SESSION_SECRET="${SAGE_SESSION_SECRET:-change_this_session_secret}"
export SAGE_SESSION_COOKIE_NAME="${SAGE_SESSION_COOKIE_NAME:-sage_session}"
export SAGE_SESSION_COOKIE_SECURE="${SAGE_SESSION_COOKIE_SECURE:-true}"
export SAGE_SESSION_COOKIE_SAME_SITE="${SAGE_SESSION_COOKIE_SAME_SITE:-lax}"
export SAGE_CORS_ALLOWED_ORIGINS="${SAGE_CORS_ALLOWED_ORIGINS:-*}"
export SAGE_CORS_ALLOW_CREDENTIALS="${SAGE_CORS_ALLOW_CREDENTIALS:-false}"
export SAGE_CORS_ALLOW_METHODS="${SAGE_CORS_ALLOW_METHODS:-*}"
export SAGE_CORS_ALLOW_HEADERS="${SAGE_CORS_ALLOW_HEADERS:-*}"
export SAGE_CORS_EXPOSE_HEADERS="${SAGE_CORS_EXPOSE_HEADERS:-}"
export SAGE_CORS_MAX_AGE="${SAGE_CORS_MAX_AGE:-600}"
export SAGE_OAUTH2_CLIENTS="${SAGE_OAUTH2_CLIENTS:-}"
export SAGE_OAUTH2_ISSUER="${SAGE_OAUTH2_ISSUER:-}"
export SAGE_OAUTH2_ACCESS_TOKEN_EXPIRES_IN="${SAGE_OAUTH2_ACCESS_TOKEN_EXPIRES_IN:-3600}"
export SAGE_EML_ENDPOINT="${SAGE_EML_ENDPOINT:-dm.aliyuncs.com}"
export SAGE_EML_ACCESS_KEY_ID="${SAGE_EML_ACCESS_KEY_ID:-}"
export SAGE_EML_ACCESS_KEY_SECRET="${SAGE_EML_ACCESS_KEY_SECRET:-}"
export SAGE_EML_SECURITY_TOKEN="${SAGE_EML_SECURITY_TOKEN:-}"
export SAGE_EML_ACCOUNT_NAME="${SAGE_EML_ACCOUNT_NAME:-sage@mail.example.com}"
export SAGE_EML_TEMPLATE_ID="${SAGE_EML_TEMPLATE_ID:-}"
export SAGE_EML_REGISTER_SUBJECT="${SAGE_EML_REGISTER_SUBJECT:-Sage security verification}"
export SAGE_EML_ADDRESS_TYPE="${SAGE_EML_ADDRESS_TYPE:-1}"
export SAGE_EML_REPLY_TO_ADDRESS="${SAGE_EML_REPLY_TO_ADDRESS:-false}"
export SAGE_DEFAULT_LLM_API_KEY="${SAGE_DEFAULT_LLM_API_KEY:-}"
export SAGE_DEFAULT_LLM_API_BASE_URL="${SAGE_DEFAULT_LLM_API_BASE_URL:-https://dashscope.aliyuncs.com/compatible-mode/v1/}"
export SAGE_DEFAULT_LLM_MODEL_NAME="${SAGE_DEFAULT_LLM_MODEL_NAME:-deepseek-v3}"
export SAGE_DEFAULT_LLM_MAX_TOKENS="${SAGE_DEFAULT_LLM_MAX_TOKENS:-4096}"
export SAGE_DEFAULT_LLM_TEMPERATURE="${SAGE_DEFAULT_LLM_TEMPERATURE:-0.2}"
export SAGE_DEFAULT_LLM_MAX_MODEL_LEN="${SAGE_DEFAULT_LLM_MAX_MODEL_LEN:-52000}"
export SAGE_DB_TYPE="${SAGE_DB_TYPE:-mysql}"
export SAGE_MYSQL_HOST="${SAGE_MYSQL_HOST:-sage-mysql}"
export SAGE_MYSQL_PORT="${SAGE_MYSQL_PORT:-3306}"
export SAGE_MYSQL_DATABASE="${SAGE_MYSQL_DATABASE:-sage}"
export SAGE_MYSQL_USER="${SAGE_MYSQL_USER:-root}"
export SAGE_MYSQL_PASSWORD="${SAGE_MYSQL_PASSWORD:-change_this_mysql_password}"
export SAGE_ELASTICSEARCH_URL="${SAGE_ELASTICSEARCH_URL:-http://sage-es:9200}"
export SAGE_ELASTICSEARCH_PORT="${SAGE_ELASTICSEARCH_PORT:-9200}"
export SAGE_ELASTICSEARCH_USERNAME="${SAGE_ELASTICSEARCH_USERNAME:-elastic}"
export SAGE_ELASTICSEARCH_PASSWORD="${SAGE_ELASTICSEARCH_PASSWORD:-change_this_elasticsearch_password}"
export SAGE_S3_ENDPOINT="${SAGE_S3_ENDPOINT:-sage-rustfs:9000}"
export SAGE_S3_ACCESS_KEY="${SAGE_S3_ACCESS_KEY:-root}"
export SAGE_S3_SECRET_KEY="${SAGE_S3_SECRET_KEY:-change_this_s3_secret}"
export SAGE_S3_SECURE="${SAGE_S3_SECURE:-false}"
export SAGE_S3_BUCKET_NAME="${SAGE_S3_BUCKET_NAME:-sage}"
export SAGE_S3_PUBLIC_BASE_URL="${SAGE_S3_PUBLIC_BASE_URL:-${SAGE_PUBLIC_URL}/sage}"
export SAGE_EMBEDDING_API_KEY="${SAGE_EMBEDDING_API_KEY:-}"
export SAGE_EMBEDDING_BASE_URL="${SAGE_EMBEDDING_BASE_URL:-https://dashscope.aliyuncs.com/compatible-mode/v1/}"
export SAGE_EMBEDDING_MODEL="${SAGE_EMBEDDING_MODEL:-text-embedding-v4}"
export SAGE_EMBEDDING_DIMS="${SAGE_EMBEDDING_DIMS:-1024}"

image_name() {
  local name="$1"
  if [ -n "$IMAGE_REGISTRY" ]; then
    printf '%s/%s:%s' "${IMAGE_REGISTRY%/}" "$name" "$IMAGE_TAG"
  else
    printf '%s:%s' "$name" "$IMAGE_TAG"
  fi
}

export SAGE_SERVER_IMAGE="${SAGE_SERVER_IMAGE:-$(image_name sage-server)}"
export SAGE_WEB_IMAGE="${SAGE_WEB_IMAGE:-$(image_name sage-web)}"
export SAGE_WIKI_IMAGE="${SAGE_WIKI_IMAGE:-$(image_name sage-wiki)}"
export SAGE_ES_IMAGE="${SAGE_ES_IMAGE:-$(image_name sage-es)}"

if [ -n "$STORAGE_CLASS" ]; then
  export PVC_STORAGE_CLASS="storageClassName: $STORAGE_CLASS"
else
  export PVC_STORAGE_CLASS=""
fi

if [ -n "$INGRESS_CLASS_NAME" ]; then
  export INGRESS_CLASS_LINE="ingressClassName: $INGRESS_CLASS_NAME"
else
  export INGRESS_CLASS_LINE=""
fi

if [ -n "$TLS_SECRET_NAME" ]; then
  export TLS_BLOCK="tls:
  - hosts:
      - $SAGE_HOST
    secretName: $TLS_SECRET_NAME"
else
  export TLS_BLOCK=""
fi

RENDERED_DIR="$(mktemp -d "${TMPDIR:-/tmp}/sage-k8s.XXXXXX")"
trap 'rm -rf "$RENDERED_DIR"' EXIT

python3 - "$K8S_DIR" "$RENDERED_DIR" <<'PY'
import os
import pathlib
import shutil
import string
import sys

src = pathlib.Path(sys.argv[1])
dst = pathlib.Path(sys.argv[2])
skip_dirs = {".git"}

for path in src.rglob("*"):
    if any(part in skip_dirs for part in path.parts):
        continue
    rel = path.relative_to(src)
    out = dst / rel
    if path.is_dir():
        out.mkdir(parents=True, exist_ok=True)
        continue
    if path.suffix in {".yaml", ".yml"}:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(string.Template(path.read_text()).safe_substitute(os.environ), encoding="utf-8")
    else:
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, out)
PY

if [ "$NAMESPACE" = "sage" ]; then
  kubectl apply -f "$RENDERED_DIR/namespace.yaml"
else
  kubectl create namespace "$NAMESPACE" --dry-run=client -o yaml | kubectl apply -f -
fi

kubectl -n "$NAMESPACE" apply -f "$RENDERED_DIR/configmaps"
kubectl -n "$NAMESPACE" apply -f "$RENDERED_DIR/secrets"
kubectl -n "$NAMESPACE" apply -f "$RENDERED_DIR/services"
kubectl -n "$NAMESPACE" apply -f "$RENDERED_DIR/workloads"
kubectl -n "$NAMESPACE" apply -f "$RENDERED_DIR/ingress"

kubectl -n "$NAMESPACE" rollout status statefulset/sage-mysql --timeout=10m

for deployment in sage-es sage-rustfs sage-jaeger sage-server sage-web sage-wiki; do
  kubectl -n "$NAMESPACE" rollout status "deployment/$deployment" --timeout=10m
done

kubectl -n "$NAMESPACE" get pods,svc,ingress
