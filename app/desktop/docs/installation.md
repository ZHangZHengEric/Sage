# Sage Desktop Installation Guide

This guide explains how to build and install the Sage Desktop application on macOS and Windows.

## Prerequisites

1.  **Node.js**: Version 18+ recommended.
2.  **Rust**: Install via `rustup` (https://rustup.rs).
3.  **Python**: Version 3.11+ (recommended 3.11.13).
4.  **Conda** (Optional but recommended): For managing Python environments.

## Setup Environment

### 1. Python Environment

Create a virtual environment:

```bash
conda create -n sage-desktop python=3.11
conda activate sage-desktop
pip install -r app/desktop/src_python/requirements.txt
```

### 2. Frontend Dependencies

Install Vue dependencies:

```bash
cd app/web
npm install
```

### 3. Tauri Dependencies

Install Tauri CLI:

```bash
cargo install tauri-cli
```

## Building the Application

We provide a script to automate the build process:

```bash
# From project root
chmod +x app/desktop/scripts/build.sh
./app/desktop/scripts/build.sh
```

This script will:
1.  Build the Python sidecar executable using PyInstaller.
2.  Build the Vue frontend.
3.  Bundle everything into a native application using Tauri.

The output will be located in `app/desktop/src-tauri/target/release/bundle/`.

## Development Mode

To run in development mode with hot-reloading:

1.  Start the Python backend manually (optional, or let Tauri handle it if configured for dev):
    ```bash
    # In a separate terminal
    python app/desktop/src_python/main.py
    ```

2.  Start the Frontend dev server:
    ```bash
    cd app/web
    npm run dev
    ```

3.  Start Tauri:
    ```bash
    cd app/desktop/src-tauri
    cargo tauri dev
    ```

## Troubleshooting

-   **Sidecar not found**: Ensure the Python executable is built and placed in `app/desktop/src-tauri/bin/`. The name must match the target architecture (e.g., `sage-server-x86_64-apple-darwin`).
-   **Port conflict**: The Python server tries to bind to a random port. Check logs for "Starting Sage Desktop Server on port ...".
