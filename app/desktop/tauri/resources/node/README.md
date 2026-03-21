Place the full Node.js runtime for the target platform in this directory before building the desktop app.

The desktop build scripts now auto-populate this directory with a minimal runtime before `tauri build`:
- macOS/Linux: `bin/node` plus `lib/node_modules/npm`
- Windows: `node.exe` plus `node_modules/npm`

If you want to override that source, set `SAGE_BUNDLED_NODE_SOURCE` to a prepared runtime directory in one of the layouts below.

Recommended layouts that the Tauri runtime code supports:

1. Extract a Unix/macOS tarball here so the directory contains:
   - `bin/node`
   - `bin/npm`
   - `bin/npx`
   - `lib/node_modules/npm/bin/npm-cli.js`

2. Extract a Windows zip here so the directory contains:
   - `node.exe`
   - `npm.cmd`
   - `npx.cmd`
   - `node_modules/npm/bin/npm-cli.js`

Notes:

- The app now prefers this bundled runtime and falls back to system `npm` if it is not present.
- Bundling Node solves the "new machine has no Node" problem, but it does not make preset package installation fully offline by itself.
- If you want first launch to be fully offline, you also need to prebundle the required npm packages or a prepared `.sage_node_env`.
