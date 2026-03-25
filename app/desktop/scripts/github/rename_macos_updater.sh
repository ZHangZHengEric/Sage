#!/usr/bin/env bash
set -euo pipefail

if [ $# -ne 1 ]; then
    echo "Usage: $0 <arch>"
    exit 1
fi

ARCH="$1"
VERSION="${GITHUB_REF#refs/tags/desktop-v}"
TARGET_DIR="app/desktop/tauri/target/release/bundle/macos"
TARGET_NAME="Sage_${VERSION}_${ARCH}.app.tar.gz"

shopt -s nullglob
cd "$TARGET_DIR"

for file in *.tar.gz; do
    if [ "$file" != "$TARGET_NAME" ]; then
        mv "$file" "$TARGET_NAME"
    fi
done

for file in *.tar.gz.sig; do
    if [ "$file" != "${TARGET_NAME}.sig" ]; then
        mv "$file" "${TARGET_NAME}.sig"
    fi
done
