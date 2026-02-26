#!/bin/bash
set -e

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
# Assuming conda or venv is active, or use specific python
# Install dependencies
pip install -r app/desktop/src_python/requirements.txt
pip install pyinstaller

# 2. Build Python Sidecar
echo "Building Python Sidecar..."
cd app/desktop/src_python
pyinstaller --clean --noconfirm --name sage-server --onefile --windowed main.py
cd ../../../..

# Move binary to src-tauri/bin
mkdir -p app/desktop/src-tauri/bin
if [ "$OS_TYPE" == "Mac" ]; then
    # Add target triple for Tauri sidecar
    # Example: x86_64-apple-darwin or aarch64-apple-darwin
    ARCH=$(uname -m)
    TARGET="$ARCH-apple-darwin"
    cp app/desktop/src_python/dist/sage-server app/desktop/src-tauri/bin/sage-server-$TARGET
elif [ "$OS_TYPE" == "MinGw" ] || [ "$OS_TYPE" == "Cygwin" ]; then
    # Windows
    TARGET="x86_64-pc-windows-msvc"
    cp app/desktop/src_python/dist/sage-server.exe app/desktop/src-tauri/bin/sage-server-$TARGET.exe
else
    # Linux
    TARGET="x86_64-unknown-linux-gnu"
    cp app/desktop/src_python/dist/sage-server app/desktop/src-tauri/bin/sage-server-$TARGET
fi

echo "Python Sidecar built and moved to bin."

# 3. Build Frontend
echo "Building Frontend..."
cd app/web
npm install
npm run build
cd ../..

# Move frontend build to desktop dist
mkdir -p app/desktop/dist
cp -r app/web/dist/* app/desktop/dist/

# 4. Build Tauri
echo "Building Tauri App..."
cd app/desktop/src-tauri
# Check if cargo is available
if command -v cargo &> /dev/null; then
    cargo tauri build
else
    echo "Cargo not found. Skipping Tauri build. Please install Rust and run 'cargo tauri build' manually."
fi

echo "Build complete!"
