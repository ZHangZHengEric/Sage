#!/bin/sh
set -eu

sessions_root="sessions"
days="7"
apply="0"
max_list="200"

usage() {
  cat <<'EOF'
Usage: cleanup_llm_request_dirs.sh [options]

Options:
  --sessions-root PATH  Sessions root to scan (default: ./sessions)
  --days N              Delete llm_request dirs older than N days (default: 7)
  --apply               Actually delete matched dirs. Default is dry-run.
  --max-list N          Max rows to print (default: 200; 0 = all)
  -h, --help            Show help
EOF
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --sessions-root)
      sessions_root="${2:?missing value for --sessions-root}"
      shift 2
      ;;
    --days)
      days="${2:?missing value for --days}"
      shift 2
      ;;
    --apply)
      apply="1"
      shift
      ;;
    --max-list)
      max_list="${2:?missing value for --max-list}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "[ERROR] unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

case "$days" in
  ''|*[!0-9]*)
    echo "[ERROR] --days must be a positive integer" >&2
    exit 2
    ;;
esac

case "$max_list" in
  ''|*[!0-9]*)
    echo "[ERROR] --max-list must be a non-negative integer" >&2
    exit 2
    ;;
esac

if [ "$days" -le 0 ]; then
  echo "[ERROR] --days must be greater than 0" >&2
  exit 2
fi

if [ ! -d "$sessions_root" ]; then
  echo "[ERROR] sessions root not found: $sessions_root" >&2
  exit 1
fi

abs_sessions_root="$(cd "$sessions_root" && pwd -P)"

now="$(date +%s)"
cutoff="$((now - days * 24 * 60 * 60))"

stat_mtime() {
  if stat -f %m "$1" >/dev/null 2>&1; then
    stat -f %m "$1"
  else
    stat -c %Y "$1"
  fi
}

format_time() {
  if date -r "$1" '+%Y-%m-%d %H:%M:%S' >/dev/null 2>&1; then
    date -r "$1" '+%Y-%m-%d %H:%M:%S'
  else
    date -d "@$1" '+%Y-%m-%d %H:%M:%S'
  fi
}

dir_size_bytes() {
  if du -sk "$1" >/dev/null 2>&1; then
    set -- $(du -sk "$1")
    echo $(($1 * 1024))
  else
    echo 0
  fi
}

format_bytes() {
  awk -v size="$1" '
    BEGIN {
      split("B KiB MiB GiB TiB", units, " ");
      value = size + 0;
      unit = 1;
      while (value >= 1024 && unit < 5) {
        value /= 1024;
        unit++;
      }
      if (unit == 1) {
        printf "%d B", value;
      } else {
        printf "%.1f %s", value, units[unit];
      }
    }
  '
}

tmp_file="$(mktemp "${TMPDIR:-/tmp}/sage-llm-request-cleanup.XXXXXX")"
trap 'rm -f "$tmp_file"' EXIT INT TERM

# The runtime writes llm_request directly under each session_workspace. Parent
# sessions can contain nested sub_sessions, so scan recursively.
find "$abs_sessions_root" -type d -name llm_request -prune | while IFS= read -r dir; do
  if [ -L "$dir" ]; then
    continue
  fi
  mtime="$(stat_mtime "$dir")"
  if [ "$mtime" -lt "$cutoff" ]; then
    size="$(dir_size_bytes "$dir")"
    rel="${dir#"$abs_sessions_root"/}"
    printf '%s\t%s\t%s\n' "$mtime" "$size" "$rel" >> "$tmp_file"
  fi
done

matched="$(wc -l < "$tmp_file" | tr -d ' ')"
total_size="$(awk -F '\t' '{ total += $2 } END { print total + 0 }' "$tmp_file")"
mode="DRY-RUN"
if [ "$apply" = "1" ]; then
  mode="APPLY"
fi

echo "[$mode] sessions_root=$abs_sessions_root"
echo "[$mode] cutoff=$(format_time "$cutoff") (${days} days)"
echo "[$mode] matched=$matched, total_size=$(format_bytes "$total_size")"

printed="0"
sort -n "$tmp_file" | while IFS="$(printf '\t')" read -r mtime size rel; do
  if [ "$max_list" -ne 0 ] && [ "$printed" -ge "$max_list" ]; then
    continue
  fi
  printf '%s  %10s  %s\n' "$(format_time "$mtime")" "$(format_bytes "$size")" "$rel"
  printed=$((printed + 1))
done

if [ "$max_list" -ne 0 ] && [ "$matched" -gt "$max_list" ]; then
  echo "... $((matched - max_list)) more not shown"
fi

if [ "$apply" != "1" ]; then
  echo "[DRY-RUN] no files deleted; rerun with --apply to delete matches"
  exit 0
fi

deleted="0"
failed="0"
sort -n "$tmp_file" | while IFS="$(printf '\t')" read -r _mtime _size rel; do
  target="$abs_sessions_root/$rel"
  if rm -rf "$target"; then
    deleted=$((deleted + 1))
  else
    failed=$((failed + 1))
    echo "[ERROR] failed to delete $target" >&2
  fi
  echo "$deleted $failed" > "$tmp_file.count"
done

if [ -f "$tmp_file.count" ]; then
  set -- $(cat "$tmp_file.count")
  deleted="$1"
  failed="$2"
  rm -f "$tmp_file.count"
fi

echo "[APPLY] deleted=$deleted, failed=$failed"
if [ "$failed" -gt 0 ]; then
  exit 1
fi
