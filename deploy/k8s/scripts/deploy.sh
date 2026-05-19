#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
DEPLOY_DIR="$ROOT_DIR/deploy"
K8S_DIR="$DEPLOY_DIR/k8s"
DEPLOY_ENV="${DEPLOY_ENV:-prod}"
ENV_DIR="$DEPLOY_DIR/$DEPLOY_ENV"
ENV_FILE="${ENV_FILE:-$ENV_DIR/.env}"

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
IMAGE_PULL_POLICY="${IMAGE_PULL_POLICY:-}"
K8S_IMAGE_TARGET="${K8S_IMAGE_TARGET:-ctr}"
CTR_NAMESPACE="${CTR_NAMESPACE:-k8s.io}"
CTR_BIN="${CTR_BIN:-ctr}"
RECREATE="${RECREATE:-false}"
DELETE_PVCS="${DELETE_PVCS:-false}"
SKIP_IMAGE_PREPARE="${SKIP_IMAGE_PREPARE:-false}"
STORAGE_CLASS="${STORAGE_CLASS:-}"
INGRESS_CLASS_NAME="${INGRESS_CLASS_NAME:-nginx}"
TLS_SECRET_NAME="${TLS_SECRET_NAME:-}"
ENABLE_INGRESS="${ENABLE_INGRESS:-false}"
SAGE_WEB_SERVICE_TYPE="${SAGE_WEB_SERVICE_TYPE:-NodePort}"
SAGE_WIKI_SERVICE_TYPE="${SAGE_WIKI_SERVICE_TYPE:-NodePort}"
SAGE_WEB_NODE_PORT="${SAGE_WEB_NODE_PORT:-30080}"
SAGE_WIKI_NODE_PORT="${SAGE_WIKI_NODE_PORT:-30081}"
SELECTED_SERVICE_KEYS=()

usage() {
  cat <<'EOF'
Usage: deploy/k8s/scripts/deploy.sh [SERVICE...]

Deploy Sage Kubernetes resources.

Environment:
  DEPLOY_ENV=dev|prod|test Select deploy/<env>/.env (default: prod)
  ENV_FILE=path           Override the env file path

Services:
  all                   Deploy all Sage services (default)
  server, sage-server   Deploy only sage-server resources
  web, sage-web         Deploy only sage-web resources
  wiki, sage-wiki       Deploy only sage-wiki resources
  mysql, sage-mysql     Deploy only sage-mysql resources
  rustfs, sage-rustfs   Deploy only sage-rustfs resources
  jaeger, sage-jaeger   Deploy only sage-jaeger resources

Options:
  -s, --service SERVICE Add one service to deploy
  -r, --recreate        Delete selected resources before deploying them again
      --redeploy        Alias for --recreate
      --skip-images     Skip image build/pull/import preparation
  -h, --help            Show this help
EOF
}

add_service_key() {
  local service="$1"
  local key existing

  case "$service" in
    all)
      SELECTED_SERVICE_KEYS=(mysql rustfs jaeger server web wiki)
      return 0
      ;;
    server|sage-server)
      key="server"
      ;;
    web|sage-web)
      key="web"
      ;;
    wiki|sage-wiki)
      key="wiki"
      ;;
    mysql|sage-mysql)
      key="mysql"
      ;;
    rustfs|sage-rustfs)
      key="rustfs"
      ;;
    jaeger|sage-jaeger)
      key="jaeger"
      ;;
    *)
      echo "Unsupported service '$service'. Expected one of: all, server, web, wiki, mysql, rustfs, jaeger, sage-server, sage-web, sage-wiki, sage-mysql, sage-rustfs, sage-jaeger." >&2
      exit 1
      ;;
  esac

  if [ "${#SELECTED_SERVICE_KEYS[@]}" -gt 0 ]; then
    for existing in "${SELECTED_SERVICE_KEYS[@]}"; do
      [ "$existing" = "$key" ] && return 0
    done
  fi
  SELECTED_SERVICE_KEYS+=("$key")
}

parse_args() {
  local arg

  if [ "$#" -eq 0 ]; then
    add_service_key all
    return 0
  fi

  while [ "$#" -gt 0 ]; do
    arg="$1"
    case "$arg" in
      -h|--help)
        usage
        exit 0
        ;;
      -s|--service)
        shift
        if [ "$#" -eq 0 ]; then
          echo "$arg requires a service name." >&2
          exit 1
        fi
        add_service_key "$1"
        ;;
      --service=*)
        add_service_key "${arg#*=}"
        ;;
      -r|--recreate|--redeploy)
        RECREATE="true"
        ;;
      --skip-images)
        SKIP_IMAGE_PREPARE="true"
        ;;
      --)
        shift
        while [ "$#" -gt 0 ]; do
          add_service_key "$1"
          shift
        done
        return 0
        ;;
      -*)
        echo "Unknown option '$arg'." >&2
        usage >&2
        exit 1
        ;;
      *)
        add_service_key "$arg"
        ;;
    esac
    shift
  done
}

selected_has() {
  local wanted="$1"
  local existing

  if [ "${#SELECTED_SERVICE_KEYS[@]}" -gt 0 ]; then
    for existing in "${SELECTED_SERVICE_KEYS[@]}"; do
      [ "$existing" = "$wanted" ] && return 0
    done
  fi
  return 1
}

parse_args "$@"

if [ "${#SELECTED_SERVICE_KEYS[@]}" -eq 0 ]; then
  add_service_key all
fi

if selected_has web && [ ! -d "$ENV_DIR/nginx" ]; then
  echo "Environment nginx config directory not found: $ENV_DIR/nginx" >&2
  exit 1
fi

if [ -z "$SAGE_HOST" ] && [ -z "$SAGE_PUBLIC_URL" ] && selected_has server; then
  echo "SAGE_HOST or SAGE_PUBLIC_URL is required when deploying sage-server. Set it in $ENV_FILE or pass SAGE_HOST=example.com." >&2
  exit 1
fi

if [ -z "$SAGE_HOST" ] && [ "$ENABLE_INGRESS" = "true" ] && { selected_has web || selected_has wiki; }; then
  echo "SAGE_HOST is required when ENABLE_INGRESS=true and deploying sage-web or sage-wiki." >&2
  exit 1
fi

is_ip_address() {
  [[ "$1" =~ ^[0-9]+(\.[0-9]+){3}$ ]] || [[ "$1" == *:* ]]
}

if [ -z "$SAGE_PUBLIC_URL" ]; then
  if [ -z "$SAGE_HOST" ]; then
    SAGE_PUBLIC_URL="http://sage.example.com"
  elif is_ip_address "$SAGE_HOST"; then
    if [ "$SAGE_WEB_SERVICE_TYPE" = "NodePort" ]; then
      SAGE_PUBLIC_URL="http://$SAGE_HOST:$SAGE_WEB_NODE_PORT"
    else
      SAGE_PUBLIC_URL="http://$SAGE_HOST"
    fi
  else
    SAGE_PUBLIC_URL="https://$SAGE_HOST"
  fi
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
export SAGE_ELASTICSEARCH_URL="${SAGE_ELASTICSEARCH_URL:-}"
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
    printf '%s/%s:latest' "${IMAGE_REGISTRY%/}" "$name"
  else
    printf '%s:latest' "$name"
  fi
}

canonical_image_name() {
  local image="$1"
  if [[ "$image" != */* ]]; then
    printf 'docker.io/library/%s' "$image"
  else
    printf '%s' "$image"
  fi
}

command_exists() {
  command -v "$1" >/dev/null 2>&1
}

normalize_image_target() {
  local target="$K8S_IMAGE_TARGET"

  if [ "$target" = "auto" ]; then
    target="ctr"
  fi

  case "$target" in
    containerd|cri|ctr)
      K8S_IMAGE_TARGET="$target"
      ;;
    *)
      echo "Unsupported K8S_IMAGE_TARGET '$target'. Kubernetes image deployment only supports ctr/containerd/cri." >&2
      exit 1
      ;;
  esac
}

containerd_image_exists() {
  local image="$1"
  local existing

  while IFS= read -r existing; do
    [ "$existing" = "$image" ] && return 0
  done < <(
    "$CTR_BIN" -n "$CTR_NAMESPACE" images ls -q 2>/dev/null || \
    "$CTR_BIN" -n "$CTR_NAMESPACE" images ls 2>/dev/null | awk 'NR > 1 {print $1}'
  )

  return 1
}

containerd_image_exists_any() {
  local image="$1"
  local canonical_image

  containerd_image_exists "$image" && return 0

  canonical_image="$(canonical_image_name "$image")"
  if [ "$canonical_image" != "$image" ]; then
    containerd_image_exists "$canonical_image" && return 0
  fi

  return 1
}

add_unique_image() {
  local image="$1"
  local existing

  if [ "${#SAGE_EXTERNAL_IMAGES[@]}" -gt 0 ]; then
    for existing in "${SAGE_EXTERNAL_IMAGES[@]}"; do
      [ "$existing" = "$image" ] && return 0
    done
  fi
  SAGE_EXTERNAL_IMAGES+=("$image")
}

export SAGE_SERVER_IMAGE="${SAGE_SERVER_IMAGE:-$(image_name sage-server)}"
export SAGE_WEB_IMAGE="${SAGE_WEB_IMAGE:-$(image_name sage-web)}"
export SAGE_WIKI_IMAGE="${SAGE_WIKI_IMAGE:-$(image_name sage-wiki)}"
export SAGE_MYSQL_IMAGE="${SAGE_MYSQL_IMAGE:-docker.m.daocloud.io/mysql:8.4}"
export SAGE_RUSTFS_IMAGE="${SAGE_RUSTFS_IMAGE:-docker.m.daocloud.io/rustfs/rustfs:latest}"
export SAGE_JAEGER_IMAGE="${SAGE_JAEGER_IMAGE:-docker.m.daocloud.io/jaegertracing/jaeger:2.16.0}"

select_images() {
  local service
  SAGE_IMAGES=()
  SAGE_CONTAINERD_IMAGES=()
  SAGE_EXTERNAL_IMAGES=()

  for service in "${SELECTED_SERVICE_KEYS[@]}"; do
    case "$service" in
      server)
        SAGE_IMAGES+=("$SAGE_SERVER_IMAGE")
        ;;
      web)
        SAGE_IMAGES+=("$SAGE_WEB_IMAGE")
        ;;
      wiki)
        SAGE_IMAGES+=("$SAGE_WIKI_IMAGE")
        ;;
      mysql)
        add_unique_image "$SAGE_MYSQL_IMAGE"
        ;;
      rustfs)
        add_unique_image "$SAGE_RUSTFS_IMAGE"
        ;;
      jaeger)
        add_unique_image "$SAGE_JAEGER_IMAGE"
        ;;
    esac
  done

  if [ "${#SAGE_IMAGES[@]}" -gt 0 ]; then
    SAGE_CONTAINERD_IMAGES=("${SAGE_IMAGES[@]}")
  fi
}

build_images() {
  local service

  for service in "${SELECTED_SERVICE_KEYS[@]}"; do
    case "$service" in
      server)
        docker build -f "$DEPLOY_DIR/images/Dockerfile.server" -t "$SAGE_SERVER_IMAGE" "$ROOT_DIR"
        ;;
      web)
        docker build \
          -f "$DEPLOY_DIR/images/Dockerfile.web-github" \
          --build-arg "NGINX_CONF=deploy/$DEPLOY_ENV/nginx/nginx.conf" \
          -t "$SAGE_WEB_IMAGE" \
          "$ROOT_DIR"
        ;;
      wiki)
        docker build \
          -f "$DEPLOY_DIR/images/Dockerfile.wiki-github" \
          --build-arg "NGINX_CONF=deploy/nginx/nginx_wiki.conf" \
          -t "$SAGE_WIKI_IMAGE" \
          "$ROOT_DIR"
        ;;
    esac
  done
}

import_built_images_to_containerd() {
  local archive image verify_images

  [ "${#SAGE_CONTAINERD_IMAGES[@]}" -gt 0 ] || return 0
  verify_images=("${SAGE_CONTAINERD_IMAGES[@]}")

  if [ -z "$IMAGE_REGISTRY" ]; then
    SAGE_CONTAINERD_IMAGES=()
    verify_images=()
    for image in "${SAGE_IMAGES[@]}"; do
      image="$(canonical_image_name "$image")"
      docker tag "${image#docker.io/library/}" "$image"
      SAGE_CONTAINERD_IMAGES+=("$image")
      verify_images+=("$image")
    done
  fi

  archive="$(mktemp "${TMPDIR:-/tmp}/sage-images.XXXXXX")"
  (
    trap 'rm -f "$archive"' EXIT
    docker save -o "$archive" "${SAGE_CONTAINERD_IMAGES[@]}"
    echo "Importing built Sage images into containerd namespace '$CTR_NAMESPACE' with $CTR_BIN."
    "$CTR_BIN" -n "$CTR_NAMESPACE" images import "$archive"
  )
  rm -f "$archive"

  for image in "${verify_images[@]}"; do
    if ! containerd_image_exists "$image"; then
      echo "Image '$image' was not found in containerd namespace '$CTR_NAMESPACE' after import." >&2
      echo "Check with: $CTR_BIN -n $CTR_NAMESPACE images ls | grep '$image'" >&2
      exit 1
    fi
  done
}

pull_external_images_to_containerd() {
  local image

  [ "${#SAGE_EXTERNAL_IMAGES[@]}" -gt 0 ] || return 0

  for image in "${SAGE_EXTERNAL_IMAGES[@]}"; do
    if containerd_image_exists_any "$image"; then
      echo "External image already exists in containerd: $image"
      continue
    fi
    echo "Pulling external image into containerd: $image"
    "$CTR_BIN" -n "$CTR_NAMESPACE" images pull "$image"
  done
}

prepare_images() {
  if [ "$SKIP_IMAGE_PREPARE" = "true" ]; then
    echo "Skipping image preparation because SKIP_IMAGE_PREPARE=true or --skip-images was set."
    return 0
  fi

  normalize_image_target
  select_images
  if [ "${#SAGE_IMAGES[@]}" -gt 0 ]; then
    command_exists docker || { echo "docker is required to build Sage images." >&2; exit 1; }
  fi
  if [ "${#SAGE_IMAGES[@]}" -gt 0 ] || [ "${#SAGE_EXTERNAL_IMAGES[@]}" -gt 0 ]; then
    command_exists "$CTR_BIN" || { echo "$CTR_BIN is required when K8S_IMAGE_TARGET=containerd/ctr." >&2; exit 1; }
  fi

  build_images
  import_built_images_to_containerd
  pull_external_images_to_containerd
}

if [ -z "$IMAGE_PULL_POLICY" ]; then
  if [ -n "$IMAGE_REGISTRY" ]; then
    IMAGE_PULL_POLICY="IfNotPresent"
  else
    IMAGE_PULL_POLICY="Never"
  fi
fi
export IMAGE_PULL_POLICY
export SAGE_WEB_SERVICE_TYPE
export SAGE_WIKI_SERVICE_TYPE

if [ "$SAGE_WEB_SERVICE_TYPE" = "NodePort" ]; then
  export SAGE_WEB_NODE_PORT_LINE="nodePort: $SAGE_WEB_NODE_PORT"
else
  export SAGE_WEB_NODE_PORT_LINE=""
fi

if [ "$SAGE_WIKI_SERVICE_TYPE" = "NodePort" ]; then
  export SAGE_WIKI_NODE_PORT_LINE="nodePort: $SAGE_WIKI_NODE_PORT"
else
  export SAGE_WIKI_NODE_PORT_LINE=""
fi

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

if is_ip_address "$SAGE_HOST"; then
  export INGRESS_HOST_LINE=""
  if [ -n "$TLS_SECRET_NAME" ]; then
    echo "SAGE_HOST is an IP address; skipping Ingress TLS host because Kubernetes Ingress hosts must be DNS names." >&2
  fi
  export TLS_BLOCK=""
else
  export INGRESS_HOST_LINE="host: $SAGE_HOST"
fi

if [ -n "$TLS_SECRET_NAME" ] && [ -n "$INGRESS_HOST_LINE" ]; then
  export TLS_BLOCK="tls:
  - hosts:
      - $SAGE_HOST
    secretName: $TLS_SECRET_NAME"
elif [ -z "${TLS_BLOCK:-}" ]; then
  export TLS_BLOCK=""
fi

ensure_namespace() {
  if [ "$NAMESPACE" = "sage" ]; then
    kubectl apply -f "$K8S_DIR/namespace.yaml"
  else
    kubectl create namespace "$NAMESPACE" --dry-run=client -o yaml | kubectl apply -f -
  fi
}

delete_selected_resources() {
  local service

  echo "Deleting selected resources before redeploy: ${SELECTED_SERVICE_KEYS[*]}"

  if selected_has web; then
    kubectl -n "$NAMESPACE" delete ingress sage --ignore-not-found
  fi
  if selected_has wiki; then
    kubectl -n "$NAMESPACE" delete ingress sage-wiki --ignore-not-found
  fi

  for service in "${SELECTED_SERVICE_KEYS[@]}"; do
    case "$service" in
      mysql)
        kubectl -n "$NAMESPACE" delete statefulset sage-mysql --ignore-not-found
        ;;
      *)
        kubectl -n "$NAMESPACE" delete deployment "sage-$service" --ignore-not-found
        ;;
    esac
  done

  for service in "${SELECTED_SERVICE_KEYS[@]}"; do
    kubectl -n "$NAMESPACE" delete service "sage-$service" --ignore-not-found
  done

  if selected_has server; then
    kubectl -n "$NAMESPACE" delete configmap sage-config --ignore-not-found
  fi
  if selected_has jaeger; then
    kubectl -n "$NAMESPACE" delete configmap sage-jaeger-config --ignore-not-found
  fi
  if selected_has server || selected_has mysql || selected_has rustfs; then
    kubectl -n "$NAMESPACE" delete secret sage-secrets --ignore-not-found
  fi

  if [ "$DELETE_PVCS" = "true" ]; then
    if selected_has server; then
      kubectl -n "$NAMESPACE" delete pvc \
        sage-server-sessions \
        sage-server-agents \
        sage-server-logs \
        sage-server-data \
        sage-server-skills \
        sage-server-users \
        --ignore-not-found
    fi
    if selected_has mysql; then
      kubectl -n "$NAMESPACE" delete pvc sage-mysql-data sage-mysql-conf --ignore-not-found
    fi
    if selected_has rustfs; then
      kubectl -n "$NAMESPACE" delete pvc sage-rustfs-data --ignore-not-found
    fi
  else
    echo "PVCs were preserved. Re-run with DELETE_PVCS=true to delete persistent data."
  fi
}

prepare_images

if [ "$RECREATE" = "true" ]; then
  ensure_namespace
  delete_selected_resources
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

ensure_namespace

echo "Deploying services: ${SELECTED_SERVICE_KEYS[*]}"

if selected_has server; then
  kubectl -n "$NAMESPACE" apply -f "$RENDERED_DIR/configmaps/sage-config.yaml"
fi

if selected_has jaeger; then
  kubectl -n "$NAMESPACE" apply -f "$RENDERED_DIR/configmaps/jaeger-config.yaml"
fi

if selected_has server || selected_has mysql || selected_has rustfs; then
  kubectl -n "$NAMESPACE" apply -f "$RENDERED_DIR/secrets/sage-secrets.yaml"
fi

for service in "${SELECTED_SERVICE_KEYS[@]}"; do
  kubectl -n "$NAMESPACE" apply -f "$RENDERED_DIR/services/sage-$service-service.yaml"
done

for service in "${SELECTED_SERVICE_KEYS[@]}"; do
  case "$service" in
    mysql)
      kubectl -n "$NAMESPACE" apply -f "$RENDERED_DIR/workloads/sage-mysql-statefulset.yaml"
      ;;
    *)
      kubectl -n "$NAMESPACE" apply -f "$RENDERED_DIR/workloads/sage-$service-deployment.yaml"
      ;;
  esac
done

if [ "$ENABLE_INGRESS" = "true" ]; then
  if selected_has web; then
    kubectl -n "$NAMESPACE" apply -f "$RENDERED_DIR/ingress/sage-ingress.yaml"
  fi
  if selected_has wiki; then
    kubectl -n "$NAMESPACE" apply -f "$RENDERED_DIR/ingress/sage-wiki-ingress.yaml"
  fi
elif selected_has web || selected_has wiki; then
  echo "Skipping Ingress because ENABLE_INGRESS=false. Use the sage-web/sage-wiki NodePort service instead."
fi

for service in "${SELECTED_SERVICE_KEYS[@]}"; do
  case "$service" in
    mysql)
      kubectl -n "$NAMESPACE" rollout status statefulset/sage-mysql --timeout=10m
      ;;
    *)
      kubectl -n "$NAMESPACE" rollout status "deployment/sage-$service" --timeout=10m
      ;;
  esac
done

kubectl -n "$NAMESPACE" get pods,svc
