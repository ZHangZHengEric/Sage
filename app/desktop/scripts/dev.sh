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
echo " Sage Desktop Dev ($MODE)"
echo " Root: $ROOT_DIR"
echo " Tip: Set NO_PYTHON_BUILD=1 to skip sidecar build (Default: 1)"
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
    echo "Unsupported OS: $OS"
    exit 1
    ;;
esac

echo "OS: $OS_TYPE"
echo "Target: $TARGET"

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
  echo "ERROR: Conda not found. Please install Miniconda or Anaconda."
  exit 1
fi

# Initialize conda for shell interaction
CONDA_BASE=$($CONDA_EXE info --base)
source "$CONDA_BASE/etc/profile.d/conda.sh"

ENV_NAME="sage-desktop-env"

# Check if environment exists
if conda info --envs | grep -q "$ENV_NAME"; then
  echo "Conda environment '$ENV_NAME' exists."
else
  echo "Creating Conda environment '$ENV_NAME' with Python 3.11..."
  conda create -n "$ENV_NAME" python=3.11 -y
fi

echo "Activating Conda environment '$ENV_NAME'..."
conda activate "$ENV_NAME"

# Export Python path for Tauri
# Use 'which python' to get the path from the active environment
export SAGE_PYTHON="$(which python)"
echo "Set SAGE_PYTHON: $SAGE_PYTHON"

if [[ "$CONDA_EXE" == *"anaconda3"* ]]; then
    conda install -n "$ENV_NAME" numba -y
fi
echo "Installing dependencies..."
pip install -r "$APP_DIR/core/requirements.txt" --index-url https://pypi.tuna.tsinghua.edu.cn/simple

if ! command -v pyinstaller >/dev/null; then
  pip install pyinstaller --index-url https://pypi.org/simple
fi

########################################
# 2. Build Python Sidecar (Wrapper Script)
########################################

echo "Setting up Python sidecar wrapper..."

mkdir -p "$TAURI_BIN_DIR"
mkdir -p "$TAURI_SIDECAR_DIR"

# Get current python executable path
PYTHON_EXEC=$(python -c "import sys; print(sys.executable)")

# Create wrapper script that acts as the sidecar executable
# This is used for dev mode to avoid rebuilding the binary
SIDECAR_WRAPPER="$TAURI_SIDECAR_DIR/sage-desktop"
if [ "$OS_TYPE" = "windows" ]; then
  SIDECAR_WRAPPER="$TAURI_SIDECAR_DIR/sage-desktop.exe"
fi

echo "Generating sidecar wrapper at: $SIDECAR_WRAPPER"

cat > "$SIDECAR_WRAPPER" <<EOF
#!/bin/bash
export PYTHONPATH="$ROOT_DIR:\$PYTHONPATH"
# Ensure mcp_servers are accessible (dev mode relies on source path)
# The app expects mcp_servers relative to executable or in a known location
# In dev, we can just point to source
exec "$PYTHON_EXEC" "$APP_DIR/entry.py" "\$@"
EOF

chmod +x "$SIDECAR_WRAPPER"

# Also create a .keep file
touch "$TAURI_SIDECAR_DIR/.keep"

echo "Sidecar wrapper created."

########################################
# 4. Frontend Setup
########################################

echo "Setting up frontend dependencies..."
cd "$UI_DIR"

if ! command -v npm >/dev/null; then
  echo "ERROR: npm not found. Please install Node.js."
  exit 1
fi

if [ ! -d "node_modules" ]; then
  echo "Installing frontend dependencies..."
  npm install
fi

cd "$ROOT_DIR"

########################################
# 6. Build Tauri
########################################

cd "$TAURI_DIR"

if ! command -v cargo >/dev/null; then
  echo "Cargo not found. Install Rust first."
  exit 1
fi

if ! cargo tauri --version >/dev/null 2>&1; then
  echo "Installing tauri-cli v1..."
  cargo install tauri-cli --version "^1.5"
fi

echo "======================================"
echo " Dev Server Running"
echo "======================================"

cargo tauri dev
