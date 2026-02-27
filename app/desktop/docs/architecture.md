# Sage 桌面客户端架构

本文档概述了 Sage 桌面客户端的架构，这是一个使用 Tauri、Vue 和 Python 构建的本地优先应用程序。

## 1. 概述

Sage 桌面客户端旨在提供与其智能代理交互的无缝本地体验。它使用 Tauri 将现有的 Python 后端 (`app/desktop/core`) 和 Vue 前端 (`app/desktop/ui`) 封装成一个独立的桌面应用程序。

### 关键约束与决策
- **无 MySQL**: 被 SQLite 取代。
- **无 Redis/ES**: 被本地替代方案取代（内存锁、本地文件存储、ChromaDB/LanceDB 用于向量存储）。
- **跨平台**: 支持 macOS (Intel/Apple Silicon) 和 Windows (x64)。
- **部署**: 带有嵌入式 Python 环境的单可执行文件/安装程序。

## 2. 目录结构

```
app/
├── desktop/                # 桌面客户端根目录
│   ├── ui/                 # Vue 前端代码 (原 app/desktop/web)
│   ├── core/               # Python 核心逻辑与 Sidecar (原 app/desktop/server + src_python)
│   │   ├── run_desktop.py  # Sidecar 入口点
│   │   ├── adapters/       # 本地适配器 (FileStorage, VectorStore)
│   │   ├── requirements.txt# 依赖列表
│   │   └── ...             # 核心业务逻辑
│   ├── tauri/              # Rust/Tauri 代码
│   │   ├── src/            # Rust 源码 (main.rs 等)
│   │   ├── tauri.conf.json # Tauri 配置
│   │   └── ...
│   ├── scripts/            # 构建和打包脚本
│   └── docs/               # 文档
```

## 3. 架构组件

### 3.1. 前端 (Tauri + Vue)
- **技术栈**: Tauri (Rust) 作为外壳，Vue 3 作为 UI。
- **职责**:
    - **Tauri**: 窗口管理、系统托盘、原生通知、自动更新、启动 Python Sidecar。
    - **Vue**: 用户界面。通过标准 HTTP 请求与 Python 后端通信（指向 `localhost`）。
- **修改**:
    - Vue 应用位于 `app/desktop/ui`。
    - 构建产出位于 `app/desktop/ui/dist`，Tauri 会自动读取。
    - 它需要知道 Python 服务器运行的端口（通过 Tauri -> Window -> Vue 传递）。

### 3.2. 后端 (Python Sidecar)
- **技术栈**: FastAPI (现有)，使用 PyInstaller 打包。
- **职责**:
    - 运行 Sage 智能代理逻辑。
    - 管理数据持久化 (SQLite)。
    - 处理文件存储 (本地文件系统)。
    - 处理向量搜索 (ChromaDB/LanceDB)。
- **修改**:
    - **入口点**: `app/desktop/core/run_desktop.py`，它会加载 `app/desktop/core` 中的核心逻辑。
    - **数据库**: 配置为使用 SQLite (`sqlite+aiosqlite:///...`)。
    - **存储**: 配置为使用本地目录而非 S3。
    - **向量存储**: 配置为使用本地向量存储而非 Elasticsearch。

### 3.3. 进程间通信 (IPC)
1.  **启动**:
    - Tauri 启动 Python 可执行文件作为 Sidecar。
    - Python 服务器绑定到 `127.0.0.1` 上的一个随机空闲端口（或者固定端口，但随机更安全）。
    - Python 服务器将端口输出到 stdout。
    - Tauri 读取端口并将其发送给 Vue 前端。
2.  **运行时**:
    - **Vue -> Python**: 直接 HTTP/WebSocket 调用（例如 `http://127.0.0.1:<port>/api/...`）。
    - **Vue -> Tauri**: Tauri 命令（用于窗口控制、系统对话框）。
    - **Python -> Tauri**: 不需要直接通信；Python 通过 WebSocket 向 Vue 发送事件。

## 4. 数据持久化与安全

### 4.1. 数据存储
- **位置**:
    - **macOS**: `~/Library/Application Support/Sage/data`
    - **Windows**: `%AppData%\Sage\data`
- **数据库**: SQLite (`agent_platform.db`)。
- **文件**: 本地目录 (`storage/`)。
- **向量**: 本地向量存储 (`vectors/`)。

### 4.2. 安全
- **网络**: Python 服务器仅绑定到 `127.0.0.1`。
- **认证**:
    - Tauri 在启动时生成一个随机 `API_KEY`。
    - 通过环境变量传递给 Python。
    - 通过窗口初始化脚本传递给 Vue。
    - Vue 发往 Python 的所有请求必须包含此 `API_KEY`。
- **加密**: SQLite 数据库可以使用 SQLCipher 加密（可选，根据用户需求）。

## 5. 构建与部署流程

### 5.1. Python 构建
1.  安装依赖（包括 `pyinstaller`）。
2.  对 `app/desktop/core/run_desktop.py` 运行 `pyinstaller`。
3.  将可执行文件输出到 `app/desktop/tauri/bin/`。

### 5.2. 前端构建
1.  在 `app/desktop/ui` 中运行 `npm run build`。
2.  Tauri 构建过程会自动使用 `app/desktop/ui/dist`。

### 5.3. Tauri 构建
1.  运行 `tauri build`。
2.  打包 Python 可执行文件和前端资源。
3.  生成 `.dmg`, `.app` (macOS) 和 `.msi`, `.exe` (Windows)。

### 5.4. CI/CD
- **GitHub Actions**:
    - 矩阵构建 (macos-latest, windows-latest)。
    - 步骤: 设置 Python -> 构建 Python -> 设置 Node -> 构建前端 -> 构建 Tauri -> 上传构建产物。
