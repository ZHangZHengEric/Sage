# Command and terminal clients

- `cli/`: Public `sage` dispatch and terminal launcher; no agent implementation.
- `terminal/`: Rust terminal UI, with separate v1 and v2 protocol adapters.

Application commands live in `app/v1/cli` and `app/v2/cli`. `sage run` and `sage tui` default to v2. `sage v2 run` also selects v2;
`sage v1 run` and `sage tui --runtime v1` explicitly select v1.
The source module entry point is `python -m app.clients.cli.main`.
