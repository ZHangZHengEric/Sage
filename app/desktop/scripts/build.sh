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

MODE="${1:-release}"  # release | debug

echo "======================================"
echo " Sage Desktop Build ($MODE)"
echo " Root: $ROOT_DIR"
echo " Dist: $DIST_DIR"
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

echo "Using Conda: $CONDA_EXE"

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

echo "Python version: $(python --version)"
echo "Pip version: $(pip --version)"

echo "Upgrading build tools..."
pip install --upgrade pip setuptools wheel

echo "Installing dependencies..."
pip install -r "$APP_DIR/core/requirements.txt" --index-url https://pypi.tuna.tsinghua.edu.cn/simple

if ! command -v pyinstaller >/dev/null; then
  pip install pyinstaller --index-url https://pypi.org/simple
fi

########################################
# 2. Build Python Sidecar
########################################

echo "Building Python sidecar..."

rm -rf "$DIST_DIR"
mkdir -p "$DIST_DIR"

export PYINSTALLER_CONFIG_DIR="$ROOT_DIR/.pyinstaller"
export PYTHONPATH="$ROOT_DIR:${PYTHONPATH:-}"
cd "$APP_DIR"

# Optimization: Exclude unnecessary modules to reduce size
PYI_FLAGS=(
  --noconfirm
  --clean
  --onedir
  --log-level=WARN
  --name sage-desktop
  --hidden-import=aiosqlite
  --hidden-import=greenlet
  --hidden-import=sqlalchemy.dialects.sqlite.aiosqlite
  # Exclusions
  --exclude-module=tkinter
  --exclude-module=unittest
  --exclude-module=pydoc
  --exclude-module=doctest
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
fi

pyinstaller "${PYI_FLAGS[@]}" entry.py

# Clean up pyinstaller output
echo "Cleaning up distribution..."
find "$DIST_DIR" -name "__pycache__" -type d -exec rm -rf {} +
find "$DIST_DIR" -name "*.pyc" -delete
find "$DIST_DIR" -name ".DS_Store" -delete

# Copy mcp_servers to distribution directory
echo "Copying mcp_servers to distribution..."
# Ensure target dir exists inside the bundled app
# PyInstaller onedir puts things in dist/sage-desktop/_internal usually, or top level depending on config
# Checking where pyinstaller puts things. Usually it's dist/sage-desktop.
# We want mcp_servers accessible to the app.
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

cd "$ROOT_DIR"

########################################
# 3. Move Binary to Tauri
########################################

echo "Moving binaries to Tauri sidecar directory..."

# Clean up previous build
rm -rf "$TAURI_SIDECAR_DIR"
mkdir -p "$TAURI_SIDECAR_DIR"

SRC_DIR="$DIST_DIR/sage-desktop"

if [ ! -d "$SRC_DIR" ]; then
  echo "ERROR: Sidecar directory not found: $SRC_DIR"
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

echo "Sidecar copied to: $TAURI_SIDECAR_DIR"

########################################
# 4. Build Frontend
########################################

echo "Building frontend..."

cd "$UI_DIR"

# Always install/update dependencies
npm install

npm run build

cd "$ROOT_DIR"

########################################
# 5. Setup Code Signing (Self-Signed)
########################################

CERT_DIR="$APP_DIR/scripts/certs"
CERT_B64_FILE="$CERT_DIR/cert.p12.base64"

# Generate certificate
echo "Checking self-signed certificate..."
chmod +x "$APP_DIR/scripts/generate_cert.sh"
"$APP_DIR/scripts/generate_cert.sh"

if [ -f "$CERT_B64_FILE" ]; then
  echo "Setting up self-signed certificate..."
  export APPLE_CERTIFICATE="$(cat "$CERT_B64_FILE")"
  export APPLE_CERTIFICATE_PASSWORD="sage-password"
  export APPLE_SIGNING_IDENTITY="SageAI Self Signed"
  echo "Code signing enabled with self-signed certificate."
else
  echo "WARNING: Failed to generate certificate. Build will be unsigned."
fi

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

if [ "$MODE" = "release" ]; then
  # Cargo.toml now has [profile.release] for optimization
  cargo tauri build
else
  cargo tauri build --debug
fi

echo "======================================"
echo " Build Completed Successfully"
echo "======================================"
