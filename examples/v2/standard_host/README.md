# Sage v2 standard host

This reference uses only registrations, runtime selections, `build`, `load_agent`,
`entrypoint().run_stream`, `agent_for_run`, `continue_run`, and `close`.
Its deterministic model is a real registered model provider. File operations,
Shell, FFmpeg, Skill preloading, MCP transport and nested Team delegation execute
through Sage's standard implementation.

From the repository root, with Python 3.12+, FFmpeg and Pillow installed:

```bash
.venv/bin/python -m examples.v2.standard_host \
  --root /tmp/sage-v2-media-host \
  --command-path /opt/homebrew/bin:/bin:/usr/bin
```

Use an appropriate absolute command search path on your platform. The reference
requires native macOS Seatbelt or Linux bubblewrap support. The embedding host
must have permission to inspect its sandbox descendants; running it inside an
additional outer sandbox can prevent resource accounting. Such a failure is
reported as resource loss rather than being presented as successful isolation.

Success requires all three Runs to complete, all expected tools to succeed,
Run-owned leases to refer to one shared sandbox, and actual output files to
exist. A completed parent alone is insufficient. The workspace contains the
materialized media Skill, `standard-host.txt`, `media.mp4`, and the Pillow-generated `frame.png`.

The model plugin is for deterministic integration verification. For real work,
register a production model provider and select it in runtime configuration,
or use Sage's model catalog and credential declarations. Product-specific tools
belong in registered tool providers, not a custom execution driver.

## Restart

The first output line contains the durable Run ID. Reopen with the same state
root and registration versions:

```bash
.venv/bin/python -m examples.v2.standard_host \
  --root /tmp/sage-v2-media-host --recover RUN_ID \
  --command-path /opt/homebrew/bin:/bin:/usr/bin
```

The application restores archived Agent revisions and pending execution through
its standard dispatcher. An interaction-suspended Run still needs the normal
reply/resume command before `continue_run`. Uncertain external effects follow
their tool recovery contract; restarting never promises to repeat them safely.

## Packaging boundary

This checkout does not include a PyInstaller spec for this reference. The
commands above run from source. A frozen embedding host must supply its own
packaging configuration, include `mcp_server.py` and `skills/`, and configure
`--isolation-python` with a separately installed real CPython interpreter.

The example explicitly requests metered resource limits. Its diagnostics report
which limits the native provider actually enforces in the kernel; macOS resource
accounting must not be represented as hard limits.

## Application boundary

Desktop and Server register product capabilities and use the same standard App
execution path. Run this reference from current sources for SDK acceptance.
Product acceptance remains the responsibility of each embedding application.
