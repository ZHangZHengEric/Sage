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

## Experimental: `sage v2 {run,chat,resume,sessions} --json` (SAgents v2 runtime)

`sage v2 run <task> --json` streams the v2 runtime's native `RuntimeEvent`s as NDJSON
(one JSON object per line, `protocol_version: "sage.runtime/v2"`). CLI framing lines are
interleaved and distinguished by a `cli_v2_` prefix on `type`:

- `cli_v2_session` — first line of a run: `session_id`, `run_id`, `agent_id`, `workspace`, `session_root`, `package_id`;
  `resumed: true` when the CLI is taking over a run left suspended by a previous process
- `cli_v2_interaction` — the run is suspended waiting for an answer: `interaction_id`,
  `interaction_type` (`approval` | `user_input` | ...), `allowed_decisions`, `payload`
- `cli_v2_notice` — human-readable notice
- `cli_v2_result` — last line of a run: `state` (`completed` | `failed` | `cancelled` | `suspended`),
  `interrupted` (true when the user cancelled it with Ctrl-C; process exit code 130), `final_text`, `error`

The driver answers a `cli_v2_interaction` by writing one JSON line to the CLI's stdin:

```json
{"type": "v2_interaction_decision", "interaction_id": "...", "decision": "approve_once", "payload": {}}
```

`decision` must be one of `allowed_decisions`; anything else is coerced to `deny`/`cancel`.
`payload` carries `{"text": "..."}` for `submit` / `change_direction` answers.

While a run is active (no interaction pending) the driver may append input for the next model step:

```json
{"type": "v2_steer", "text": "also update the tests"}
```

The CLI answers with `cli_v2_steer` (`status`: `accepted` | `rejected` | `unapplied`, `text`, `detail`).
`unapplied` is emitted at the end of a run for input that was accepted but never reached a next model
step; `sage v2 chat` then sends that text as the next message automatically. A decision
frame sent while no interaction is pending is reported as a rejected steer with
`detail: "no interaction is pending"`. In plain (non-JSON) mode steering is enabled only when stdin is
a terminal; lines piped into `sage v2 chat` are always treated as the next prompts.

`sage v2 sessions --json` is a one-shot command like `sage sessions --json`: it prints one JSON
object with `session_root`, `total`, `unreadable` (session ids whose state could not be read) and
`list` (newest first; each entry has `session_id`, `created_at`, `updated_at`, `run_count`,
`last_run_id`, `last_state`, `agent_id`, `task`, `workspace`, `package_id`).

`sage v2 sessions inspect <session_id> --json` prints one JSON object: `session` (the same entry
shape as the listing) and `runs` (in order; each with `run_id`, `state`, `invocation_mode`,
`created_at`, `updated_at` and `entries` — `{kind: user|assistant|tool|interaction, text, detail?}`
rebuilt from the session's durable events).

`sage v2 chat --json` and `sage v2 resume <session_id> --json` repeat the run framing per turn:
between turns the CLI reads one plain-text prompt line from stdin (`/exit` ends the session);
while a run is active, stdin lines are interpreted only as decision lines. Every turn after the
first reuses the `session_id` announced by the first `cli_v2_session` frame.

This surface is not yet consumed by `sage-terminal` and may change until the TUI integration lands.
