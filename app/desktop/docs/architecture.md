# Sage Desktop Client Architecture

This document outlines the architecture for the Sage desktop client, a local-first application built with Tauri, Vue, and Python.

## 1. Overview

The Sage Desktop Client is designed to provide a seamless local experience for interacting with Sage agents. It wraps the existing Python backend (`app/server`) and Vue frontend (`app/web`) into a standalone desktop application using Tauri.

### Key Constraints & Decisions
- **No MySQL**: Replaced by SQLite.
- **No Redis/ES**: Replaced by local alternatives (in-memory locks, local file storage, ChromaDB/LanceDB for vectors).
- **Cross-Platform**: Supports macOS (Intel/Apple Silicon) and Windows (x64).
- **Deployment**: Single executable/installer with embedded Python environment.

## 2. Directory Structure

```
app/
├── desktop/                # New desktop module
│   ├── src-tauri/          # Rust/Tauri code
│   │   ├── src/            # Rust source (main.rs, etc.)
│   │   ├── tauri.conf.json # Tauri configuration
│   │   └── ...
│   ├── src-python/         # Python sidecar wrapper
│   │   ├── main.py         # Entry point for the sidecar
│   │   ├── adapters/       # Local adapters (FileStorage, VectorStore)
│   │   └── requirements.txt# Desktop-specific dependencies
│   ├── scripts/            # Build and packaging scripts
│   └── docs/               # Documentation
├── server/                 # Existing backend (referenced)
└── web/                    # Existing frontend (referenced)
```

## 3. Architecture Components

### 3.1. Frontend (Tauri + Vue)
- **Technology**: Tauri (Rust) for the shell, Vue 3 for the UI.
- **Responsibility**:
    - **Tauri**: Window management, system tray, native notifications, auto-updates, launching the Python sidecar.
    - **Vue**: User interface. It communicates with the Python backend via standard HTTP requests to `localhost`.
- **Modifications**:
    - The Vue app needs to be built into `app/desktop/src-tauri/dist` (or similar).
    - It needs to know the port the Python server is running on (passed via Tauri -> Window -> Vue).

### 3.2. Backend (Python Sidecar)
- **Technology**: FastAPI (existing), packaged with PyInstaller.
- **Responsibility**:
    - Running the Sage agent logic.
    - Managing data persistence (SQLite).
    - Handling file storage (Local File System).
    - Handling vector search (ChromaDB/LanceDB).
- **Modifications**:
    - **Entry Point**: A new `main.py` in `app/desktop/src-python` that sets up the environment and starts the server.
    - **Database**: Configured to use SQLite (`sqlite+aiosqlite:///...`).
    - **Storage**: Configured to use a local directory instead of S3.
    - **Vector Store**: Configured to use a local vector store instead of Elasticsearch.

### 3.3. Inter-Process Communication (IPC)
1.  **Startup**:
    - Tauri launches the Python executable as a sidecar.
    - Python server binds to `127.0.0.1` on a random free port (or a fixed port if preferred, but random is safer).
    - Python server outputs the port to stdout.
    - Tauri reads the port and emits it to the Vue frontend.
2.  **Runtime**:
    - **Vue -> Python**: Direct HTTP/WebSocket calls (e.g., `http://127.0.0.1:<port>/api/...`).
    - **Vue -> Tauri**: Tauri Commands (for window controls, system dialogs).
    - **Python -> Tauri**: Not directly needed; Python sends events via WebSockets to Vue.

## 4. Data Persistence & Security

### 4.1. Data Storage
- **Location**:
    - **macOS**: `~/Library/Application Support/Sage/data`
    - **Windows**: `%AppData%\Sage\data`
- **Database**: SQLite (`agent_platform.db`).
- **Files**: Local directory (`storage/`).
- **Vectors**: Local vector store (`vectors/`).

### 4.2. Security
- **Network**: Python server binds ONLY to `127.0.0.1`.
- **Authentication**:
    - Tauri generates a random `API_KEY` on startup.
    - Passes it to Python via environment variable.
    - Passes it to Vue via window initialization script.
    - All requests from Vue to Python must include this `API_KEY`.
- **Encryption**: SQLite database can be encrypted using SQLCipher (optional, per user request).

## 5. Build & Deployment Pipeline

### 5.1. Python Build
1.  Install dependencies (including `pyinstaller`).
2.  Run `pyinstaller` on `app/desktop/src-python/main.py`.
3.  Output the executable to `app/desktop/src-tauri/bin/`.

### 5.2. Frontend Build
1.  Run `npm run build` in `app/web`.
2.  Copy output to `app/desktop/src-tauri/dist/`.

### 5.3. Tauri Build
1.  Run `tauri build`.
2.  Bundles the Python executable and Frontend assets.
3.  Generates `.dmg`, `.app` (macOS) and `.msi`, `.exe` (Windows).

### 5.4. CI/CD
- **GitHub Actions**:
    - Matrix build (macos-latest, windows-latest).
    - Steps: Setup Python -> Build Python -> Setup Node -> Build Frontend -> Build Tauri -> Upload Artifacts.
