#!/bin/bash

# 设置 Node.js 运行时用于打包
# 下载完整的 Node.js 发行版（包含 npm）到 sidecar 目录

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TAURI_DIR="$SCRIPT_DIR/../tauri"
SIDECAR_DIR="$TAURI_DIR/sidecar"
NODE_DIR="$SIDECAR_DIR/node"

# Node.js 版本 - 需要 20.19+ 或 22.12+ 以支持 Vite 等现代工具
NODE_VERSION="v22.14.0"

# 检测平台和架构
OS="$(uname -s)"
ARCH="$(uname -m)"

# 根据平台和架构设置下载 URL
 case "$OS" in
    Linux*)
        PLATFORM="linux"
        case "$ARCH" in
            x86_64) NODE_ARCH="x64" ;;
            aarch64|arm64) NODE_ARCH="arm64" ;;
            *) echo "Unsupported architecture: $ARCH"; exit 1 ;;
        esac
        ;;
    Darwin*)
        PLATFORM="darwin"
        case "$ARCH" in
            x86_64) NODE_ARCH="x64" ;;
            arm64) NODE_ARCH="arm64" ;;
            *) echo "Unsupported architecture: $ARCH"; exit 1 ;;
        esac
        ;;
    MINGW*|CYGWIN*|MSYS*)
        PLATFORM="win"
        case "$ARCH" in
            x86_64) NODE_ARCH="x64" ;;
            *) echo "Unsupported architecture: $ARCH"; exit 1 ;;
        esac
        ;;
    *)
        echo "Unsupported platform: $OS"
        exit 1
        ;;
esac

# 构建下载 URL 和解压目录名
NODE_DIST_NAME="node-${NODE_VERSION}-${PLATFORM}-${NODE_ARCH}"
if [ "$PLATFORM" = "win" ]; then
    NODE_DOWNLOAD_URL="https://nodejs.org/dist/${NODE_VERSION}/${NODE_DIST_NAME}.zip"
else
    NODE_DOWNLOAD_URL="https://nodejs.org/dist/${NODE_VERSION}/${NODE_DIST_NAME}.tar.gz"
fi

echo "Setting up Node.js runtime..."
echo "Node version: $NODE_VERSION"
echo "Platform: $PLATFORM"
echo "Architecture: $NODE_ARCH"
echo "Download URL: $NODE_DOWNLOAD_URL"

# 创建目录
mkdir -p "$NODE_DIR"

# 下载并解压 Node.js
# 注意：必须完全删除旧目录再复制，避免旧版本文件残留导致模块冲突
NODE_VERSION_FILE="$NODE_DIR/.node-version"
NEED_DOWNLOAD=false

if [ ! -f "$NODE_DIR/bin/node" ] && [ ! -f "$NODE_DIR/node.exe" ]; then
    NEED_DOWNLOAD=true
    echo "Node.js not found, need to download."
elif [ -f "$NODE_VERSION_FILE" ]; then
    INSTALLED_VERSION=$(cat "$NODE_VERSION_FILE")
    if [ "$INSTALLED_VERSION" != "$NODE_VERSION" ]; then
        NEED_DOWNLOAD=true
        echo "Node.js version mismatch (installed: $INSTALLED_VERSION, required: $NODE_VERSION), need to re-download."
    fi
else
    NEED_DOWNLOAD=true
    echo "Node.js version file not found, need to re-download."
fi

if [ "$NEED_DOWNLOAD" = true ]; then
    echo "Downloading Node.js ${NODE_VERSION}..."
    
    # 完全删除旧目录，避免文件残留导致模块冲突
    if [ -d "$NODE_DIR" ]; then
        echo "Removing old Node.js directory..."
        rm -rf "$NODE_DIR"
    fi
    mkdir -p "$NODE_DIR"
    
    TEMP_DIR=$(mktemp -d)
    
    if [ "$PLATFORM" = "win" ]; then
        # Windows: 下载 zip 并使用 unzip
        curl -L -o "$TEMP_DIR/node.zip" "$NODE_DOWNLOAD_URL"
        unzip -q "$TEMP_DIR/node.zip" -d "$TEMP_DIR"
        # Windows 版本直接复制到 NODE_DIR
        cp -R "$TEMP_DIR/${NODE_DIST_NAME}/"* "$NODE_DIR/"
    else
        # macOS/Linux: 下载 tar.gz 并使用 tar
        curl -L -o "$TEMP_DIR/node.tar.gz" "$NODE_DOWNLOAD_URL"
        tar -xzf "$TEMP_DIR/node.tar.gz" -C "$TEMP_DIR"
        # 复制下载的 Node.js 到 sidecar 目录
        cp -R "$TEMP_DIR/${NODE_DIST_NAME}/"* "$NODE_DIR/"
    fi
    
    # 记录版本号
    echo "$NODE_VERSION" > "$NODE_VERSION_FILE"
    
    rm -rf "$TEMP_DIR"
    echo "Node.js downloaded successfully"
else
    echo "Node.js ${NODE_VERSION} already exists, skipping download"
fi

# 创建 npm 和 npx 包装脚本（使用相对路径，这样目录被复制后也能正常工作）
if [ -f "$NODE_DIR/bin/node" ]; then
    echo "Creating npm wrapper scripts..."
    
    NPM_CLI_DST="$NODE_DIR/bin/npm"
    NPX_CLI_DST="$NODE_DIR/bin/npx"
    
    # 删除原来的 npm/npx（如果是符号链接或文件）
    rm -f "$NPM_CLI_DST" "$NPX_CLI_DST"
    
    # 创建包装脚本 - 使用相对路径
    cat > "$NPM_CLI_DST" << 'EOF'
#!/bin/sh
# 获取脚本所在目录
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
exec "$SCRIPT_DIR/node" "$SCRIPT_DIR/../lib/node_modules/npm/bin/npm-cli.js" "$@"
EOF
    
    cat > "$NPX_CLI_DST" << 'EOF'
#!/bin/sh
# 获取脚本所在目录
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
exec "$SCRIPT_DIR/node" "$SCRIPT_DIR/../lib/node_modules/npm/bin/npx-cli.js" "$@"
EOF
    
    chmod +x "$NPM_CLI_DST" "$NPX_CLI_DST"
    echo "NPM wrapper scripts created (using relative paths)"
fi

echo "Node.js runtime setup complete!"
echo "Location: $NODE_DIR"
echo "Node version:"
"$NODE_DIR/bin/node" --version
echo "NPM version:"
"$NODE_DIR/bin/npm" --version 2>/dev/null || echo "NPM version: (failed to get version)"
