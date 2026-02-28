#!/usr/bin/env bash
set -euo pipefail

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
# 1. Python Environment Setup
########################################

# Clear Conda environment variables to prevent PyInstaller from misidentifying the environment
unset CONDA_PREFIX
unset CONDA_DEFAULT_ENV
unset CONDA_PYTHON_EXE
unset CONDA_SHLVL
unset CONDA_EXE
unset CONDA_PROMPT_MODIFIER

if [ ! -d "$VENV_DIR" ]; then
  echo "Creating virtualenv..."
  python3 -m venv "$VENV_DIR"
fi

# Create a fake conda-meta directory to suppress PyInstaller warnings
# when using a venv created by Conda Python
mkdir -p "$VENV_DIR/conda-meta"

source "$VENV_DIR/bin/activate"

echo "Upgrading build tools..."
pip install --upgrade pip setuptools wheel >/dev/null

echo "Installing dependencies..."
pip install -r "$ROOT_DIR/app/desktop/core/requirements.txt"

if ! command -v pyinstaller >/dev/null; then
  pip install pyinstaller
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

if [ ! -d node_modules ]; then
  npm ci
fi

npm run build

cd "$ROOT_DIR"

########################################
# 5. Setup Code Signing (Self-Signed)
########################################

CERT_DIR="$ROOT_DIR/app/desktop/scripts/certs"
CERT_B64_FILE="$CERT_DIR/cert.p12.base64"

# Generate certificate if it doesn't exist
if [ ! -f "$CERT_B64_FILE" ]; then
  echo "Generating self-signed certificate..."
  "$ROOT_DIR/app/desktop/scripts/generate_cert.sh"
fi

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