# Sage Terminal Bundle Layout

This document defines the current bundle contract for `sage-terminal`.

It does not mean Sage Terminal is already shipped as a packaged release.
It defines the layout and launcher expectations that future packaging work should follow.

## Target Layout

The preferred portable bundle layout is:

```text
sage-terminal-bundle/
  bin/
    sage-terminal
    run-sage-terminal
  runtime/
    app/
      cli/
        main.py
    .venv/
      bin/
        python3
        sage
  state/
```

An alternative layout may place the runtime under:

```text
sage-terminal-bundle/
  bin/
    sage-terminal
    run-sage-terminal
  share/
    sage/
      app/
        cli/
          main.py
      .sage_py_env/
        bin/
          python3
          sage
  state/
```

## Directory Roles

`bin/`

- contains the Rust TUI binary
- contains the optional launcher wrapper
- should not contain writable runtime state

`runtime/` or `share/sage/`

- contains the Sage Python runtime
- contains built-in skills
- may contain a bundled `sage` CLI and/or Python interpreter
- should be treated as read-only at runtime

`state/`

- is an optional writable directory for portable bundles
- when present and writable, the launcher should point `SAGE_TERMINAL_STATE_ROOT` at `state/terminal-state`
- when absent, the runtime falls back to `~/.sage/terminal-state`

## Launcher Contract

The launcher should:

1. discover the bundle root relative to itself
2. prefer `runtime/` as `SAGE_TERMINAL_RUNTIME_ROOT`
3. fall back to `share/sage/` if `runtime/` is absent
4. set `SAGE_TERMINAL_CLI` when a bundled `sage` executable exists
5. otherwise set `SAGE_PYTHON` when a bundled Python exists
6. set `SAGE_TERMINAL_STATE_ROOT` to the bundle-local `state/terminal-state` only when `state/` exists and is writable
7. leave any explicitly supplied env overrides untouched

The launcher should not embed business logic from Sage itself. It should only normalize runtime discovery for packaged layouts.

## Binary Contract

The Rust TUI binary remains:

- `bin/sage-terminal`

The wrapper launcher is expected to be:

- `bin/run-sage-terminal`

Packaging may later rename the wrapper to the user-facing entrypoint, but the internal separation should stay explicit:

- one binary
- one launcher
- one runtime root
- one optional writable state root

## Current Recommendation

Until official packaging exists, this layout should be treated as the source of truth for:

- future bundle assembly
- installer integration
- launcher behavior
- release smoke checks
