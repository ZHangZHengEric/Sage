#!/usr/bin/env bash
set -euo pipefail
# Add cargo to PATH
export PATH="$HOME/.cargo/bin:$PATH"

########################################
# Sage Desktop Industrial Build Script
########################################

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
APP_DIR="$ROOT_DIR/app/desktop"
UI_DIR="$APP_DIR/ui"
TAURI_DIR="$APP_DIR/tauri"
DIST_DIR="$APP_DIR/dist"
# Standardized Sidecar Directory
TAURI_SIDECAR_DIR="$TAURI_DIR/sidecar"
TAURI_NODE_RESOURCES_DIR="$TAURI_DIR/resources/node"
# Build Cache Directory
CACHE_DIR="$APP_DIR/.build_cache"

MODE="${1:-release}"  # release | debug

echo "======================================"
echo " Sage 桌面构建 ($MODE)"
echo " 根目录: $ROOT_DIR"
echo " 输出目录: $DIST_DIR"
echo " 缓存目录: $CACHE_DIR"
echo "======================================"

# Ensure cache directory exists
mkdir -p "$CACHE_DIR"

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
# Helper Functions
########################################

calc_hash() {
    python3 -c "import hashlib; print(hashlib.sha256(open('$1', 'rb').read()).hexdigest())" 2>/dev/null || echo "unknown"
}

prepare_bundled_node_runtime() {
    echo "[Node Runtime] 正在准备内置 Node 运行时..."

    if ! command -v node >/dev/null 2>&1; then
        echo "错误: 未找到 node，无法准备 resources/node。"
        exit 1
    fi

    local node_root="${SAGE_BUNDLED_NODE_SOURCE:-}"
    if [ -z "$node_root" ]; then
        node_root="$(node -p "require('path').dirname(require('path').dirname(process.execPath))")"
    fi

    if [ ! -d "$node_root" ]; then
        echo "错误: Node 运行时目录不存在: $node_root"
        exit 1
    fi

    mkdir -p "$TAURI_NODE_RESOURCES_DIR"
    find "$TAURI_NODE_RESOURCES_DIR" -mindepth 1 ! -name "README.md" ! -name ".gitignore" -exec rm -rf {} +

    local item
    local name
    shopt -s dotglob nullglob
    for item in "$node_root"/*; do
        name="$(basename "$item")"
        if [ "$name" = "README.md" ] || [ "$name" = ".gitignore" ]; then
            continue
        fi
        cp -R "$item" "$TAURI_NODE_RESOURCES_DIR/"
    done
    shopt -u dotglob nullglob

    if [ -f "$TAURI_NODE_RESOURCES_DIR/bin/node" ]; then
        chmod +x "$TAURI_NODE_RESOURCES_DIR/bin/node"
    fi
    if [ -f "$TAURI_NODE_RESOURCES_DIR/node" ]; then
        chmod +x "$TAURI_NODE_RESOURCES_DIR/node"
    fi

    echo "[Node Runtime] 来源目录: $node_root"
    echo "[Node Runtime] 已同步到: $TAURI_NODE_RESOURCES_DIR"
}

########################################
# 1. Python Environment Setup (Conda)
########################################

ENV_NAME="sage-desktop-env"

# Check if we are already in the target environment (e.g. in CI)
if [ "${CONDA_DEFAULT_ENV:-}" = "$ENV_NAME" ]; then
  echo "已在 Conda 环境 '$ENV_NAME' 中。跳过环境设置。"
else
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

  echo "使用 Conda: $CONDA_EXE"

  # Initialize conda for shell interaction
  CONDA_BASE=$($CONDA_EXE info --base)
  source "$CONDA_BASE/etc/profile.d/conda.sh"

  # Check if environment exists
  if conda info --envs | grep -q "$ENV_NAME"; then
    echo "Conda 环境 '$ENV_NAME' 已存在。"
  else
    echo "正在创建 Conda 环境 '$ENV_NAME' (Python 3.11)..."
    conda create -n "$ENV_NAME" python=3.11 -y
  fi

  echo "正在激活 Conda 环境 '$ENV_NAME'..."
  conda activate "$ENV_NAME"
fi

echo "Python 版本: $(python --version)"
echo "Pip 版本: $(pip --version)"

# 1.1 Install Python Dependencies
install_python_deps() {
    if [ "${SKIP_PIP_INSTALL:-false}" = "true" ]; then
      echo "根据请求跳过 pip 安装。"
      return
    fi

    local REQ_FILE="$ROOT_DIR/requirements.txt"
    local HASH_FILE="$CACHE_DIR/.requirements.hash"
    local NEW_HASH=$(calc_hash "$REQ_FILE")
    local OLD_HASH=""
    
    if [ -f "$HASH_FILE" ]; then
        OLD_HASH=$(cat "$HASH_FILE")
    fi

    # 简单检查环境是否完整 (检查是否能 import 关键包)
    local ENV_OK=false
    if pip list | grep -q "requests"; then
        ENV_OK=true
    fi

    if [ "$NEW_HASH" = "$OLD_HASH" ] && [ "$ENV_OK" = "true" ]; then
        echo "Python 依赖未变更且环境正常，跳过安装。"
    else
        echo "正在升级构建工具..."
        PIP_INDEX_URL="${PIP_INDEX_URL:-https://mirrors.aliyun.com/pypi/simple}"
        echo "使用 pip 索引 URL: $PIP_INDEX_URL"

        pip install --upgrade pip setuptools wheel --index-url "$PIP_INDEX_URL"

        # 解决 x86_64 下 llvmlite 编译报错问题：优先使用 conda 安装预编译包
        if [ "${CONDA_DEFAULT_ENV:-}" = "$ENV_NAME" ]; then
            echo "正在通过 Conda 预安装 llvmlite 和 numba (防止 x86 编译错误)..."
            conda install -y -c conda-forge llvmlite numba
        fi

        echo "正在安装依赖..."
        pip install -r "$REQ_FILE" --index-url "$PIP_INDEX_URL"
        
        # 强制重新安装 chardet 和 charset-normalizer 为纯 Python 版本 (no-binary)
        # 这样 PyInstaller 可以正确打包它们，避免 mypyc 编译模块的隐藏导入问题
        echo "正在强制安装纯 Python 版 chardet 和 charset-normalizer..."
        pip install --force-reinstall --no-binary=chardet,charset-normalizer chardet charset-normalizer --index-url "$PIP_INDEX_URL"

        if ! command -v pyinstaller >/dev/null; then
            pip install pyinstaller --index-url "$PIP_INDEX_URL"
        fi
        
        # 保存新的 hash
        echo "$NEW_HASH" > "$HASH_FILE"
    fi
}

install_python_deps

########################################
# Parallel Build Tasks
########################################

build_python_sidecar() {
    echo "[Sidecar] 正在构建 Python Sidecar..."
    
    # 增量构建优化：Debug 模式下不清理
    if [ "$MODE" = "release" ]; then
        rm -rf "$DIST_DIR"
    fi
    mkdir -p "$DIST_DIR"

    export PYINSTALLER_CONFIG_DIR="$ROOT_DIR/.pyinstaller"
    export PYTHONPATH="$ROOT_DIR:${PYTHONPATH:-}"
    cd "$APP_DIR"

    # Optimization: Exclude unnecessary modules to reduce size
    local PYI_FLAGS=(
      --noconfirm
      --onedir
      --log-level=WARN
      --name sage-desktop
      --hidden-import=aiosqlite
      --hidden-import=greenlet
      --hidden-import=sqlalchemy.dialects.sqlite.aiosqlite
      # Exclusions
      --exclude-module=tkinter
      --exclude-module=unittest
      --exclude-module=email.test
      --exclude-module=test
      --exclude-module=tests
      --exclude-module=distutils
      --exclude-module=setuptools
      --exclude-module=xmlrpc
      # Common large unused libs in standard envs
      --exclude-module=IPython
      --exclude-module=notebook
    )

    if [ "$MODE" = "release" ]; then
      PYI_FLAGS+=(--strip)
      PYI_FLAGS+=(--noupx)
      PYI_FLAGS+=(--clean) # 仅 release 清理缓存
    fi

    pyinstaller "${PYI_FLAGS[@]}" entry.py

    # Clean up pyinstaller output
    echo "[Sidecar] 正在清理分发文件..."
    find "$DIST_DIR" -name "__pycache__" -type d -exec rm -rf {} +
    find "$DIST_DIR" -name "*.pyc" -delete
    find "$DIST_DIR" -name ".DS_Store" -delete

    # Copy mcp_servers to distribution directory
    echo "[Sidecar] 正在复制 mcp_servers 到分发目录..."
    if [ -d "$DIST_DIR/sage-desktop/_internal" ]; then
      TARGET_MCP_DIR="$DIST_DIR/sage-desktop/_internal"
    else
      TARGET_MCP_DIR="$DIST_DIR/sage-desktop"
    fi

    cp -r "$ROOT_DIR/mcp_servers" "$TARGET_MCP_DIR/"

    # Clean up mcp_servers in dist
    find "$TARGET_MCP_DIR/mcp_servers" -name "__pycache__" -type d -exec rm -rf {} +
    find "$TARGET_MCP_DIR/mcp_servers" -name ".git" -type d -exec rm -rf {} +
    find "$TARGET_MCP_DIR/mcp_servers" -name ".DS_Store" -delete

    # Copy skills to distribution directory
    echo "[Sidecar] 正在复制 skills 到分发目录..."
    cp -r "$ROOT_DIR/app/skills" "$TARGET_MCP_DIR/"

    # Clean up skills in dist
    find "$TARGET_MCP_DIR/skills" -name "__pycache__" -type d -exec rm -rf {} +
    find "$TARGET_MCP_DIR/skills" -name ".git" -type d -exec rm -rf {} +
    find "$TARGET_MCP_DIR/skills" -name ".DS_Store" -delete

    cd "$ROOT_DIR"

    # Move Binary to Tauri
    echo "[Sidecar] 正在移动二进制文件到 Tauri Sidecar 目录..."

    # Clean up previous build
    rm -rf "$TAURI_SIDECAR_DIR"
    mkdir -p "$TAURI_SIDECAR_DIR"

    SRC_DIR="$DIST_DIR/sage-desktop"

    if [ ! -d "$SRC_DIR" ]; then
      echo "错误: 未找到 Sidecar 目录: $SRC_DIR"
      exit 1
    fi

    # Copy the entire directory
    cp -r "$SRC_DIR/"* "$TAURI_SIDECAR_DIR/"

    # Ensure the executable is executable
    if [ "$OS_TYPE" = "windows" ]; then
      chmod +x "$TAURI_SIDECAR_DIR/sage-desktop.exe"
    else
      chmod +x "$TAURI_SIDECAR_DIR/sage-desktop"
    fi

    echo "[Sidecar] Sidecar 已复制到: $TAURI_SIDECAR_DIR"
}

build_frontend() {
    echo "[Frontend] 正在构建前端..."
    cd "$UI_DIR"

    # 智能依赖安装
    local LOCK_FILE="package-lock.json"
    local HASH_FILE="$CACHE_DIR/.package-lock.hash"
    local NEW_HASH=$(calc_hash "$LOCK_FILE")
    local OLD_HASH=""
    
    if [ -f "$HASH_FILE" ]; then
        OLD_HASH=$(cat "$HASH_FILE")
    fi

    if [ "$NEW_HASH" = "$OLD_HASH" ] && [ -d "node_modules" ]; then
        echo "[Frontend] 依赖未变更，跳过 npm install。"
    else
        npm install
        echo "$NEW_HASH" > "$HASH_FILE"
    fi

    # Increase Node.js memory limit for build
    export NODE_OPTIONS="--max-old-space-size=4096"
    npm run build
}

# 启动构建任务 (串行以避免 CI 内存溢出)
echo ">>> 开始构建任务..."

build_python_sidecar
if [ $? -ne 0 ]; then
    echo "构建失败！ Backend failed."
    exit 1
fi

build_frontend
if [ $? -ne 0 ]; then
    echo "构建失败！ Frontend failed."
    exit 1
fi

echo ">>> 构建完成。"

cd "$ROOT_DIR"

prepare_bundled_node_runtime

########################################
# 5. Setup Code Signing (Self-Signed)
########################################

CERT_DIR="$APP_DIR/scripts/certs"
CERT_B64_FILE="$CERT_DIR/cert.p12.base64"

# Generate certificate
echo "正在检查自签名证书..."
chmod +x "$APP_DIR/scripts/generate_cert.sh"
"$APP_DIR/scripts/generate_cert.sh"

if [ -f "$CERT_B64_FILE" ]; then
  echo "正在设置临时签名 (绕过证书要求)..."
  export APPLE_SIGNING_IDENTITY="-"
  echo "已启用临时代码签名。"
else
  echo "警告: 生成证书失败。构建将未签名。"
fi

########################################
# 6. Build Tauri
########################################

cd "$TAURI_DIR"

if ! command -v cargo >/dev/null; then
  echo "Cargo not found. Install Rust first."
  exit 1
fi

# Use tauri CLI from node_modules if available (much faster to install)
if [ -f "$UI_DIR/node_modules/.bin/tauri" ]; then
  echo "Using local Tauri CLI..."
  TAURI_CMD="$UI_DIR/node_modules/.bin/tauri"
elif command -v cargo-tauri >/dev/null; then
  echo "Using Cargo Tauri CLI..."
  TAURI_CMD="cargo tauri"
else
  echo "Installing Tauri CLI (via npm)..."
  # Fallback to global npm install (faster than cargo install)
  npm install -g @tauri-apps/cli
  TAURI_CMD="tauri"
fi

echo "Tauri CLI: $TAURI_CMD"

# Skip signature for updater artifacts as keys are not provided
# export TAURI_SKIP_SIGNATURE=true

if [ "$MODE" = "release" ]; then
  # Cargo.toml now has [profile.release] for optimization
  $TAURI_CMD build
else
  $TAURI_CMD build --debug
fi

echo "======================================"
echo " 构建成功完成"
echo "======================================"
