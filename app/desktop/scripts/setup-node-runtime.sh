#!/bin/bash

# 下载 Node.js 运行时用于打包
# 这个脚本在 build 之前运行，将 Node.js 二进制文件放入 sidecar 目录

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TAURI_DIR="$SCRIPT_DIR/../tauri"
SIDECAR_DIR="$TAURI_DIR/sidecar"
NODE_DIR="$SIDECAR_DIR/node"

# Node.js 版本
NODE_VERSION="20.11.0"

# 检测平台
PLATFORM=$(uname -s)
ARCH=$(uname -m)

case "$PLATFORM" in
    Darwin)
        case "$ARCH" in
            x86_64)
                NODE_PLATFORM="darwin-x64"
                ;;
            arm64)
                NODE_PLATFORM="darwin-arm64"
                ;;
            *)
                echo "Unsupported architecture: $ARCH"
                exit 1
                ;;
        esac
        ;;
    Linux)
        case "$ARCH" in
            x86_64)
                NODE_PLATFORM="linux-x64"
                ;;
            aarch64)
                NODE_PLATFORM="linux-arm64"
                ;;
            *)
                echo "Unsupported architecture: $ARCH"
                exit 1
                ;;
        esac
        ;;
    MINGW*|MSYS*|CYGWIN*)
        NODE_PLATFORM="win-x64"
        ;;
    *)
        echo "Unsupported platform: $PLATFORM"
        exit 1
        ;;
esac

echo "Setting up Node.js runtime..."
echo "Version: $NODE_VERSION"
echo "Platform: $NODE_PLATFORM"

# 创建目录
mkdir -p "$NODE_DIR"

# 下载 URL
NODE_DIST="node-v${NODE_VERSION}-${NODE_PLATFORM}"
if [[ "$NODE_PLATFORM" == win-* ]]; then
    NODE_TARBALL="${NODE_DIST}.zip"
else
    NODE_TARBALL="${NODE_DIST}.tar.gz"
fi

NODE_URL="https://npmmirror.com/mirrors/node/v${NODE_VERSION}/${NODE_TARBALL}"

echo "Downloading from: $NODE_URL"

# 下载并解压
cd "$NODE_DIR"

# 设置环境变量避免创建 macOS 扩展属性
if [[ "$PLATFORM" == "Darwin" ]]; then
    export CURL_SSL_BACKEND="secure-transport"
fi

if command -v curl &> /dev/null; then
    curl -L -o "$NODE_TARBALL" "$NODE_URL"
elif command -v wget &> /dev/null; then
    wget -O "$NODE_TARBALL" "$NODE_URL"
else
    echo "Error: curl or wget is required"
    exit 1
fi

echo "Extracting..."
if [[ "$NODE_TARBALL" == *.zip ]]; then
    unzip -q "$NODE_TARBALL"
    mv "${NODE_DIST}"/* .
    rm -rf "${NODE_DIST}"
else
    tar -xzf "$NODE_TARBALL" --strip-components=1
fi

rm "$NODE_TARBALL"

# 添加执行权限
echo "Setting permissions..."
chmod -R +x "$NODE_DIR/bin/"

echo "Node.js runtime setup complete!"
echo "Location: $NODE_DIR"
echo "Node version:"
"$NODE_DIR/bin/node" --version
echo "NPM version:"
"$NODE_DIR/bin/npm" --version
