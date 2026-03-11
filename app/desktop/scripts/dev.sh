#!/usr/bin/env bash
set -euo pipefail
# Add cargo to PATH
export PATH="$HOME/.cargo/bin:$PATH"

########################################
# Sage Desktop Dev Script
########################################

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
APP_DIR="$ROOT_DIR/app/desktop"
UI_DIR="$APP_DIR/ui"
TAURI_DIR="$APP_DIR/tauri"
DIST_DIR="$APP_DIR/dist"
TAURI_SIDECAR_DIR="$TAURI_DIR/sidecar"
TAURI_BIN_DIR="$TAURI_DIR/bin"

NO_PYTHON_BUILD=1
MODE="debug"

echo "======================================"
echo " Sage 桌面开发环境 ($MODE)"
echo " 根目录: $ROOT_DIR"
echo " 提示: 设置 NO_PYTHON_BUILD=1 跳过 Sidecar 构建 (默认: 1)"
echo "======================================"

########################################
# Detect OS & Target Triple
########################################

OS="$(uname -s)"
ARCH="$(uname -m)"

case "$OS" in
  Darwin)
    OS_TYPE="macos"
    if [ "$ARCH" = "arm64" ]; then
      TARGET="aarch64-apple-darwin"
    else
      TARGET="x86_64-apple-darwin"
    fi
    ;;
  Linux)
    OS_TYPE="linux"
    TARGET="x86_64-unknown-linux-gnu"
    ;;
  MINGW*|CYGWIN*)
    OS_TYPE="windows"
    TARGET="x86_64-pc-windows-msvc"
    ;;
  *)
    echo "不支持的操作系统: $OS"
    exit 1
    ;;
esac

echo "操作系统: $OS_TYPE"
echo "目标平台: $TARGET"

########################################
# 1. Python Environment Setup (Conda)
########################################

# Try to locate conda
CONDA_EXE=""
if command -v conda >/dev/null 2>&1; then
  CONDA_EXE=$(command -v conda)
elif [ -f "$HOME/miniconda3/bin/conda" ]; then
  CONDA_EXE="$HOME/miniconda3/bin/conda"
elif [ -f "$HOME/anaconda3/bin/conda" ]; then
  CONDA_EXE="$HOME/anaconda3/bin/conda"
elif [ -f "/opt/miniconda3/bin/conda" ]; then
  CONDA_EXE="/opt/miniconda3/bin/conda"
elif [ -f "/opt/anaconda3/bin/conda" ]; then
  CONDA_EXE="/opt/anaconda3/bin/conda"
fi

if [ -z "$CONDA_EXE" ]; then
  echo "错误: 未找到 Conda。请安装 Miniconda 或 Anaconda。"
  exit 1
fi

# Initialize conda for shell interaction
CONDA_BASE=$($CONDA_EXE info --base)
source "$CONDA_BASE/etc/profile.d/conda.sh"

ENV_NAME="sage-desktop-env"

# Check if environment exists (more robust check)
if conda env list | grep -E "^$ENV_NAME\s" > /dev/null 2>&1; then
  echo "Conda 环境 '$ENV_NAME' 已存在，跳过创建。"
elif [ -d "$CONDA_BASE/envs/$ENV_NAME" ]; then
  echo "Conda 环境 '$ENV_NAME' 目录已存在，跳过创建。"
else
  echo "正在创建 Conda 环境 '$ENV_NAME' (Python 3.11)..."
  conda create -n "$ENV_NAME" python=3.11 -y || {
    echo "警告: 创建环境失败，可能已存在，尝试继续..."
  }
fi

echo "正在激活 Conda 环境 '$ENV_NAME'..."
conda activate "$ENV_NAME"

# Export Python path for Tauri
# Use 'which python' to get the path from the active environment
export SAGE_PYTHON="$(which python)"
echo "设置 SAGE_PYTHON: $SAGE_PYTHON"

if [[ "$CONDA_EXE" == *"anaconda3"* ]]; then
    conda install -n "$ENV_NAME" numba -y
fi
echo "正在安装依赖..."
pip install -r "$APP_DIR/core/requirements.txt" --index-url https://mirrors.aliyun.com/pypi/simple

if ! command -v pyinstaller >/dev/null; then
  pip install pyinstaller --index-url https://mirrors.aliyun.com/pypi/simple
fi

########################################
# 2. Build Python Sidecar (Wrapper Script)
########################################

echo "正在设置 Python Sidecar 包装器..."

mkdir -p "$TAURI_BIN_DIR"
mkdir -p "$TAURI_SIDECAR_DIR"

# Link resources for dev mode
echo "正在链接开发模式资源..."
rm -rf "$TAURI_SIDECAR_DIR/skills" "$TAURI_SIDECAR_DIR/mcp_servers"
ln -sf "$ROOT_DIR/app/skills" "$TAURI_SIDECAR_DIR/skills"
ln -sf "$ROOT_DIR/mcp_servers" "$TAURI_SIDECAR_DIR/mcp_servers"

# Get current python executable path
PYTHON_EXEC=$(python -c "import sys; print(sys.executable)")

# Create wrapper script that acts as the sidecar executable
# This is used for dev mode to avoid rebuilding the binary
SIDECAR_WRAPPER="$TAURI_SIDECAR_DIR/sage-desktop"
if [ "$OS_TYPE" = "windows" ]; then
  SIDECAR_WRAPPER="$TAURI_SIDECAR_DIR/sage-desktop.exe"
fi

echo "正在生成 Sidecar 包装器: $SIDECAR_WRAPPER"

cat > "$SIDECAR_WRAPPER" <<EOF
#!/bin/bash
export PYTHONPATH="$ROOT_DIR:\$PYTHONPATH"
export AGENT_BROWSER_HEADED=1
# Ensure mcp_servers are accessible (dev mode relies on source path)
# The app expects mcp_servers relative to executable or in a known location
# In dev, we can just point to source
exec "$PYTHON_EXEC" "$APP_DIR/entry.py" "\$@"
EOF

chmod +x "$SIDECAR_WRAPPER"

# Also create a .keep file
touch "$TAURI_SIDECAR_DIR/.keep"

echo "Sidecar 包装器已创建。"

########################################
# 4. Frontend Setup
########################################

echo "正在设置前端依赖..."
cd "$UI_DIR"

if ! command -v npm >/dev/null; then
  echo "错误: 未找到 npm。请安装 Node.js。"
  exit 1
fi

echo "正在安装前端依赖..."
npm install

cd "$ROOT_DIR"

########################################
# 6. Build Tauri
########################################

cd "$TAURI_DIR"

if ! command -v cargo >/dev/null; then
  echo "未找到 Cargo。请先安装 Rust。"
  exit 1
fi

TAURI_CLI_VERSION="$(cargo tauri --version 2>/dev/null | awk '{print $2}' || true)"
if [ -z "$TAURI_CLI_VERSION" ] || [[ "$TAURI_CLI_VERSION" != 2.* ]]; then
  echo "正在安装 tauri-cli v2..."
  cargo install tauri-cli --version "^2"
fi

echo "======================================"
echo " 开发服务器运行中"
echo "======================================"

cargo tauri dev
