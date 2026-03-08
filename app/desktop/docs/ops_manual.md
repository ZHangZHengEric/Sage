# Sage 桌面端部署与运维手册

本指南涵盖系统管理员的部署策略。

## 静默安装

### macOS
使用 `installer` 命令行工具：
```bash
sudo installer -pkg Sage_Desktop.pkg -target /
```
注意: `.dmg` 通常包含 `.app`。若需自动化部署，考虑使用 `pkgbuild` 将 `.app` 打包为 `.pkg`。

### Windows
使用 `msiexec` 进行静默安装：
```powershell
msiexec /i Sage_Desktop.msi /quiet /norestart
```

## 通过组策略 (Windows) / 配置文件 (macOS) 进行配置

Sage Desktop 支持通过环境变量或全局配置文件进行配置。
应用程序会在以下位置查找 `sage_config.json`：
-   **Windows**: `%ProgramData%\Sage\config.json`
-   **macOS**: `/Library/Application Support/Sage/config.json`

`config.json` 示例：
```json
{
  "logLevel": "INFO",
  "disableUpdates": true,
  "proxy": "http://proxy.example.com:8080"
}
```

## 备份与恢复

### 备份脚本 (示例)
```bash
# macOS
cp -r ~/Library/Application\ Support/Sage/data /path/to/backup/
# Windows (PowerShell)
Copy-Item -Recurse $env:APPDATA\Sage\data D:\Backups\Sage
```

### 恢复脚本 (示例)
```bash
# 请先停止应用程序！
killall Sage
cp -r /path/to/backup/data ~/Library/Application\ Support/Sage/
```

## 日志管理

日志默认每天轮转并保留 7 天。
要更改日志级别，请在启动前设置 `LOG_LEVEL` 环境变量，或使用上述 `config.json`。

## 安全注意事项

-   **数据加密**: 确保用户磁盘已加密 (FileVault / BitLocker)。
-   **网络**: 应用程序仅绑定到 `127.0.0.1`。不需要为入站流量配置防火墙规则。
-   **更新**: 要禁用自动更新，请使用配置文件或阻止 `api.github.com`（如果使用 GitHub 发布）。
