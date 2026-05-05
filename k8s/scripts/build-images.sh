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
    if [ -z "${!key+x}" ]; then
      export "$key=$value"
    fi
  done < "$env_file"
}

load_env_file "$K8S_DIR/.env"

IMAGE_REGISTRY="${IMAGE_REGISTRY:-}"
SAGE_WEB_SERVICE_TYPE="${SAGE_WEB_SERVICE_TYPE:-NodePort}"
SAGE_WEB_NODE_PORT="${SAGE_WEB_NODE_PORT:-30080}"
if [ -z "${SAGE_PUBLIC_URL:-}" ]; then
  if [ "$SAGE_WEB_SERVICE_TYPE" = "NodePort" ] && [ -n "${SAGE_HOST:-}" ]; then
    SAGE_PUBLIC_URL="http://$SAGE_HOST:$SAGE_WEB_NODE_PORT"
  else
    SAGE_PUBLIC_URL="http://${SAGE_HOST:-sage.example.com}"
  fi
fi
SAGE_WEB_BASE_PATH="${SAGE_WEB_BASE_PATH:-/sage}"
SAGE_TRACE_WEB_URL="${SAGE_TRACE_WEB_URL:-${SAGE_PUBLIC_URL}/jaeger/}"
K8S_IMAGE_TARGET="${K8S_IMAGE_TARGET:-ctr}"
SAGE_WEB_BUILD_BASE="${SAGE_WEB_BASE_PATH%/}/"

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
      echo "Unsupported K8S_IMAGE_TARGET '$target'. Kubernetes image deployment only supports ctr/containerd/cri; registry push, Docker Desktop, kind, minikube, and k3d are intentionally disabled." >&2
      exit 1
      ;;
  esac
}

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

containerd_image_exists() {
  local ctr_bin="$1"
  local namespace="$2"
  local image="$3"

  "$ctr_bin" -n "$namespace" images get "$image" >/dev/null 2>&1
}

load_images_to_containerd() {
  local ctr_bin namespace archive image canonical_image
  ctr_bin="${CTR_BIN:-ctr}"
  namespace="${CTR_NAMESPACE:-k8s.io}"

  command_exists "$ctr_bin" || { echo "$ctr_bin is required when K8S_IMAGE_TARGET=containerd/ctr." >&2; exit 1; }

  if [ -z "$IMAGE_REGISTRY" ]; then
    SAGE_CONTAINERD_IMAGES=()
    for image in "${SAGE_IMAGES[@]}"; do
      canonical_image="$(canonical_image_name "$image")"
      docker tag "$image" "$canonical_image"
      SAGE_CONTAINERD_IMAGES+=("$image" "$canonical_image")
    done
  fi

  archive="$(mktemp "${TMPDIR:-/tmp}/sage-images.XXXXXX")"

  (
    trap 'rm -f "$archive"' EXIT
    docker save -o "$archive" "${SAGE_CONTAINERD_IMAGES[@]}"
    echo "Importing Sage images into containerd namespace '$namespace' with $ctr_bin."
    "$ctr_bin" -n "$namespace" images import "$archive"
  )
  rm -f "$archive"

  for image in "${SAGE_CONTAINERD_IMAGES[@]}"; do
    if ! containerd_image_exists "$ctr_bin" "$namespace" "$image"; then
      echo "Image '$image' was not found in containerd namespace '$namespace' after import." >&2
      echo "Check with: $ctr_bin -n $namespace images get '$image'" >&2
      exit 1
    fi
  done
}

publish_images() {
  local target="$K8S_IMAGE_TARGET"

  case "$target" in
    containerd|cri|ctr)
      load_images_to_containerd
      ;;
    *)
      echo "Unsupported K8S_IMAGE_TARGET '$target'. Kubernetes image deployment only supports ctr/containerd/cri; registry push, Docker Desktop, kind, minikube, and k3d are intentionally disabled." >&2
      exit 1
      ;;
  esac
}

cd "$ROOT_DIR"

normalize_image_target

SAGE_SERVER_IMAGE="$(image_name sage-server)"
SAGE_WEB_IMAGE="$(image_name sage-web)"
SAGE_WIKI_IMAGE="$(image_name sage-wiki)"
SAGE_IMAGES=("$SAGE_SERVER_IMAGE" "$SAGE_WEB_IMAGE" "$SAGE_WIKI_IMAGE")
SAGE_CONTAINERD_IMAGES=("${SAGE_IMAGES[@]}")

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

publish_images

printf 'Built Sage images:\n'
printf '  %s\n' "${SAGE_IMAGES[@]}"
