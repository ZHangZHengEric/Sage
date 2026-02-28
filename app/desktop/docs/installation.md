# Sage 桌面客户端安装指南

本文档说明如何在 macOS 和 Windows 上构建和安装 Sage 桌面应用程序。

## 1. 前置依赖安装

在开始之前，请确保已安装以下工具。

### 1.1 安装 Rust (和 Cargo)

Tauri 依赖 Rust 语言环境。

**macOS / Linux:**

打开终端运行：

```bash
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
```

或者brew安装：

```bash
brew install rustup-init
```

安装完成后，重启终端或运行 `source $HOME/.cargo/env` 以生效。验证安装：

```bash
cargo --version
# 输出示例: cargo 1.70.0 (ec8a8a0ca 2023-04-25)
```

**安装 Tauri CLI:**

为了更方便地使用 Tauri，请安装 Tauri CLI 工具 (需要 v1 版本)：

```bash
cargo install tauri-cli --version "^1.5"
```

**Windows:**

请访问 [Rust 官网](https://www.rust-lang.org/tools/install) 下载并运行 `rustup-init.exe`。

### 1.2 安装 Node.js

前端构建依赖 Node.js。推荐使用 LTS 版本 (v18+)。

**macOS (使用 Homebrew):**

```bash
brew install node
```

**Windows:**

请访问 [Node.js 官网](https://nodejs.org/) 下载安装包。

验证安装：

```bash
node -v
npm -v
```

### 1.3 安装 Python (3.11+)

后端服务依赖 Python 环境。

**macOS:**

推荐使用 Homebrew 或 Pyenv 安装。

```bash
brew install python@3.11
```

**Windows:**

请访问 [Python 官网](https://www.python.org/downloads/) 下载安装包。

### 1.4 (可选) 安装 Conda

为了更好地管理 Python 环境，推荐使用 Miniconda 或 Anaconda。

[Miniconda 下载地址](https://docs.conda.io/en/latest/miniconda.html)

---

## 2. 开发模式启动
我们提供了一个脚本 `dev.sh` 来简化开发模式的启动。
在项目根目录下运行：

```bash
chmod +x app/desktop/scripts/dev.sh
./app/desktop/scripts/dev.sh
```

## 3. 编译打包

我们提供了一键编译脚本，自动处理 Python 环境打包、前端构建和 Tauri 打包。

在项目根目录下运行：

```bash
chmod +x app/desktop/scripts/build.sh
./app/desktop/scripts/build.sh
```

**构建产物位置：**
- macOS: `app/desktop/tauri/target/release/bundle/macos/` (或 `.dmg`)
- Windows: `app/desktop/tauri/target/release/bundle/msi/`
