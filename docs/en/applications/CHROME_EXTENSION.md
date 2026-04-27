---
layout: default
title: Chrome Extension
parent: Applications
nav_order: 6
description: "Load the Sage browser extension and connect it to a local desktop or server backend"
lang: en
ref: chrome-extension
---

{% include lang_switcher.html %}

# Chrome Extension (Browser Bridge)

The **Chrome extension** under `app/chrome-extension/` is a **browser bridge**: it talks to a running Sage **Desktop** (or compatible local API) from the **Side Panel**, sends page context to the agent, and can execute simple browser actions from a command queue.

It is not a replacement for the full **Web** app (`app/server` + browser at port 5173/8080) — it is a **lightweight sidecar** for people who work in Chrome next to a local Sage backend.

**Canonical technical README (repo):** [app/chrome-extension/README.md](https://github.com/ZHangZHengEric/Sage/blob/main/app/chrome-extension/README.md)

## What it does (summary)

- Chat in the **Side Panel** (streams to the backend, e.g. desktop `/api/web-stream` when configured).
- Detects whether a local Sage service is up before allowing chat.
- Reports page context: title, URL, selection, short body summary.
- Polls a **browser command queue** and runs actions in the active tab (navigate, click, fill, script, etc.) when the agent requests them.

## Load unpacked (development)

1. Open `chrome://extensions/`.
2. Turn on **Developer mode** (top right).
3. **Load unpacked** and select the directory: `app/chrome-extension` (the folder that contains the extension `manifest`).

## Point it at your backend

By default the extension tries common local URLs, including:

- `http://127.0.0.1:8000` / `http://localhost:8000`
- `http://127.0.0.1:8080` / `http://localhost:8080`

If your API runs on a different host/port, set it in the **extension popup** and save.

## Use the Side Panel

Click the Sage icon in the toolbar; Chrome opens the **Side Panel** in split view so you can chat while browsing.

## See also

- [Architecture — other app entries](../architecture/ARCHITECTURE_APP_OTHERS.md) (Chrome extension section)
- [Desktop](DESKTOP.md) — extension is usually used **with** a running desktop backend
- [Web](WEB.md) — full browser product and Docker/server workflows
