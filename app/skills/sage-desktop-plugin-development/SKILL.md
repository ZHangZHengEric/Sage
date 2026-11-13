---
name: sage-desktop-plugin-development
description: Create, validate, and register custom HTML, CSS, and JavaScript panels in Sage Desktop. Use when asked to build or update a Desktop plugin.
---

# Sage Desktop plugin development

Start from the [task list](assets/example/manifest.json) or the [project data panel](assets/project-data/manifest.json) and use [the manifest schema](assets/manifest.schema.json). Build in the current workspace. Package `manifest.json`, the HTML entry and local assets in a ZIP with the manifest at the root. Include a distinctive static square PNG logo, ideally 256 × 256 px (64–512 px, at most 256 KiB), and set `logo` to its package-relative path. Keep `icon` as the native glyph for the sidebar and tabs. Keep paths relative, scripts and styles in separate bundled files, and avoid browser navigation, remote scripts and package installation at runtime. Preserve the plugin ID and increase the numeric version on updates. The host supplies the title, navigation, theme CSS and JavaScript SDK. Use concise visible labels and check both themes.

When the user asks to add or update the plugin, call `register_desktop_plugin` once with `package_path` set to the workspace-relative ZIP path. The tool validates the package before registration. If validation fails, fix the reported issue and retry. Successful registration adds the plugin to Desktop Plugins and opens it in the requesting window. Report the returned ID and version. If the result is uncertain, retry with the same ID, version and contents to reconcile without reopening the panel. If the user wants to install the package manually, give them the ZIP and point them to Desktop Plugins → Upload Plugin.

To modify an installed plugin in a new chat, call `list_desktop_plugins` to find its exact ID and current version. Call `download_desktop_plugin` with that `plugin_id` and an unused workspace-relative ZIP `destination_path`. Inspect or unpack the ZIP in the workspace, make the changes, keep the ID and increase the version, then register the new ZIP. The downloaded package contains the original bundled files, including the logo.

Use `await sageDesktop.ready`, then `await sageDesktop.call(method, params)`. Requests use protocol version 1. Listen for `sage:environment` to observe theme, locale and visibility. The host styles native controls using `--sage-surface`, `--sage-text`, `--sage-control`, `--sage-border` and `--sage-primary`.

- `storage.get`, `storage.set`, `storage.delete` accept `{key}` or `{key, value}`. Values are JSON. `notify` accepts `{message}`.
- `context.read` provides the current workspace and session identifiers and workspace name. Declare `context`.
- `file.read` opens the native file picker and returns `{name, base64}` or null. Declare `file.read`.
- `file.export` accepts `{name, base64}` and opens the native save dialog. Declare `file.export`.
- `draft.insert` accepts `{text}` and appends to the current composer. Declare `draft`.
- `https.request` accepts `{endpoint, body}`. Declare `https` and name each endpoint in the manifest with its exact HTTPS URL and method. The host returns `{status, body}`. For a bearer-protected endpoint, set `"auth": "bearer"` on the endpoint. The user enters the token in a native dialog. Sage keeps it in the running sidecar and injects it only for that declared endpoint. Keep authorization headers and credentials out of the plugin package and its private storage.

Invoke capabilities from an explicit user action. Handle denial, cancellation and missing context as normal outcomes. Opening or restoring a panel should only initialize its view and read its private state.
