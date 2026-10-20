# Command and terminal clients

- `cli/`: Public `sage` dispatch and terminal launcher; no agent implementation.
- `terminal/`: Rust terminal UI, with separate v1 and v2 protocol adapters.

Application commands live in `app/v1/cli` and `app/v2/cli`. Use `sage run`,
`sage chat`, `sage sessions`, and `sage tui` for the default runtime (v2).
`sage v1 run` and `sage tui --runtime v1` explicitly select the legacy runtime.
The explicit `sage v2` command group is also available.
The source module entry point is `python -m app.clients.cli.main`.
