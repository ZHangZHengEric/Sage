# Memory Search Validation

This document is the combined validation entry for the current memory-search workstream.

Detailed phase notes remain in:

- `MEMORY_SEARCH_P1_VALIDATION.md`
- `MEMORY_SEARCH_P2_VALIDATION.md`
- `MEMORY_SEARCH_P3_VALIDATION.md`
- `MEMORY_SEARCH_P4_VALIDATION.md`
- `MEMORY_SEARCH_P5_VALIDATION.md`

## Scope

The current memory-search line is split into these layers:

- P1: search quality, ranking, preview quality, identifier/path-aware search
- P2: retriever-boundary stabilization for file memory vs session history
- P3: session-memory backend separation and factory wiring
- P4: backend/strategy configurability and CLI diagnostics
- P5: operational hardening for diagnostics, config templates, and unified validation

## Unified Validation Command

Run the combined suite:

```bash
python scripts/memory_search_validate.py
```

Useful variant:

```bash
python scripts/memory_search_validate.py --noise-files 300 --top-k 5
```

The combined validation runs:

- `py_compile` for the current memory-search implementation and test files
- `tests/test_memory_index_fts.py`
- `tests/test_memory_tool.py`
- `tests/sagents/context/test_session_memory_manager.py`
- `tests/app/cli/test_doctor_memory_backends.py`
- `scripts/memory_search_benchmark.py`

## Current Checkpoints

P1:

- `cac18b1f` `feat: improve memory search ranking quality`
- `cf569769` `test: expand memory search query coverage`
- `eb4bc953` `test: add memory search performance sanity cases`
- `bed40c1d` `docs: add memory search p1 validation guide`

P2:

- `b3a67aa4` `feat: stabilize memory retriever boundaries`
- `76280080` `test: expand memory retriever regression coverage`
- `e0f2c6c3` `docs: add unified memory search validation`

P3:

- pending current branch commits

P4:

- pending current branch commits

P5:

- pending current branch commits

## Notes

- this validation entry is meant to be the top-level command for local memory-search regression checks
- benchmark numbers remain sanity signals rather than machine-independent guarantees
