#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
APP_DIR="$ROOT_DIR/app/desktop"
UI_DIR="$APP_DIR/ui"
TAURI_DIR="$APP_DIR/tauri"
TAURI_SIDECAR_DIR="$TAURI_DIR/sidecar"
CACHE_DIR="$APP_DIR/.build_cache"
BUILD_REQ_FILE="$APP_DIR/scripts/github/requirements-build.txt"

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
    if command -v python >/dev/null 2>&1; then
        echo "python -m pip"
    elif command -v python3 >/dev/null 2>&1; then
        echo "python3 -m pip"
    else
        echo ""
    fi
}

echo "Preparing desktop dependencies for $OS_TYPE/$ARCH..."

echo "$(calc_hash "$ROOT_DIR/requirements.txt")" > "$CACHE_DIR/.requirements.hash"

PIP_CMD="$(get_pip_cmd)"
WHEELHOUSE_DIR="$CACHE_DIR/wheelhouse"
if [ -n "$PIP_CMD" ]; then
    PIP_INDEX_URL="${PIP_INDEX_URL:-https://pypi.org/simple}"
    if [ -d "$WHEELHOUSE_DIR" ] && [ -n "$(find "$WHEELHOUSE_DIR" -type f -print -quit 2>/dev/null || true)" ]; then
        echo "Reusing cached Python wheelhouse at $WHEELHOUSE_DIR..."
    else
        echo "Preparing Python wheelhouse at $WHEELHOUSE_DIR..."
        rm -rf "$WHEELHOUSE_DIR"
        mkdir -p "$WHEELHOUSE_DIR"

        # 先在 prepare 环境里安装一套现代构建工具链，避免 pip 解析 pyproject metadata 时走到 runner 自带的旧依赖。
        eval "$PIP_CMD install --upgrade -r \"$BUILD_REQ_FILE\" --index-url \"$PIP_INDEX_URL\""

        # 再把这套构建工具链本身也下载进 wheelhouse，供 build 阶段离线安装和无隔离构建使用。
        eval "$PIP_CMD download --dest \"$WHEELHOUSE_DIR\" -r \"$BUILD_REQ_FILE\" --index-url \"$PIP_INDEX_URL\""

        # 用受控的现代打包工具链准备 wheelhouse，避免系统 Python 自带 pip 的老旧元数据构建逻辑。
        eval "$PIP_CMD download --dest \"$WHEELHOUSE_DIR\" -r \"$ROOT_DIR/requirements.txt\" --index-url \"$PIP_INDEX_URL\""

        # Build 阶段会强制 no-binary 重新安装这两个包，需要提前缓存源码包。
        eval "$PIP_CMD download --dest \"$WHEELHOUSE_DIR\" --no-binary=chardet,charset-normalizer chardet charset-normalizer --index-url \"$PIP_INDEX_URL\""
    fi
else
    echo "Python is not available in prepare job."
    exit 1
fi

cd "$UI_DIR"
npm install --prefer-offline --no-audit --no-fund
echo "$(calc_hash "$UI_DIR/package-lock.json")" > "$CACHE_DIR/.package-lock.hash"

NODE_CACHE_DIR="$CACHE_DIR/node-runtime/${OS_TYPE}-${ARCH}"
if [ -d "$NODE_CACHE_DIR" ] && [ -n "$(find "$NODE_CACHE_DIR" -type f -print -quit 2>/dev/null || true)" ]; then
    echo "Reusing cached bundled Node runtime at $NODE_CACHE_DIR..."
else
    echo "Preparing bundled Node runtime cache..."
    chmod +x "$APP_DIR/scripts/setup-node-runtime.sh"
    "$APP_DIR/scripts/setup-node-runtime.sh"

    NODE_DIR="$TAURI_SIDECAR_DIR/node"
    rm -rf "$NODE_CACHE_DIR"
    mkdir -p "$NODE_CACHE_DIR"
    cp -a "$NODE_DIR/." "$NODE_CACHE_DIR/"
fi

cd "$ROOT_DIR"

echo "Dependency preparation completed."
