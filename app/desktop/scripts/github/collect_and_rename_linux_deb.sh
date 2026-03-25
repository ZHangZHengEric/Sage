#!/usr/bin/env bash
set -euo pipefail

if [ $# -ne 2 ]; then
    echo "Usage: $0 <arch> <deb_dir>"
    exit 1
fi

ARCH="$1"
DEB_DIR="$2"
VERSION="${GITHUB_REF#refs/tags/desktop-v}"

mkdir -p release-assets/linux
cp "$DEB_DIR"/*.deb release-assets/linux/

for file in release-assets/linux/*.deb; do
    mv "$file" "release-assets/linux/Sage_${VERSION}_${ARCH}.deb"
done
