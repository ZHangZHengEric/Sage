# Sage Terminal Boundary

`sage-terminal` is a terminal-first frontend for Sage. It is not a second Sage runtime.

This document defines what belongs in the Rust TUI layer and what must remain in the CLI/runtime layer.

## TUI Responsibilities

The Rust TUI owns:

- terminal rendering
- input editing and cursor behavior
- popup / overlay / picker interaction
- startup routing for `sage-terminal ...`
- transcript presentation
- local UI state
- mapping structured backend results into terminal-friendly output

The TUI may add convenience entrypoints, but it should not invent new backend behavior.

## CLI / Runtime Responsibilities

The Sage CLI/runtime owns:

- agent orchestration
- provider verification and persistence
- config inspection and config file creation
- session storage and session inspection
- skill discovery and validation
- doctor diagnostics
- backend event generation and JSON schemas

If behavior changes in any of those areas, it should be implemented in the CLI/runtime first and only surfaced through the TUI second.

## Hard Rules

1. The TUI should prefer structured results over human-readable CLI text.
2. The TUI should not parse presentation-oriented stdout when a JSON contract is available.
3. New non-interactive entrypoints should be added to the CLI/runtime first, then exposed through `sage-terminal`.
4. TUI-only state must stay UI-local. Business state must stay in the runtime.

## What The TUI Currently Depends On

The current TUI contract surface includes:

- `doctor --json`
- `config show --json`
- `config init --json`
- `sessions --json`
- `sessions inspect --json`
- `skills --json`
- `provider list --json`
- `provider inspect --json`
- `provider verify --json`
- `provider create --json`
- `provider update --json`
- `provider delete --json`
- chat/resume streaming events over the existing runtime channel

## What Should Not Be Added To The TUI

Avoid moving these concerns into Rust TUI code:

- provider business rules
- config template logic
- doctor probe implementation
- session persistence logic
- skill resolution logic
- runtime-specific error classification that the CLI can define directly

## Practical Review Guideline

For future PRs:

- if a change only affects rendering or interaction, it belongs in `app/terminal`
- if a change affects runtime meaning or data shape, it belongs in `app/cli` / runtime first
- if the TUI needs a new capability, prefer adding a stable CLI/JSON contract instead of special-casing UI logic
