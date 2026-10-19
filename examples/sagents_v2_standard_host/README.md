# Sage v2 standard host

This reference uses only registrations, runtime selections, `build`, `load_agent`,
`entrypoint().run_stream`, `agent_for_run`, `continue_run`, and `close`.
Its deterministic model is a real registered model provider. File operations,
Shell, FFmpeg, Skill preloading, MCP transport and nested Team delegation execute
through Sage's standard implementation.

From the repository root, with FFmpeg installed:

```bash
.venv/bin/python -m examples.sagents_v2_standard_host \
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
.venv/bin/python -m examples.sagents_v2_standard_host \
  --root /tmp/sage-v2-media-host --recover RUN_ID \
  --command-path /opt/homebrew/bin:/bin:/usr/bin
```

The application restores archived Agent revisions and pending execution through
its standard dispatcher. An interaction-suspended Run still needs the normal
reply/resume command before `continue_run`. Uncertain external effects follow
their tool recovery contract; restarting never promises to repeat them safely.

## Frozen executable

```bash
PYINSTALLER_CONFIG_DIR=/tmp/sage-v2-pyinstaller-cache \
.venv/bin/pyinstaller --noconfirm \
  --distpath /tmp/sage-v2-dist --workpath /tmp/sage-v2-build \
  examples/sagents_v2_standard_host/host.spec

/tmp/sage-v2-dist/sage-v2-standard-host/sage-v2-standard-host \
  --root /tmp/sage-v2-frozen-host \
  --isolation-python /absolute/path/to/real/python3 \
  --command-path /absolute/path/to/media/bin:/bin:/usr/bin
```

The trusted isolation interpreter is independently validated CPython. It is
not the frozen host executable, and it does not determine which Python the
Agent Shell finds. Ship and configure real CPython and your media runtime
separately. Sage supplies its internal isolation launch protocol.

The example explicitly requests metered resource limits. Its diagnostics report
which limits the native provider actually enforces in the kernel; macOS resource
accounting must not be represented as hard limits.

## Application boundary

Desktop and Server register product capabilities and use the same standard App
execution path. Run this reference from current sources for SDK acceptance;
Yiii migration and its product acceptance tests are performed by Yiii itself.
