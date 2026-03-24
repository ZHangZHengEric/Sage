# Sage 自动更新架构与开发报告

## 1. 架构概览

Sage 客户端自动更新系统采用 **Tauri v2 Updater** 标准架构。整个流程包含三个核心部分：

1. **制品构建与发布 (CI/CD)**：通过 GitHub Actions 自动化构建安装包及更新包，并发布到 GitHub Releases。
2. **服务端分发 (Update Server)**：Sage 服务端提供 API 接口，向客户端返回最新的版本信息和下载地址。
3. **客户端更新 (Client Updater)**：Sage 桌面端定期检查更新，验证签名并自动下载安装。

***

## 2. 制品包来源 (Package Origin)

制品包由 GitHub Actions 工作流自动生成。

文件路径：`.github/workflows/release-desktop.yml`

当推送以 `desktop-v*` 开头的 Tag (例如 `desktop-v1.0.1`) 时，工作流会自动触发：

1. **环境准备**：配置 Node.js, Rust, Python 环境。
2. **构建应用**：
   - **macOS**: 生成 `.dmg` 安装包和 `.tar.gz` 更新包。
   - **Windows**: 生成 `.exe` 安装包和 `.zip` 更新包。
3. **签名 (Signing)**：构建过程中，Tauri CLI 会使用配置的私钥对更新包进行签名，生成 `.sig` 文件。
4. **发布 (Release)**：将所有生成的包 (`.dmg`, `.exe`, `.tar.gz`, `.zip`, `.sig`) 上传到 GitHub Releases。

### 2.2 关键产物

对于自动更新，我们需要关注以下文件：

- **macOS**: `SageAI-<version>-<arch>.tar.gz` 和 `.tar.gz.sig`
- **Windows**: `SageAI-<version>-x86_64-setup.zip` 和 `.zip.sig`

### 2.3 签名配置 (必须)

为了确保更新安全，您需要生成一对密钥，并配置到 GitHub Secrets 中。

1. **生成密钥**:
   在本地运行命令：
   ```bash
   npm run tauri signer generate -w app/desktop/tauri/tauri.conf.json
   ```
   此命令会：
   - 自动修改 `tauri.conf.json` 添加公钥 (`pubkey`)。
   - 在终端输出私钥 (`Private key`) 和密码。
2. **配置 GitHub Secrets**:
   在 GitHub 仓库设置中添加以下 Secrets：
   - `TAURI_SIGNING_PRIVATE_KEY`: 填入上一步生成的私钥内容。
   - `TAURI_SIGNING_PRIVATE_KEY_PASSWORD`: 填入生成的密码 (如果生成时留空则为空)。

***

## 3. 服务端实现 (Update Server)

服务端负责告诉客户端“有没有新版本”以及“去哪里下载”。

### 3.1 数据库模型

文件：`app/server/models/system.py`

- **Version**: 存储版本号、发布说明、发布时间。
- **VersionArtifact**: 存储不同平台 (macOS/Windows) 的下载链接 (URL) 和签名 (Signature)。

### 3.2 API 接口

文件：`app/server/routers/version.py`

- `GET /api/system/version/check`: **Tauri 更新检查接口**。
  - 返回格式符合 Tauri v2 规范。
  - 包含版本号、发布说明、各平台的下载 URL 和签名。
- `GET /api/system/version/latest`: **Web 下载页接口**。
  - 用于前端下载页面展示最新版本信息。
- `POST /api/system/version`: **版本发布接口** (管理员用)。
  - CI/CD 完成后，或者管理员手动，将 GitHub Release 的信息录入到数据库。

***

## 4. 客户端实现 (Desktop Client)

客户端负责检测、下载和应用更新。

### 4.1 配置

文件：`app/desktop/tauri/tauri.conf.json`

- `plugins.updater.endpoints`: 设置为 `["https://您的服务端域名/api/system/version/check"]`。
- `plugins.updater.pubkey`: 必须填入生成的公钥。

### 4.2 交互逻辑

文件：`app/desktop/ui/src/views/SystemSettings.vue`

- 用户点击“检查更新”。
- 调用 `check()` 方法查询服务端。
- 如有更新，弹出确认框展示 Release Notes。
- 用户确认后，下载并重启应用 (`relaunch()`)。

***

## 5. 发布流程总结 (SOP)

1. **代码准备**: 完成开发，提交代码。
2. **打标签 (Tag)**: `git tag desktop-v1.0.1 && git push origin desktop-v1.0.1`。
3. **等待构建**: 观察 GitHub Actions，等待 Release 构建完成。
4. **录入版本**: 获取 GitHub Release 中的下载链接和 `.sig` 文件内容，调用服务端接口录入数据库：
   ```json
   POST /api/system/version
   {
     "version": "1.0.1",
     "release_notes": "修复了一些已知问题...",
     "artifacts": [
       {
         "platform": "darwin-aarch64",
         "url": "https://github.com/.../SageAI-1.0.1-aarch64.tar.gz",
         "signature": "Content of .tar.gz.sig"
       },
       {
         "platform": "windows-x86_64",
         "url": "https://github.com/.../SageAI-1.0.1-x86_64-setup.zip",
         "signature": "Content of .zip.sig"
       }
     ]
   }
   ```
5. **用户更新**: 客户端即可检测到新版本。

