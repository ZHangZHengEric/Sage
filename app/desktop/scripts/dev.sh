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
SAGE_HOME_DIR="${HOME}/.sage"
SAGE_NODE_ENV_DIR="$SAGE_HOME_DIR/.sage_node_env"
SAGE_NODE_RUNTIME_DIR="$SAGE_NODE_ENV_DIR/runtime"

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
    case "$ARCH" in
      x86_64)
        TARGET="x86_64-unknown-linux-gnu"
        ;;
      aarch64|arm64)
        TARGET="aarch64-unknown-linux-gnu"
        ;;
      *)
        echo "不支持的 Linux 架构: $ARCH"
        exit 1
        ;;
    esac
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
# 0. Cleanup Stale Dev Processes
########################################

cleanup_stale_dev_processes() {
  if [ "${SKIP_DEV_CLEANUP:-0}" = "1" ]; then
    echo "已跳过残留进程清理 (SKIP_DEV_CLEANUP=1)"
    return
  fi

  echo "正在清理残留开发进程..."

  # 仅清理本项目相关命令，避免误杀其他工作区进程。
  local patterns=(
    "vite.*$ROOT_DIR/app/desktop"
    "cargo.*tauri.*$ROOT_DIR/app/desktop/tauri"
    "$ROOT_DIR/app/desktop/scripts/dev.sh"
  )

  if command -v pgrep >/dev/null 2>&1; then
    for pattern in "${patterns[@]}"; do
      if pgrep -f "$pattern" >/dev/null 2>&1; then
        pkill -f "$pattern" >/dev/null 2>&1 || true
      fi
    done
  fi

  # 兜底释放常见开发端口 (Vite 1420 / app 默认 8080)。
  if command -v lsof >/dev/null 2>&1; then
    for port in 1420 8080; do
      local pids
      pids="$(lsof -nP -iTCP:"$port" -sTCP:LISTEN -t 2>/dev/null || true)"
      if [ -n "$pids" ]; then
        echo "释放端口 $port: $pids"
        for pid in $pids; do
          kill "$pid" >/dev/null 2>&1 || true
        done
      fi
    done
  fi
}

cleanup_stale_dev_processes

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
# Ensure we get the python from the activated conda environment
export SAGE_PYTHON="$CONDA_PREFIX/bin/python"
if [ ! -f "$SAGE_PYTHON" ]; then
    # Fallback: try to find python in PATH
    export SAGE_PYTHON="$(which python)"
fi
echo "设置 SAGE_PYTHON: $SAGE_PYTHON"

# Verify python exists
if [ ! -f "$SAGE_PYTHON" ]; then
    echo "错误: 找不到 Python 解释器: $SAGE_PYTHON"
    exit 1
fi

if [[ "$CONDA_EXE" == *"anaconda3"* ]]; then
    conda install -n "$ENV_NAME" numba -y
fi
echo "正在安装依赖..."
pip install -r "$ROOT_DIR/requirements.txt" --index-url https://mirrors.aliyun.com/pypi/simple

if ! command -v pyinstaller >/dev/null; then
  pip install pyinstaller --index-url https://mirrors.aliyun.com/pypi/simple
fi

########################################
# 2. Setup Node.js Runtime
########################################

echo "正在设置 Node.js 运行时..."

mkdir -p "$TAURI_BIN_DIR"
mkdir -p "$TAURI_SIDECAR_DIR"

# 使用 setup-node-runtime.sh 下载 Node.js
NODE_DIR="$TAURI_SIDECAR_DIR/node"
SETUP_SCRIPT="$APP_DIR/scripts/setup-node-runtime.sh"

if [ -f "$NODE_DIR/bin/node" ]; then
    echo "[Node.js] Node.js 运行时已存在，跳过下载。"
elif [ -f "$SETUP_SCRIPT" ]; then
    echo "[Node.js] 执行 Node.js 下载脚本..."
    chmod +x "$SETUP_SCRIPT"
    "$SETUP_SCRIPT"
    if [ $? -ne 0 ]; then
        echo "[Node.js] 错误: Node.js 下载失败"
        exit 1
    fi
else
    echo "[Node.js] 错误: 未找到下载脚本 $SETUP_SCRIPT"
    exit 1
fi

# 同步到 ~/.sage 共享运行时，保持 dev / build 行为一致
mkdir -p "$SAGE_NODE_ENV_DIR"
SOURCE_NODE_VERSION_FILE="$NODE_DIR/.node-version"
TARGET_NODE_VERSION_FILE="$SAGE_NODE_RUNTIME_DIR/.node-version"

NEEDS_NODE_SYNC=0
if [ ! -x "$SAGE_NODE_RUNTIME_DIR/bin/node" ]; then
  NEEDS_NODE_SYNC=1
elif [ -f "$SOURCE_NODE_VERSION_FILE" ] && [ -f "$TARGET_NODE_VERSION_FILE" ]; then
  if ! cmp -s "$SOURCE_NODE_VERSION_FILE" "$TARGET_NODE_VERSION_FILE"; then
    NEEDS_NODE_SYNC=1
  fi
elif [ -f "$SOURCE_NODE_VERSION_FILE" ] || [ -f "$TARGET_NODE_VERSION_FILE" ]; then
  NEEDS_NODE_SYNC=1
fi

if [ "$NEEDS_NODE_SYNC" -eq 1 ]; then
  echo "[Node.js] 正在同步共享运行时到 $SAGE_NODE_RUNTIME_DIR"
  rm -rf "$SAGE_NODE_RUNTIME_DIR"
  mkdir -p "$(dirname "$SAGE_NODE_RUNTIME_DIR")"
  cp -R "$NODE_DIR" "$SAGE_NODE_RUNTIME_DIR"
fi

RUNTIME_NODE_DIR="$SAGE_NODE_RUNTIME_DIR"
if [ ! -x "$RUNTIME_NODE_DIR/bin/node" ]; then
  echo "[Node.js] 共享运行时不可用，回退到 sidecar 运行时"
  RUNTIME_NODE_DIR="$NODE_DIR"
fi

# 设置 PATH，优先使用 ~/.sage 共享 Node.js 运行时
export PATH="$RUNTIME_NODE_DIR/bin:$PATH"
export SAGE_BUNDLED_NODE_BIN="$RUNTIME_NODE_DIR/bin"
echo "[Node.js] PATH 已更新: $RUNTIME_NODE_DIR/bin"
echo "[Node.js] SAGE_BUNDLED_NODE_BIN: $SAGE_BUNDLED_NODE_BIN"

# Link resources for dev mode
echo "正在链接开发模式资源..."
rm -rf "$TAURI_SIDECAR_DIR/skills" "$TAURI_SIDECAR_DIR/mcp_servers" "$TAURI_SIDECAR_DIR/wiki"
ln -sf "$ROOT_DIR/app/skills" "$TAURI_SIDECAR_DIR/skills"
ln -sf "$ROOT_DIR/mcp_servers" "$TAURI_SIDECAR_DIR/mcp_servers"
ln -sf "$ROOT_DIR/app/wiki" "$TAURI_SIDECAR_DIR/wiki"

########################################
# 3. Build Python Sidecar (Wrapper Script)
########################################

echo "正在设置 Python Sidecar 包装器..."

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

########################################
# 5. Start Development Server
########################################

echo "======================================"
echo " 开发服务器运行中"
echo " 端口: 由应用动态分配 (默认 8080)"
echo "======================================"

TAURI_DEV_ARGS=()
if [ "$OS_TYPE" = "linux" ] && [ "$TARGET" = "aarch64-unknown-linux-gnu" ]; then
  echo "使用显式 Tauri target: $TARGET"
  TAURI_DEV_ARGS=(--target "$TARGET")
fi

if [ ${#TAURI_DEV_ARGS[@]} -gt 0 ]; then
  cargo tauri dev "${TAURI_DEV_ARGS[@]}"
else
  cargo tauri dev
fi
