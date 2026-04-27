#!/usr/bin/env sh

set -eu

REPO_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../../.." && pwd)
TERMINAL_DIR="$REPO_ROOT/app/terminal"
BINARY_PATH="$TERMINAL_DIR/target/release/sage-terminal"
WORK_DIR=$(mktemp -d "${TMPDIR:-/tmp}/sage-terminal-smoke.XXXXXX")
WORK_DIR=$(CDPATH= cd -- "$WORK_DIR" && pwd)
trap 'rm -rf "$WORK_DIR"' EXIT

if [ ! -x "$BINARY_PATH" ]; then
  cargo build --release --manifest-path "$TERMINAL_DIR/Cargo.toml" >/dev/null
fi

BUNDLE_ROOT="$WORK_DIR/bundle"
mkdir -p "$BUNDLE_ROOT/bin" "$BUNDLE_ROOT/runtime/app/cli" "$BUNDLE_ROOT/state"
cp "$BINARY_PATH" "$BUNDLE_ROOT/bin/sage-terminal"
cp "$TERMINAL_DIR/scripts/run-sage-terminal.sh" "$BUNDLE_ROOT/bin/run-sage-terminal"
chmod +x "$BUNDLE_ROOT/bin/run-sage-terminal"

printf '# stub\n' >"$BUNDLE_ROOT/runtime/app/cli/main.py"

run_debug() {
  env SAGE_TERMINAL_DEBUG_LAUNCH=1 "$BUNDLE_ROOT/bin/run-sage-terminal" --help
}

assert_contains() {
  haystack=$1
  needle=$2
  if ! printf '%s\n' "$haystack" | grep -F "$needle" >/dev/null; then
    printf 'missing expected line: %s\n' "$needle" >&2
    exit 1
  fi
}

assert_not_contains() {
  haystack=$1
  needle=$2
  if printf '%s\n' "$haystack" | grep -F "$needle" >/dev/null; then
    printf 'unexpected line: %s\n' "$needle" >&2
    exit 1
  fi
}

explicit_cli="$WORK_DIR/tools/explicit-sage"
explicit_python="$WORK_DIR/tools/explicit-python"
mkdir -p "$WORK_DIR/tools"
: >"$explicit_cli"
: >"$explicit_python"
chmod +x "$explicit_cli" "$explicit_python"

scenario_one=$(
  env \
    SAGE_TERMINAL_RUNTIME_ROOT="$WORK_DIR/explicit-runtime" \
    SAGE_TERMINAL_CLI="$explicit_cli" \
    SAGE_PYTHON="$explicit_python" \
    SAGE_TERMINAL_STATE_ROOT="$WORK_DIR/explicit-state" \
    SAGE_TERMINAL_BIN="$BUNDLE_ROOT/bin/sage-terminal" \
    SAGE_TERMINAL_DEBUG_LAUNCH=1 \
    "$BUNDLE_ROOT/bin/run-sage-terminal" --help
)
assert_contains "$scenario_one" "SAGE_TERMINAL_RUNTIME_ROOT=$WORK_DIR/explicit-runtime"
assert_contains "$scenario_one" "SAGE_TERMINAL_CLI=$explicit_cli"
assert_contains "$scenario_one" "SAGE_PYTHON=$explicit_python"
assert_contains "$scenario_one" "SAGE_TERMINAL_STATE_ROOT=$WORK_DIR/explicit-state"

mkdir -p "$BUNDLE_ROOT/runtime/.venv/bin"
: >"$BUNDLE_ROOT/runtime/.venv/bin/sage"
chmod +x "$BUNDLE_ROOT/runtime/.venv/bin/sage"

scenario_two=$(run_debug)
assert_contains "$scenario_two" "SAGE_TERMINAL_RUNTIME_ROOT=$BUNDLE_ROOT/runtime"
assert_contains "$scenario_two" "SAGE_TERMINAL_CLI=$BUNDLE_ROOT/runtime/.venv/bin/sage"
assert_contains "$scenario_two" "SAGE_TERMINAL_STATE_ROOT=$BUNDLE_ROOT/state/terminal-state"

rm -f "$BUNDLE_ROOT/runtime/.venv/bin/sage"
: >"$BUNDLE_ROOT/runtime/.venv/bin/python3"
chmod +x "$BUNDLE_ROOT/runtime/.venv/bin/python3"

scenario_three=$(run_debug)
assert_contains "$scenario_three" "SAGE_TERMINAL_RUNTIME_ROOT=$BUNDLE_ROOT/runtime"
assert_contains "$scenario_three" "SAGE_PYTHON=$BUNDLE_ROOT/runtime/.venv/bin/python3"
assert_contains "$scenario_three" "SAGE_TERMINAL_STATE_ROOT=$BUNDLE_ROOT/state/terminal-state"
assert_contains "$scenario_three" "SAGE_TERMINAL_CLI="

printf 'runtime/distribution smoke checks passed\n'
