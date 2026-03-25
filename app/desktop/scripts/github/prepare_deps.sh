#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
APP_DIR="$ROOT_DIR/app/desktop"
UI_DIR="$APP_DIR/ui"
TAURI_DIR="$APP_DIR/tauri"
TAURI_SIDECAR_DIR="$TAURI_DIR/sidecar"
CACHE_DIR="$APP_DIR/.build_cache"

mkdir -p "$CACHE_DIR"

OS="$(uname -s)"
ARCH="$(uname -m)"

case "$OS" in
  Darwin)
    OS_TYPE="macos"
    ;;
  Linux)
    OS_TYPE="linux"
    ;;
  *)
    echo "Unsupported OS for prepare_deps.sh: $OS"
    exit 1
    ;;
esac

calc_hash() {
    if command -v shasum >/dev/null 2>&1; then
        shasum -a 256 "$1" | awk '{print $1}'
    elif command -v sha256sum >/dev/null 2>&1; then
        sha256sum "$1" | awk '{print $1}'
    else
        openssl dgst -sha256 "$1" | awk '{print $NF}'
    fi
}

echo "Preparing desktop dependencies for $OS_TYPE/$ARCH..."

echo "$(calc_hash "$ROOT_DIR/requirements.txt")" > "$CACHE_DIR/.requirements.hash"

cd "$UI_DIR"
npm install --prefer-offline --no-audit --no-fund
echo "$(calc_hash "$UI_DIR/package-lock.json")" > "$CACHE_DIR/.package-lock.hash"

echo "Preparing bundled Node runtime cache..."
chmod +x "$APP_DIR/scripts/setup-node-runtime.sh"
"$APP_DIR/scripts/setup-node-runtime.sh"

NODE_DIR="$TAURI_SIDECAR_DIR/node"
NODE_CACHE_DIR="$CACHE_DIR/node-runtime/${OS_TYPE}-${ARCH}"
rm -rf "$NODE_CACHE_DIR"
mkdir -p "$NODE_CACHE_DIR"
cp -a "$NODE_DIR/." "$NODE_CACHE_DIR/"

cd "$ROOT_DIR"

echo "Dependency preparation completed."
