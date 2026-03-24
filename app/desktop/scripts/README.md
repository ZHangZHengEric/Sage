# Build 脚本说明

## setup-node-runtime.sh

这个脚本用于下载 Node.js 运行时，将其打包进 Sage 应用中。

### 用途

Sage 的一些 Skill 需要 Node.js 环境来运行（如 `agent-browser`、`docx` 等）。为了确保用户机器上没有安装 Node.js 也能正常使用这些功能，我们将 Node.js 运行时打包进应用。

### 使用方法

在构建 Sage 应用之前运行此脚本：

```bash
cd app/desktop/scripts
./setup-node-runtime.sh
```

### 脚本功能

1. 检测当前平台（macOS/Linux/Windows）和架构（x64/arm64）
2. 从国内镜像源（npmmirror.com）下载对应版本的 Node.js
3. 解压到 `app/desktop/tauri/sidecar/node/` 目录
4. 验证 Node.js 和 NPM 是否可用

### 下载的 Node.js 版本

- 版本: 20.11.0 (LTS)
- 支持平台:
  - macOS (x64, arm64)
  - Linux (x64, arm64)
  - Windows (x64)

### 构建流程

完整的构建流程应该是：

```bash
# 1. 下载 Node.js 运行时
cd app/desktop/scripts
./setup-node-runtime.sh

# 2. 构建 Tauri 应用
cd ../tauri
cargo tauri build
```

### 注意事项

1. **网络问题**: 脚本使用国内镜像源，如果下载失败可以检查网络连接或更换镜像源
2. **磁盘空间**: Node.js 运行时约 40MB，确保有足够的磁盘空间
3. **权限问题**: 确保脚本有执行权限 (`chmod +x setup-node-runtime.sh`)

### 手动下载

如果脚本运行失败，也可以手动下载 Node.js：

```bash
# 以 macOS arm64 为例
NODE_VERSION="20.11.0"
curl -L -o node.tar.gz "https://npmmirror.com/mirrors/node/v${NODE_VERSION}/node-v${NODE_VERSION}-darwin-arm64.tar.gz"
tar -xzf node.tar.gz -C app/desktop/tauri/sidecar/node --strip-components=1
```
