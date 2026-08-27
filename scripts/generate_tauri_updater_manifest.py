#!/usr/bin/env python3
"""Generate Tauri's static updater manifest from signed release assets."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from urllib.parse import quote


# Static updater contract:
# https://v2.tauri.app/plugin/updater/#static-json-file
PLATFORM_ASSETS = {
    "darwin-aarch64": "Sage-{version}-aarch64.app.tar.gz",
    "darwin-x86_64": "Sage-{version}-x86_64.app.tar.gz",
    "windows-x86_64": "Sage-{version}-x86_64-setup.exe",
}


def build_manifest(
    *, repo: str, tag: str, version: str, assets_dir: Path
) -> dict[str, object]:
    platforms: dict[str, dict[str, str]] = {}

    for platform, filename_template in PLATFORM_ASSETS.items():
        filename = filename_template.format(version=version)
        bundle_path = assets_dir / filename
        signature_path = assets_dir / f"{filename}.sig"

        if not bundle_path.is_file():
            raise ValueError(f"missing updater bundle for {platform}: {filename}")
        if not signature_path.is_file():
            raise ValueError(f"missing updater signature for {platform}: {filename}.sig")

        signature = signature_path.read_text(encoding="utf-8").strip()
        if not signature:
            raise ValueError(f"empty updater signature for {platform}: {filename}.sig")

        platforms[platform] = {
            "url": (
                f"https://github.com/{repo}/releases/download/"
                f"{quote(tag, safe='')}/{quote(filename, safe='')}"
            ),
            "signature": signature,
        }

    return {"version": version, "platforms": platforms}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--assets-dir", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    manifest = build_manifest(
        repo=args.repo,
        tag=args.tag,
        version=args.version,
        assets_dir=args.assets_dir,
    )
    args.output.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
