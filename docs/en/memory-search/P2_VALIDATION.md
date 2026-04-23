# Memory Search P2 Validation

This document captures the current P2 scope for memory search retriever-boundary work, along with repeatable validation commands.

## Scope

P2 focuses on stabilizing the internal boundary between:

- file memory retrieval
- session history retrieval

The external `search_memory` tool contract remains stable for existing consumers.

Current improvements include:

- explicit cache reset helpers on both retrievers
- stable `search_memory` response keys across success and error paths
- regression coverage for:
  - file retriever cache reuse
  - file retriever refresh interval behavior
  - session history cache reuse
  - session history cache invalidation on message/config changes
  - tool-level `session_id` injection through `ToolManager`

## Test Suite

Primary P2 regression suite:

```bash
python tests/sagents/tool/impl/test_memory_tool.py
```

Current coverage includes:

- stable error contract for missing session / empty query
- session-history retriever cache reuse
- session-history retriever cache invalidation when `agent_config` changes
- file-memory retriever scoped index reuse
- file-memory retriever refresh after refresh interval
- split-result success shape
- tool-level invocation through `ToolManager`

## Recommended Validation

Run the local validation for this branch:

```bash
python -m py_compile sagents/tool/impl/memory_tool.py tests/sagents/tool/impl/test_memory_tool.py
python tests/sagents/tool/impl/test_memory_tool.py
python tests/sagents/tool/impl/test_memory_index_fts.py
```

Unified entry:

```bash
python scripts/memory_search_validate.py
```

## Current Checkpoints

- `b3a67aa4` `feat: stabilize memory retriever boundaries`
- `76280080` `test: expand memory retriever regression coverage`

## Notes

- this P2 line intentionally keeps the current `long_term_memory` / `session_history` consumer contract
- the goal here is not storage migration; it is to make the two retrieval paths easier to validate and evolve independently

