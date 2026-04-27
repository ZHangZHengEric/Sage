# Sage Terminal / CLI Contract

This document lists the CLI/runtime interfaces that `sage-terminal` treats as stable integration points.

## Integration Model

`sage-terminal` is a Rust client over the existing local Sage runtime.

There are two integration paths:

- chat / resume streaming through the existing backend event channel
- one-shot CLI commands for inspect/list/init/verify style operations

## Stable One-Shot JSON Commands

The TUI currently expects these commands to support structured JSON output:

- `sage doctor --json`
- `sage config show --json`
- `sage config init --json`
- `sage sessions --json`
- `sage sessions inspect <session_id|latest> --json`
- `sage skills --json`
- `sage provider list --json`
- `sage provider inspect <provider_id> --json`
- `sage provider verify --json`
- `sage provider create --json`
- `sage provider update <provider_id> --json`
- `sage provider delete <provider_id> --json`

## Stable Startup Entry Surface

The TUI startup layer currently aligns to these commands:

- `sage-terminal run <prompt>`
- `sage-terminal chat <prompt>`
- `sage-terminal config init [path] [--force]`
- `sage-terminal doctor [probe-provider]`
- `sage-terminal provider verify [key=value...]`
- `sage-terminal sessions [limit]`
- `sage-terminal sessions inspect <latest|session_id>`
- `sage-terminal resume [latest|session_id]`

## Contract Expectations

For one-shot JSON commands:

- stdout should be valid JSON when `--json` is used
- error reporting should remain machine-readable enough for the TUI to wrap cleanly
- human-readable formatting can change independently of the TUI

For streaming events:

- event type names should remain explicit
- fields such as `type`, `role`, `content`, `tool_calls`, and `metadata.tool_name` should remain stable or be evolved compatibly

## Change Policy

If one of these contracts must change:

1. change the CLI/runtime contract intentionally
2. update `app/terminal/src/backend/contract.rs`
3. update Rust-side tests
4. update Python-side JSON contract tests
5. update this document if the surface area changed
