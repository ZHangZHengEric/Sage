#!/usr/bin/env bash
set -euo pipefail
# Add cargo to PATH
export PATH="$HOME/.cargo/bin:$PATH"

########################################
# Sage Desktop Industrial Build Script
########################################

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
VENV_DIR="$ROOT_DIR/app/desktop/core/.venv"
DIST_DIR="$ROOT_DIR/app/desktop/dist"
TAURI_BIN_DIR="$ROOT_DIR/app/desktop/tauri/bin"

MODE="${1:-release}"  # release | debug

echo "======================================"
echo " Sage Desktop Build ($MODE)"
echo " Root: $ROOT_DIR"
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
pip install -r "$ROOT_DIR/app/desktop/core/requirements.txt" --index-url https://pypi.tuna.tsinghua.edu.cn/simple

if ! command -v pyinstaller >/dev/null; then
  pip install pyinstaller --index-url https://pypi.org/simple
fi

########################################
# 2. Build Python Sidecar
########################################

echo "Building Python sidecar..."

rm -rf "$DIST_DIR"

export PYINSTALLER_CONFIG_DIR="$ROOT_DIR/.pyinstaller"
export PYTHONPATH="$ROOT_DIR:${PYTHONPATH:-}"
cd "$ROOT_DIR/app/desktop"

PYI_FLAGS=(
  --noconfirm
  --clean
  --onedir
  --log-level=WARN
  --name sage-desktop
  --hidden-import=aiosqlite
  --hidden-import=greenlet
  --hidden-import=sqlalchemy.dialects.sqlite.aiosqlite
)

if [ "$MODE" = "release" ]; then
  PYI_FLAGS+=(--strip)
  PYI_FLAGS+=(--noupx)
fi

pyinstaller "${PYI_FLAGS[@]}" entry.py

cd "$ROOT_DIR"

########################################
# 3. Move Binary to Tauri
########################################

# Define the sidecar directory in Tauri
TAURI_SIDECAR_DIR="$ROOT_DIR/app/desktop/tauri/sidecar"

# Clean up previous build
rm -rf "$TAURI_SIDECAR_DIR"
mkdir -p "$TAURI_SIDECAR_DIR"

if [ "$OS_TYPE" = "windows" ]; then
  SRC_DIR="$DIST_DIR/sage-desktop"
else
  SRC_DIR="$DIST_DIR/sage-desktop"
fi

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

echo "Sidecar copied to:"
echo "$TAURI_SIDECAR_DIR"

########################################
# 4. Build Frontend
########################################

echo "Building frontend..."

cd "$ROOT_DIR/app/desktop/ui"

# Always install/update dependencies to ensure everything in package.json is installed
npm install

npm run build

cd "$ROOT_DIR"

########################################
# 5. Setup Code Signing (Self-Signed)
########################################

CERT_DIR="$ROOT_DIR/app/desktop/scripts/certs"
CERT_B64_FILE="$CERT_DIR/cert.p12.base64"

# Generate certificate (script checks if regeneration is needed)
echo "Checking self-signed certificate..."
chmod +x "$ROOT_DIR/app/desktop/scripts/generate_cert.sh"
"$ROOT_DIR/app/desktop/scripts/generate_cert.sh"

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

cd "$ROOT_DIR/app/desktop/tauri"

if ! command -v cargo >/dev/null; then
  echo "Cargo not found. Install Rust first."
  exit 1
fi

if ! cargo tauri --version >/dev/null 2>&1; then
  echo "Installing tauri-cli v1..."
  cargo install tauri-cli --version "^1.5"
fi

if [ "$MODE" = "release" ]; then
  cargo tauri build
else
  cargo tauri build --debug
fi

echo "======================================"
echo " Build Completed Successfully"
echo "======================================"