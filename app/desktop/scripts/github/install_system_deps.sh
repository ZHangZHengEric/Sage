#!/usr/bin/env bash
set -euo pipefail

PLATFORM="${1:-}"

case "$PLATFORM" in
  macos)
    brew install create-dmg
    ;;
  linux)
    sudo apt-get update
    sudo apt-get install -y \
      libgtk-3-dev \
      librsvg2-dev \
      patchelf \
      pkg-config \
      libssl-dev \
      libglib2.0-dev
    sudo apt-get install -y libwebkit2gtk-4.1-dev || sudo apt-get install -y libwebkit2gtk-4.0-dev
    sudo apt-get install -y libappindicator3-dev || sudo apt-get install -y libayatana-appindicator3-dev
    ;;
  *)
    echo "Unsupported platform: $PLATFORM"
    echo "Usage: $0 <macos|linux>"
    exit 1
    ;;
esac
