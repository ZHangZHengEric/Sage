---
layout: default
title: 桌面应用
parent: 应用入口
nav_order: 5
description: "安装桌面端、macOS/Windows 首次打开说明，以及从源码构建"
lang: zh
ref: desktop-app
---

{% include lang_switcher.html %}

# 桌面应用

**桌面端** 为 Tauri 打包的本地产品：在 `127.0.0.1` 上起本地 HTTP 服务 + 桌面壳 UI。适合**单机、日常**使用，而无需在终端里长期跑完整 `app/server` 开发栈。

| 内容 | 位置 |
|------|------|
| 安装包（`.dmg` / `.exe` / `.deb`） | [GitHub Releases](https://github.com/ZHangZHengEric/Sage/releases) |
| 构建依赖与步骤（Rust、Node、Python、Tauri 等） | [桌面端安装与构建 — 详细](../../../app/desktop/docs/installation.md) |
| 使用与运维 | [运维手册](../../../app/desktop/docs/ops_manual.md) · [用户说明](../../../app/desktop/docs/user_manual.md) |
| 架构 | [桌面应用架构](../architecture/ARCHITECTURE_APP_DESKTOP.md) |

## 使用发行包安装

1. 在 [Releases](https://github.com/ZHangZHengEric/Sage/releases) 下载对应系统安装包（如 macOS 用 `.dmg`，Windows 用 NSIS 的 `.exe`，Linux 用 `.deb`）。
2. 按安装向导或拖拽到「应用程序」等完成安装。
3. 从开始菜单、启动台或应用程序文件夹启动 Sage。

## macOS：门闸与「已损坏」

发布包**不一定**经过 Apple 公证。若出现「无法打开，因为无法验证开发者」或「无法检查是否包含恶意软件」：

1. 在**访达 → 应用程序**中**右键** `Sage.app` → **打开** → 在弹窗中再点**打开**。
2. 若仍被拦：**系统设置 → 隐私与安全性** → 找到关于 Sage 的提示 → **仍要打开** 后重试。
3. 若提示应用**已损坏**或无法启动，可清除隔离后重试：

```bash
xattr -dr com.apple.quarantine /Applications/Sage.app
```

## Windows：SmartScreen

若 **SmartScreen** 拦截安装程序，可点**更多信息** → **仍要运行**（不同版本文案可能略有差异）。

## Linux：安装 `.deb`

在 Debian / Ubuntu 上，下载对应架构的 `.deb` 后：

```bash
sudo apt install ./Sage-<version>-<arch>.deb
```

多数桌面环境也支持直接双击安装。

## 从源码构建

在仓库根目录（完整环境与依赖见 [安装指南](../../../app/desktop/docs/installation.md)）：

```bash
# macOS / Linux
app/desktop/scripts/build.sh release
```

```powershell
# Windows
./app/desktop/scripts/build_windows.ps1 release
```

产物路径与各平台注意点以 [安装指南](../../../app/desktop/docs/installation.md) 为准。

## 延伸阅读

- [快速开始](GETTING_STARTED.md) — 文末亦含桌面构建说明
- [环境变量 — 与桌面/安装相关](../ENV_VARS.md#8-桌面端--安装期)
