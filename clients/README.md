# Command and terminal clients

- `cli/`: Public `sage` dispatch and terminal launcher; no agent implementation.
- `terminal/`: Rust terminal UI, with separate v1 and v2 protocol adapters.

Application commands live in `app/v1/cli` and `app/v2/cli`. `sage run` uses v1;
`sage v2 run` uses v2; `sage tui --runtime v2` launches the terminal for v2.
The source module entry point is `python -m clients.cli.main`.
