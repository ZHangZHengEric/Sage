#!/usr/bin/env sh

set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
BUNDLE_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)

platform_tag() {
  system=$(uname -s | tr '[:upper:]' '[:lower:]')
  machine=$(uname -m | tr '[:upper:]' '[:lower:]')

  case "$system" in
    darwin) system=macos ;;
  esac

  case "$machine" in
    amd64) machine=x86_64 ;;
  esac

  printf '%s-%s\n' "$system" "$machine"
}

first_existing_executable() {
  for candidate in "$@"; do
    if [ -x "$candidate" ]; then
      printf '%s\n' "$candidate"
      return
    fi
  done
  printf '\n'
}

resolve_terminal_bin() {
  if [ -n "${SAGE_TERMINAL_BIN:-}" ]; then
    printf '%s\n' "$SAGE_TERMINAL_BIN"
    return
  fi

  tag=$(platform_tag)
  first_existing_executable \
    "$BUNDLE_ROOT/bin/$tag/sage-terminal" \
    "$BUNDLE_ROOT/bin/sage-terminal"
}

resolve_runtime_root() {
  if [ -n "${SAGE_TERMINAL_RUNTIME_ROOT:-}" ]; then
    printf '%s\n' "$SAGE_TERMINAL_RUNTIME_ROOT"
    return
  fi

  if [ -f "$BUNDLE_ROOT/runtime/app/cli/main.py" ]; then
    printf '%s\n' "$BUNDLE_ROOT/runtime"
    return
  fi

  if [ -f "$BUNDLE_ROOT/share/sage/app/cli/main.py" ]; then
    printf '%s\n' "$BUNDLE_ROOT/share/sage"
    return
  fi

  if [ -f "$BUNDLE_ROOT/../../app/cli/main.py" ]; then
    CDPATH= cd -- "$BUNDLE_ROOT/../.." && pwd
    return
  fi

  printf '\n'
}

set_if_missing() {
  key=$1
  value=$2
  if [ -n "$value" ]; then
    eval "current=\${$key:-}"
    if [ -z "$current" ]; then
      export "$key=$value"
    fi
  fi
}

first_existing_file() {
  for candidate in "$@"; do
    if [ -f "$candidate" ]; then
      printf '%s\n' "$candidate"
      return
    fi
  done
  printf '\n'
}

runtime_root=$(resolve_runtime_root)
set_if_missing "SAGE_TERMINAL_RUNTIME_ROOT" "$runtime_root"
TERMINAL_BIN=$(resolve_terminal_bin)

if [ -n "$runtime_root" ]; then
  bundled_cli=$(first_existing_file \
    "$runtime_root/.venv/bin/sage" \
    "$runtime_root/bin/sage" \
    "$runtime_root/python/bin/sage" \
    "$runtime_root/.sage_py_env/bin/sage")
  set_if_missing "SAGE_TERMINAL_CLI" "$bundled_cli"

  bundled_python=$(first_existing_file \
    "$runtime_root/.venv/bin/python3" \
    "$runtime_root/.venv/bin/python" \
    "$runtime_root/bin/python3" \
    "$runtime_root/bin/python" \
    "$runtime_root/python/bin/python3" \
    "$runtime_root/python/bin/python" \
    "$runtime_root/.sage_py_env/bin/python3" \
    "$runtime_root/.sage_py_env/bin/python")
  set_if_missing "SAGE_PYTHON" "$bundled_python"
fi

if [ -z "${SAGE_TERMINAL_STATE_ROOT:-}" ] && [ -d "$BUNDLE_ROOT/state" ] && [ -w "$BUNDLE_ROOT/state" ]; then
  export SAGE_TERMINAL_STATE_ROOT="$BUNDLE_ROOT/state/terminal-state"
fi

if [ "${SAGE_TERMINAL_DEBUG_LAUNCH:-0}" = "1" ]; then
  printf 'SAGE_TERMINAL_BIN=%s\n' "$TERMINAL_BIN"
  printf 'SAGE_TERMINAL_RUNTIME_ROOT=%s\n' "${SAGE_TERMINAL_RUNTIME_ROOT:-}"
  printf 'SAGE_TERMINAL_CLI=%s\n' "${SAGE_TERMINAL_CLI:-}"
  printf 'SAGE_PYTHON=%s\n' "${SAGE_PYTHON:-}"
  printf 'SAGE_TERMINAL_STATE_ROOT=%s\n' "${SAGE_TERMINAL_STATE_ROOT:-}"
fi

if [ -z "$TERMINAL_BIN" ] || [ ! -x "$TERMINAL_BIN" ]; then
  printf 'sage-terminal binary was not found. Set SAGE_TERMINAL_BIN or install a bundle with bin/<platform>/sage-terminal.\n' >&2
  exit 127
fi

exec "$TERMINAL_BIN" "$@"
