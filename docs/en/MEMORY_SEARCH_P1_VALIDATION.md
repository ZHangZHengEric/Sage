# Memory Search P1 Validation

This document captures the current P1 scope for memory search quality work, along with repeatable validation commands.

## Scope

P1 focuses on search quality and stability without changing the broader runtime architecture.

Current improvements include:

- multi-term candidate selection prefers `AND` matches before falling back to `OR`
- file ranking uses query-term coverage, chunk diversity, cohesion, and chunk span signals
- row-level reranking includes path tokens in addition to chunk content
- preview selection skips strongly overlapping redundant chunks
- tokenizer expansion covers:
  - `snake_case`
  - `camelCase`
  - mixed English / Chinese search terms
- path and directory tokens are indexed for file-level and chunk-level search

## Test Suite

Primary regression suite:

```bash
python tests/test_memory_index_fts.py
```

Current coverage includes:

- focused chunk hit retrieval
- stale sidecar cleanup
- multi-chunk ranking
- multi-term coverage ranking
- chunk cohesion and tighter span preference
- redundant preview suppression
- identifier-aware search
- directory/path-aware search
- realistic CLI/runtime query coverage
- mixed-language query coverage
- moderate synthetic latency sanity checks

## Benchmark Script

Synthetic benchmark:

```bash
python scripts/memory_search_benchmark.py
```

Useful variants:

```bash
python scripts/memory_search_benchmark.py --noise-files 300
python scripts/memory_search_benchmark.py --noise-files 600 --top-k 5
python scripts/memory_search_benchmark.py --noise-files 1000 --chunk-size 160
```

The benchmark prints:

- index build time
- per-query search time
- top result path
- top result score
- total and average query latency

## Recommended Validation

Run the full local validation for this branch:

```bash
python -m py_compile sagents/tool/impl/memory_index.py tests/test_memory_index_fts.py scripts/memory_search_benchmark.py
python tests/test_memory_index_fts.py
python scripts/memory_search_benchmark.py --noise-files 300
```

Unified entry:

```bash
python scripts/memory_search_validate.py
```

## Current Checkpoints

- `cac18b1f` `feat: improve memory search ranking quality`
- `cf569769` `test: expand memory search query coverage`
- `eb4bc953` `test: add memory search performance sanity cases`

## Notes

- this P1 line improves search quality and regression coverage, but does not redesign runtime memory architecture
- benchmark numbers are intended as sanity signals, not hard performance guarantees across every machine
