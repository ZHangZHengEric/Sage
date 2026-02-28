#!/bin/bash
set -e

# Add cargo to PATH
export PATH="$HOME/.cargo/bin:$PATH"

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"

# Detect OS
OS="$(uname -s)"
case "${OS}" in
    Linux*)     OS_TYPE=Linux;;
    Darwin*)    OS_TYPE=Mac;;
    CYGWIN*)    OS_TYPE=Cygwin;;
    MINGW*)     OS_TYPE=MinGw;;
    *)          OS_TYPE="UNKNOWN:${OS}"
esac

echo "Building for $OS_TYPE..."

# 1. Setup Python Environment
echo "Setting up Python environment..."
VENV_DIR="$ROOT_DIR/app/desktop/core/.venv"

if [ ! -d "$VENV_DIR" ]; then
    echo "Creating Python virtual environment at $VENV_DIR..."
    python3 -m venv "$VENV_DIR"
fi

source "$VENV_DIR/bin/activate"

# Install dependencies
pip install --upgrade setuptools
pip install -r "$ROOT_DIR/app/desktop/core/requirements.txt"
pip install pyinstaller

# 2. Build Python Sidecar
echo "Building Python Sidecar..."
export PYINSTALLER_CONFIG_DIR="$ROOT_DIR/.pyinstaller"
cd "$ROOT_DIR/app/desktop/core"
# Make sure we can import from app.desktop.core
export PYTHONPATH="$ROOT_DIR:$PYTHONPATH"
pyinstaller --clean --noconfirm --name sage-desktop --onefile --windowed main.py --paths="$ROOT_DIR"
cd "$ROOT_DIR"

# Move binary to tauri/bin
mkdir -p "$ROOT_DIR/app/desktop/tauri/bin"
if [ "$OS_TYPE" == "Mac" ]; then
    ARCH=$(uname -m)
    if [ "$ARCH" == "arm64" ]; then
        TARGET="aarch64-apple-darwin"
    else
        TARGET="$ARCH-apple-darwin"
    fi
    if [ -f "$ROOT_DIR/app/desktop/core/dist/sage-desktop" ]; then
        cp "$ROOT_DIR/app/desktop/core/dist/sage-desktop" "$ROOT_DIR/app/desktop/tauri/bin/sage-desktop-sidecar-$TARGET"
    elif [ -f "$ROOT_DIR/app/desktop/core/dist/sage-desktop.app/Contents/MacOS/sage-desktop" ]; then
        cp "$ROOT_DIR/app/desktop/core/dist/sage-desktop.app/Contents/MacOS/sage-desktop" "$ROOT_DIR/app/desktop/tauri/bin/sage-desktop-sidecar-$TARGET"
    else
        echo "Sidecar binary not found under app/desktop/core/dist"
        exit 1
    fi
elif [ "$OS_TYPE" == "MinGw" ] || [ "$OS_TYPE" == "Cygwin" ]; then
    TARGET="x86_64-pc-windows-msvc"
    if [ -f "$ROOT_DIR/app/desktop/core/dist/sage-desktop.exe" ]; then
        cp "$ROOT_DIR/app/desktop/core/dist/sage-desktop.exe" "$ROOT_DIR/app/desktop/tauri/bin/sage-desktop-sidecar-$TARGET.exe"
    else
        echo "Sidecar binary not found under app/desktop/core/dist"
        exit 1
    fi
else
    TARGET="x86_64-unknown-linux-gnu"
    if [ -f "$ROOT_DIR/app/desktop/core/dist/sage-desktop" ]; then
        cp "$ROOT_DIR/app/desktop/core/dist/sage-desktop" "$ROOT_DIR/app/desktop/tauri/bin/sage-desktop-sidecar-$TARGET"
    else
        echo "Sidecar binary not found under app/desktop/core/dist"
        exit 1
    fi
fi

echo "Python Sidecar built and moved to bin."

# 3. Build Frontend
echo "Building Frontend..."
cd "$ROOT_DIR/app/desktop/ui"
npm install
npm run build
cd "$ROOT_DIR"

# Move frontend build to desktop dist is handled by tauri config (distDir)
# But if we want to manually check or use it for something else:
# The dist will be at app/desktop/ui/dist

# 4. Build Tauri
echo "Building Tauri App..."
cd "$ROOT_DIR/app/desktop/tauri"
# Check if cargo is available
if command -v cargo &> /dev/null; then
    # Check if tauri-cli is installed
    if ! cargo tauri --version &> /dev/null; then
        echo "Tauri CLI not found. Installing..."
        cargo install tauri-cli --version "^1.5"
    elif [[ $(cargo tauri --version) == *"tauri-cli 2"* ]]; then
        echo "Tauri CLI v2 detected but v1 is required. Installing v1..."
        cargo install tauri-cli --version "^1.5" --force
    fi
    cargo tauri build
else
    echo "Cargo not found. Skipping Tauri build. Please install Rust and run 'cargo tauri build' manually."
fi

echo "Build complete!"
