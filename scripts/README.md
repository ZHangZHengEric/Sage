# Repository scripts

| Directory | Purpose |
| --- | --- |
| `checks/` | Architecture, localization and local task smoke checks |
| `dev/` | Developer setup, including Git hooks |
| `maintenance/` | Runtime-data cleanup; defaults to dry-run, deletion requires `--apply` |
| `release/` | Release metadata generation |
| `v1/` | Legacy dev startup, memory validation and benchmarks |
| `v1/diagnostics/` | Offline legacy diagnostics; some compare historical Git objects |
| `v2/` | Offline v2 benchmarks |

Run from the repository root with `.venv/bin/python`. Legacy diagnostics also
require `PYTHONPATH=.`. Examples:

```bash
.venv/bin/python scripts/checks/check_architecture.py
cargo build --manifest-path app/clients/terminal/Cargo.toml
.venv/bin/python scripts/checks/smoke_cli_tui.py
PYTHONPATH=. .venv/bin/python scripts/v1/diagnostics/mock_stream_latency.py --requests 1 --chunks 20
.venv/bin/python scripts/v2/benchmark_v2_context.py --messages 20 --sessions 2
.venv/bin/python scripts/maintenance/cleanup_llm_request_dirs.py --help
```

`v1/dev-up.sh` starts development services; it is not a validation script.
`dev/install-git-hooks.sh` modifies local Git configuration. The historical ledger
benchmark requires commit `284abc7f` in the local Git history; shallow clones may
not contain it. Application-specific build scripts remain beside their application.
