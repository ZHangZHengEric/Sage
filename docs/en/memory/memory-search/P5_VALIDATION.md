# Memory Search P5 Validation

This document captures the current P5 hardening and delivery scope for the memory-search workstream.

## Scope

P5 is focused on operational robustness and delivery polish on top of P1 through P4.

Current improvements include:

- `sage doctor` and `sage config show` now return structured diagnostics even when memory backend or strategy values are invalid
- invalid runtime choices are surfaced under:
  - `memory_backends.*`
  - `memory_strategies.*`
- `collect_config_info()` now reports memory-related environment sources:
  - `SAGE_SESSION_MEMORY_BACKEND`
  - `SAGE_FILE_MEMORY_BACKEND`
  - `SAGE_SESSION_MEMORY_STRATEGY`
- `sage config init` now writes commented optional memory-search overrides into the generated env template
- the unified validation entry now includes the CLI doctor/config regression suite

## Test Suite

Primary P5 regression suite:

```bash
python tests/app/cli/test_doctor_memory_backends.py
python scripts/memory_search_validate.py --noise-files 30 --top-k 2
```

Current coverage includes:

- doctor/config diagnostics for valid backend and strategy values
- doctor/config structured error handling for invalid backend and strategy values
- `env_sources` visibility for memory backend/strategy environment variables
- `sage config init` template coverage for commented memory-search override settings

## Recommended Validation

```bash
python -m py_compile app/cli/service.py tests/app/cli/test_doctor_memory_backends.py scripts/memory_search_validate.py
python tests/app/cli/test_doctor_memory_backends.py
python scripts/memory_search_validate.py --noise-files 30 --top-k 2
```

## Notes

- P5 does not change the external `search_memory` contract
- this stage is about making configuration, diagnostics, and local validation robust enough for submission

