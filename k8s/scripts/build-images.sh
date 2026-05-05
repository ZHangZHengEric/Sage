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
K8S_IMAGE_TARGET="${K8S_IMAGE_TARGET:-auto}"
PUSH_IMAGES="${PUSH_IMAGES:-auto}"
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
SAGE_IMAGES=("$SAGE_SERVER_IMAGE" "$SAGE_WEB_IMAGE" "$SAGE_WIKI_IMAGE" "$SAGE_ES_IMAGE")

command_exists() {
  command -v "$1" >/dev/null 2>&1
}

current_kubectl_context() {
  kubectl config current-context 2>/dev/null || true
}

load_images_to_kind() {
  local context cluster
  context="$(current_kubectl_context)"
  cluster="${KIND_CLUSTER_NAME:-${context#kind-}}"
  if [ -z "$cluster" ] || [ "$cluster" = "$context" ]; then
    cluster="${KIND_CLUSTER_NAME:-kind}"
  fi
  kind load docker-image "${SAGE_IMAGES[@]}" --name "$cluster"
}

load_images_to_minikube() {
  local profile
  profile="${MINIKUBE_PROFILE:-$(current_kubectl_context)}"
  [ -n "$profile" ] || profile="minikube"
  minikube image load "${SAGE_IMAGES[@]}" --profile "$profile"
}

load_images_to_k3d() {
  local context cluster
  context="$(current_kubectl_context)"
  cluster="${K3D_CLUSTER_NAME:-${context#k3d-}}"
  if [ -z "$cluster" ] || [ "$cluster" = "$context" ]; then
    echo "K3D_CLUSTER_NAME is required when the current kubectl context is not k3d-<cluster>." >&2
    exit 1
  fi
  k3d image import "${SAGE_IMAGES[@]}" --cluster "$cluster"
}

publish_images() {
  local target="$K8S_IMAGE_TARGET"

  if [ "$target" = "auto" ]; then
    if [ -n "$IMAGE_REGISTRY" ]; then
      target="registry"
    else
      local context
      context="$(current_kubectl_context)"
      case "$context" in
        kind-*) target="kind" ;;
        minikube) target="minikube" ;;
        k3d-*) target="k3d" ;;
        docker-desktop) target="docker" ;;
        *)
          echo "Cannot auto-detect where to publish images for kubectl context '$context'." >&2
          echo "Set IMAGE_REGISTRY for a private registry, or set K8S_IMAGE_TARGET=kind|minikube|k3d|docker|none." >&2
          exit 1
          ;;
      esac
    fi
  fi

  case "$target" in
    registry)
      if [ -z "$IMAGE_REGISTRY" ]; then
        echo "IMAGE_REGISTRY is required when K8S_IMAGE_TARGET=registry." >&2
        exit 1
      fi
      docker push "$SAGE_SERVER_IMAGE"
      docker push "$SAGE_WEB_IMAGE"
      docker push "$SAGE_WIKI_IMAGE"
      docker push "$SAGE_ES_IMAGE"
      ;;
    kind)
      command_exists kind || { echo "kind is required when K8S_IMAGE_TARGET=kind." >&2; exit 1; }
      load_images_to_kind
      ;;
    minikube)
      command_exists minikube || { echo "minikube is required when K8S_IMAGE_TARGET=minikube." >&2; exit 1; }
      load_images_to_minikube
      ;;
    k3d)
      command_exists k3d || { echo "k3d is required when K8S_IMAGE_TARGET=k3d." >&2; exit 1; }
      load_images_to_k3d
      ;;
    docker)
      echo "Using Docker Desktop Kubernetes; locally built Docker images are available to the cluster."
      ;;
    none)
      echo "Skipping image publish/load because K8S_IMAGE_TARGET=none."
      ;;
    *)
      echo "Unsupported K8S_IMAGE_TARGET '$target'. Use auto, registry, kind, minikube, k3d, docker, or none." >&2
      exit 1
      ;;
  esac
}

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

if [ "$PUSH_IMAGES" != "false" ]; then
  publish_images
fi

printf 'Built images:\n'
printf '  %s\n' "${SAGE_IMAGES[@]}"
