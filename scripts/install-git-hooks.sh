#!/usr/bin/env sh
set -eu

repo_root="$(git rev-parse --show-toplevel)"
git -C "$repo_root" config core.hooksPath .githooks
echo "Git hooks installed: core.hooksPath=.githooks"
