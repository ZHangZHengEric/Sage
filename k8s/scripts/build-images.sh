#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
K8S_DIR="$ROOT_DIR/k8s"

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

load_env_file "$K8S_DIR/.env"

IMAGE_TAG="${IMAGE_TAG:-v1.0}"
IMAGE_REGISTRY="${IMAGE_REGISTRY:-}"
SAGE_PUBLIC_URL="${SAGE_PUBLIC_URL:-http://${SAGE_HOST:-sage.example.com}}"
SAGE_WEB_BASE_PATH="${SAGE_WEB_BASE_PATH:-/sage}"
SAGE_TRACE_WEB_URL="${SAGE_TRACE_WEB_URL:-${SAGE_PUBLIC_URL}/jaeger/}"
PUSH_IMAGES="${PUSH_IMAGES:-false}"
SAGE_WEB_BUILD_BASE="${SAGE_WEB_BASE_PATH%/}/"

image_name() {
  local name="$1"
  if [ -n "$IMAGE_REGISTRY" ]; then
    printf '%s/%s:%s' "${IMAGE_REGISTRY%/}" "$name" "$IMAGE_TAG"
  else
    printf '%s:%s' "$name" "$IMAGE_TAG"
  fi
}

SAGE_SERVER_IMAGE="$(image_name sage-server)"
SAGE_WEB_IMAGE="$(image_name sage-web)"
SAGE_WIKI_IMAGE="$(image_name sage-wiki)"
SAGE_ES_IMAGE="$(image_name sage-es)"

cd "$ROOT_DIR"

docker build -f docker/Dockerfile.server -t "$SAGE_SERVER_IMAGE" .
docker build \
  -f docker/Dockerfile.web \
  --build-arg "VITE_SAGE_API_BASE_URL=$SAGE_PUBLIC_URL" \
  --build-arg "VITE_SAGE_TRACE_WEB_URL=$SAGE_TRACE_WEB_URL" \
  --build-arg "VITE_SAGE_WEB_BASE_PATH=$SAGE_WEB_BUILD_BASE" \
  -t "$SAGE_WEB_IMAGE" .
docker build \
  -f docker/Dockerfile.wiki \
  --build-arg "VITE_SAGE_API_BASE_URL=$SAGE_PUBLIC_URL" \
  -t "$SAGE_WIKI_IMAGE" .
docker build -f docker/Dockerfile.es -t "$SAGE_ES_IMAGE" .

if [ "$PUSH_IMAGES" = "true" ]; then
  docker push "$SAGE_SERVER_IMAGE"
  docker push "$SAGE_WEB_IMAGE"
  docker push "$SAGE_WIKI_IMAGE"
  docker push "$SAGE_ES_IMAGE"
fi

printf 'Built images:\n'
printf '  %s\n' "$SAGE_SERVER_IMAGE" "$SAGE_WEB_IMAGE" "$SAGE_WIKI_IMAGE" "$SAGE_ES_IMAGE"
