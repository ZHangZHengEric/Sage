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

get_pip_cmd() {
    if command -v python3 >/dev/null 2>&1; then
        echo "python3 -m pip"
    elif command -v python >/dev/null 2>&1; then
        echo "python -m pip"
    else
        echo ""
    fi
}

echo "Preparing desktop dependencies for $OS_TYPE/$ARCH..."

echo "$(calc_hash "$ROOT_DIR/requirements.txt")" > "$CACHE_DIR/.requirements.hash"

PIP_CMD="$(get_pip_cmd)"
if [ -n "$PIP_CMD" ]; then
    PIP_INDEX_URL="${PIP_INDEX_URL:-https://pypi.org/simple}"
    WHEELHOUSE_DIR="$CACHE_DIR/wheelhouse"
    echo "Preparing Python wheelhouse at $WHEELHOUSE_DIR..."
    rm -rf "$WHEELHOUSE_DIR"
    mkdir -p "$WHEELHOUSE_DIR"

    # 预下载 requirements 对应分发包，供 build 阶段离线优先安装。
    eval "$PIP_CMD download --dest \"$WHEELHOUSE_DIR\" -r \"$ROOT_DIR/requirements.txt\" --index-url \"$PIP_INDEX_URL\""

    # Build 阶段会强制 no-binary 重新安装这两个包，需要提前缓存源码包。
    eval "$PIP_CMD download --dest \"$WHEELHOUSE_DIR\" --no-binary=chardet,charset-normalizer chardet charset-normalizer --index-url \"$PIP_INDEX_URL\""
else
    echo "Python is not available in prepare job, skip wheelhouse preparation."
fi

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
