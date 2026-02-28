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
NO_PYTHON_BUILD=1
MODE="debug"  # release | debug

echo "======================================"
echo " Sage Desktop Build ($MODE)"
echo " Root: $ROOT_DIR"
echo " Tip: Set NO_PYTHON_BUILD=1 to skip sidecar build"
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
# 2. Build Python Sidecar (Wrapper Script)
########################################

echo "Setting up Python sidecar wrapper..."

TAURI_BIN_DIR="$ROOT_DIR/app/desktop/tauri/bin"
mkdir -p "$TAURI_BIN_DIR"

# Get current python executable path
PYTHON_EXEC=$(python -c "import sys; print(sys.executable)")

# Determine target triple name
SIDECAR_NAME="sage-desktop-sidecar-$TARGET"
SIDECAR_PATH="$TAURI_BIN_DIR/$SIDECAR_NAME"

echo "Generating sidecar script at: $SIDECAR_PATH"

# Create wrapper script
cat > "$SIDECAR_PATH" <<EOF
#!/bin/bash
export PYTHONPATH="$ROOT_DIR:\$PYTHONPATH"
exec "$PYTHON_EXEC" "$ROOT_DIR/app/desktop/entry.py" "\$@"
EOF

chmod +x "$SIDECAR_PATH"

echo "Sidecar wrapper created."

# Ensure sidecar directory exists and is not empty to satisfy tauri.conf.json resources
TAURI_SIDECAR_DIR="$ROOT_DIR/app/desktop/tauri/sidecar"
mkdir -p "$TAURI_SIDECAR_DIR"
touch "$TAURI_SIDECAR_DIR/.keep"

########################################
# 3. Move Binary to Tauri (Skipped)
########################################
# Since we are using a wrapper script in place, we don't need to copy binaries.
# The wrapper script IS the sidecar.

########################################
# 4. Frontend Setup
########################################

echo "Setting up frontend dependencies..."
cd "$ROOT_DIR/app/desktop/ui"

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

cargo tauri dev

echo "======================================"
echo " Build Completed Successfully"
echo "======================================"