#!/bin/sh
set -eu

dist_url="$1"
checksum_url="$2"
shift 2

dist_dir="${SAGE_DIST_DIR:-/usr/share/nginx/html}"
archive_file="/tmp/sage-dist.tgz"
checksum_file="/tmp/sage-dist.sha256"

wget -qO "$archive_file" "$dist_url"
wget -qO "$checksum_file" "$checksum_url"

expected_sha="$(awk '{print $1}' "$checksum_file")"
actual_sha="$(sha256sum "$archive_file" | awk '{print $1}')"
if [ "$expected_sha" != "$actual_sha" ]; then
  echo "dist checksum mismatch: expected $expected_sha, got $actual_sha" >&2
  exit 1
fi

mkdir -p "$dist_dir"
find "$dist_dir" -mindepth 1 -maxdepth 1 -exec rm -rf {} +
tar -xzf "$archive_file" -C "$dist_dir"

if [ ! -f "$dist_dir/index.html" ]; then
  echo "dist archive does not contain index.html" >&2
  exit 1
fi

exec "$@"
