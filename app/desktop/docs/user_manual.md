# Sage 桌面端用户手册

## 安装

### macOS
1.  下载最新发布的 `.dmg` 文件。
2.  打开 `.dmg` 文件。
3.  将 **Sage Desktop** 图标拖入 **Applications** (应用程序) 文件夹。
4.  从启动台或应用程序中启动 **Sage Desktop**。
    *   *注意*: 首次启动时，可能会看到安全警告。请前往 **系统设置 > 隐私与安全性** 并点击 **仍要打开**。

### Windows
1.  下载 `.msi` 安装程序或 `.exe` 设置文件。
2.  运行安装程序并按照屏幕上的说明进行操作。
3.  从开始菜单或桌面快捷方式启动 **Sage Desktop**。

## 使用指南

### 初始设置
首次启动时，应用程序将初始化本地环境：
-   **数据库**: 创建于 `~/Library/Application Support/Sage/data` (macOS) 或 `%AppData%\Sage\data` (Windows)。
-   **文件**: 初始化本地存储目录。
-   **向量库**: 初始化本地向量数据库。

### 主界面
界面与网页版相同，但完全在您的机器上运行。
-   **对话**: 与智能代理互动。
-   **知识库**: 上传文件（PDF, TXT, MD）进行本地处理。
    *   *注意*: 处理大文件可能会花费一些时间，具体取决于您的计算机性能。

### 数据管理
您的所有数据都存储在本地。
-   **备份**: 您可以通过复制上述 `data` 目录来备份数据。
-   **卸载**:
    -   macOS: 将应用程序拖入废纸篓。要删除数据，请删除 `~/Library/Application Support/Sage`。
    -   Windows: 使用“添加或删除程序”。要删除数据，请删除 `%AppData%\Sage`。

## 故障排除

### 应用程序无法启动
-   检查是否已有另一个实例在运行。
-   重启计算机。

### "Backend not ready" (后端未就绪) 错误
-   Python 后台服务可能启动失败。
-   检查日志：
    -   macOS: `~/Library/Logs/Sage Desktop/`
    -   Windows: `%AppData%\Sage\logs\`
