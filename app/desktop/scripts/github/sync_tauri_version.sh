#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
TAURI_CONFIG="$ROOT_DIR/app/desktop/tauri/tauri.conf.json"

if [[ "${GITHUB_REF:-}" != refs/tags/desktop-v* ]]; then
    echo "Skip Tauri version sync: current ref is not desktop-v tag (${GITHUB_REF:-unknown})."
    exit 0
fi

VERSION="${GITHUB_REF#refs/tags/desktop-v}"
echo "Syncing Tauri version to ${VERSION}"

TAURI_VERSION="$VERSION" TAURI_CONFIG_PATH="$TAURI_CONFIG" node - <<'EOF'
const fs = require('fs');
const configPath = process.env.TAURI_CONFIG_PATH || 'app/desktop/tauri/tauri.conf.json';
const version = process.env.TAURI_VERSION;
const config = JSON.parse(fs.readFileSync(configPath, 'utf8'));
config.version = version;
fs.writeFileSync(configPath, JSON.stringify(config, null, 2) + '\n');
EOF
