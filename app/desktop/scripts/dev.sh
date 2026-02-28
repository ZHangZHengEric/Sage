#!/bin/bash
set -e

# Add cargo to PATH
export PATH="$HOME/.cargo/bin:$PATH"

# Disable sandbox for desktop app
export SAGE_USE_SANDBOX=False

# 1. Determine paths
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
APP_ROOT="$SCRIPT_DIR/.."
PROJECT_ROOT="$(cd "$APP_ROOT/../.." && pwd)"
TAURI_DIR="$APP_ROOT/tauri"
CORE_DIR="$APP_ROOT/core"
UI_DIR="$APP_ROOT/ui"

# 1.5 Setup Python Environment
VENV_DIR="$CORE_DIR/.venv"
if [ ! -d "$VENV_DIR" ]; then
    echo "Creating Python virtual environment at $VENV_DIR..."
    python3 -m venv "$VENV_DIR"
fi

source "$VENV_DIR/bin/activate"

echo "Installing Python dependencies..."
pip install --upgrade setuptools
pip install -r "$CORE_DIR/requirements.txt"

# 2. Check and install frontend dependencies
if [ ! -d "$UI_DIR/node_modules" ]; then
    echo "Installing frontend dependencies..."
    cd "$UI_DIR"
    npm install
fi

# 3. Detect OS and Architecture for Sidecar
OS="$(uname -s)"
ARCH="$(uname -m)"

if [ "$OS" == "Darwin" ]; then
    if [ "$ARCH" == "arm64" ]; then
        TARGET="aarch64-apple-darwin"
    else
        TARGET="x86_64-apple-darwin"
    fi
elif [ "$OS" == "Linux" ]; then
    TARGET="x86_64-unknown-linux-gnu"
else
    echo "Warning: Unsupported OS for auto-sidecar generation script: $OS"
    echo "You may need to manually configure the sidecar."
    # Fallback to a generic name just in case, or exit?
    # Let's try to proceed, maybe it's Git Bash on Windows
    if [[ "$OS" == MINGW* ]] || [[ "$OS" == CYGWIN* ]]; then
         TARGET="x86_64-pc-windows-msvc"
         # Windows handling is tricky with shell scripts calling python
         echo "Windows detected. Please use a PowerShell script or manual setup for best results."
    fi
fi

if [ -n "$TARGET" ]; then
    SIDECAR_NAME="sage-desktop-sidecar-$TARGET"
    if [[ "$OS" == MINGW* ]] || [[ "$OS" == CYGWIN* ]]; then
        SIDECAR_NAME="$SIDECAR_NAME.exe"
    fi
    
    BIN_DIR="$TAURI_DIR/bin"
    mkdir -p "$BIN_DIR"
    SIDECAR_PATH="$BIN_DIR/$SIDECAR_NAME"

    echo "Creating sidecar wrapper at $SIDECAR_PATH..."

    # Create a wrapper script that runs the Python source
    # We use a trick for Windows: if it expects .exe, we might need a bat file or similar, 
    # but Tauri `Command::new_sidecar` on Windows appends .exe. 
    # For macOS/Linux, a shell script is fine.
    
    if [[ "$OS" == "Darwin" ]] || [[ "$OS" == "Linux" ]]; then
        cat > "$SIDECAR_PATH" <<EOF
#!/bin/bash
# Sidecar Wrapper for Development
# This script launches the Python source directly instead of a compiled binary.

# Calculate paths
PROJECT_ROOT="$PROJECT_ROOT"
CORE_DIR="\$PROJECT_ROOT/app/desktop/core"
VENV_PYTHON="\$CORE_DIR/.venv/bin/python"

# Set PYTHONPATH to include project root
export PYTHONPATH="\$PROJECT_ROOT:\$PYTHONPATH"

# Execute Python script
echo "Wrapper starting Python sidecar from source: app.desktop.core.main"
exec "\$VENV_PYTHON" -m app.desktop.core.main
EOF
        chmod +x "$SIDECAR_PATH"
    fi
fi

# 4. Start Tauri in Development Mode
echo "Starting Tauri in development mode..."
cd "$TAURI_DIR"

# Enable Rust logging to see println! output from main.rs
export RUST_LOG=info

# Check if cargo exists
if ! command -v cargo &> /dev/null; then
    echo "Error: cargo not found. Please install Rust."
    exit 1
fi

# Check if tauri-cli is installed
if ! cargo tauri --version &> /dev/null; then
    echo "Tauri CLI not found. Installing..."
    cargo install tauri-cli --version "^1.5"
elif [[ $(cargo tauri --version) == *"tauri-cli 2"* ]]; then
     echo "Tauri CLI v2 detected but v1 is required. Installing v1..."
     cargo install tauri-cli --version "^1.5" --force
fi

# Run Tauri Dev
# This will compile the Rust app and run it. 
# It will also start the frontend (via beforeDevCommand) and the sidecar (via wrapper).
cargo tauri dev
