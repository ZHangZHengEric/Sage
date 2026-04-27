# Sage Terminal Runtime / Distribution Notes

This document describes the current runtime-resolution rules for `sage-terminal`.

It does not introduce a packaged installer yet. It defines the compatibility layer that future bundle or installer work should follow.

Related documents:

- [BUNDLE_LAYOUT.md](./BUNDLE_LAYOUT.md)
- launcher wrapper: `scripts/run-sage-terminal.sh`
- smoke script: `scripts/smoke-runtime-distribution.sh`

## Runtime Resolution

`sage-terminal` currently resolves the Sage backend runtime in this order:

1. `SAGE_TERMINAL_RUNTIME_ROOT`
2. bundled/runtime-adjacent layouts relative to the current executable
3. the current Sage checkout inferred from `CARGO_MANIFEST_DIR`

A valid runtime root is any directory that contains:

- `app/cli/main.py`

## CLI Resolution

The Sage backend entrypoint used by the TUI is resolved in this order:

1. `SAGE_TERMINAL_CLI`
2. bundled `sage` executable candidates under the runtime root
3. Python module fallback via `python -m app.cli.main`

This keeps source checkouts working while allowing future bundles or wrapper launchers to provide a stable `sage` command without changing TUI code.

## Python Resolution

When the TUI falls back to Python module execution, the interpreter is resolved in this order:

1. `SAGE_PYTHON`
2. `PYTHON`
3. bundled interpreter candidates under the runtime root
4. fallback to `python3`

Bundled interpreter candidates currently include layouts such as:

- `.venv/bin/python3`
- `.venv/bin/python`
- `bin/python3`
- `bin/python`
- `python/bin/python3`
- `python/bin/python`
- `.sage_py_env/bin/python3`
- `.sage_py_env/bin/python`

## State Root Resolution

The TUI state root is resolved in this order:

1. `SAGE_TERMINAL_STATE_ROOT`
2. `<runtime_root>/.sage-terminal-state` when the runtime root looks like a source checkout (`.git/` exists)
3. `~/.sage/terminal-state`
4. fallback to `<runtime_root>/.sage-terminal-state`

This keeps source development behavior unchanged while avoiding writes into a read-only packaged runtime layout.

## Workspace Resolution

The TUI default workspace is now based on the current working directory, not the compiled repo path.

This affects:

- chat requests launched from the TUI
- workspace skill discovery
- the directory label shown in the welcome banner

## Packaging Direction

The current runtime resolution is intentionally compatible with a future bundle layout such as:

```text
sage-terminal-bundle/
  bin/
    sage-terminal
  runtime/
    app/
      cli/
        main.py
    .venv/
      bin/
        python3
        sage
```

or:

```text
sage-terminal-bundle/
  bin/
    sage-terminal
  share/
    sage/
      app/
        cli/
          main.py
      .sage_py_env/
        bin/
          python3
          sage
```

## Current Scope

This is only the first runtime/distribution step.

Still out of scope:

- installer generation
- release bundling automation
- npm / brew packaging
- shipping an embedded Python environment in CI

## Launcher And Smoke Helpers

The repository now includes:

- `scripts/run-sage-terminal.sh`
  - a minimal launcher contract for future bundles
  - normalizes `SAGE_TERMINAL_RUNTIME_ROOT`, `SAGE_TERMINAL_CLI`, `SAGE_PYTHON`, and optional bundle-local state
- `scripts/smoke-runtime-distribution.sh`
  - a release-facing smoke script
  - validates explicit overrides, bundled `sage`, and bundled Python fallback behavior
