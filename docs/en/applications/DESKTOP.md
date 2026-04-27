---

## layout: default
title: Desktop Application
parent: Applications
nav_order: 5
description: "Install the Sage desktop app, first-launch on macOS/Windows, and build from source"
lang: en
ref: desktop-app

{% include lang_switcher.html %}

# Desktop Application

The **Desktop** app is a Tauri-packaged product: a local HTTP backend on `127.0.0.1` plus a desktop shell UI. It is the best fit for daily **offline-friendly** work on a single machine without running the full `app/server` dev stack in terminals.


| Topic                                           | Where                                                                                                                  |
| ----------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------- |
| Installers (`.dmg` / `.exe` / `.deb`)           | [GitHub Releases](https://github.com/ZHangZHengEric/Sage/releases)                                                     |
| Build prerequisites (Rust, Node, Python, Tauri) | [Desktop build & install — detailed](../../../app/desktop/docs/installation.md)                                        |
| End-user / ops topics                           | [Operations manual](../../../app/desktop/docs/ops_manual.md) · [User manual](../../../app/desktop/docs/user_manual.md) |
| Architecture                                    | [Desktop app architecture](../architecture/ARCHITECTURE_APP_DESKTOP.md)                                                |


## Install from release packages

1. Download the package for your OS from [Releases](https://github.com/ZHangZHengEric/Sage/releases) (e.g. `.dmg` for macOS, `.exe` / `.msi` for Windows, `.deb` for Linux).
2. Run the installer or drag the app as documented on the download page.
3. Launch Sage from the Start menu, Applications folder, or app grid.

## macOS: Gatekeeper and “damaged” app

Releases are **not** always Apple-notarized. If you see *cannot be opened because the developer cannot be verified* or *Apple cannot check it for malware*:

1. In **Finder → Applications**, **right-click** `Sage.app` → **Open** → confirm **Open** in the dialog.
2. If still blocked: **System Settings → Privacy & Security** → find the Sage message → **Open Anyway**, then try again.
3. If the app is reported as **damaged** or will not start, clear quarantine and retry:

```bash
xattr -dr com.apple.quarantine /Applications/Sage.app
```

## Windows: SmartScreen

If **Windows SmartScreen** blocks the installer, use **More info** → **Run anyway** (wording can vary by Windows version).

## Linux: `.deb` install

On Debian / Ubuntu, after downloading the matching `.deb`:

```bash
sudo apt install ./Sage-<version>-<arch>.deb
```

Many desktop environments also support double-clicking the package.

## Build from source

From the repository root (see [full steps](../../../app/desktop/docs/installation.md) for environment setup):

```bash
# macOS / Linux
app/desktop/scripts/build.sh release
```

```powershell
# Windows
./app/desktop/scripts/build_windows.ps1 release
```

Artifacts and platform-specific notes are in the [installation guide](../../../app/desktop/docs/installation.md).

## See also

- [Getting Started](GETTING_STARTED.md) — also mentions desktop build at the end
- [Environment variables — Desktop & install](../ENV_VARS.md#8-desktop--install)

