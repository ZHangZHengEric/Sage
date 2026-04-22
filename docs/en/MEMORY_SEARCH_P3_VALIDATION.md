# Memory Search P3 Validation

This document captures the current P3 scope for session-memory backend separation work.

## Scope

P3 focuses on separating the session-history backend implementation from the manager/runtime wiring.

Current improvements include:

- a backend contract in `sagents/context/session_memory/backend.py`
- a dedicated BM25 backend implementation in `sagents/context/session_memory/bm25_backend.py`
- a placeholder `noop` backend for session memory
- a factory entrypoint in `sagents/context/session_memory/factory.py`
- `SessionMemoryManager` reduced to a manager/delegation layer
- `SessionContext` now builds the manager through the backend factory instead of directly hardcoding one implementation
- matching file-memory backend/factory wiring under `sagents/tool/impl/file_memory/`

## Test Suite

Primary P3 regression suite:

```bash
python tests/sagents/context/test_session_memory_manager.py
python tests/sagents/tool/impl/test_file_memory_backend.py
```

Current coverage includes:

- default backend selection
- noop backend selection
- backend delegation from `SessionMemoryManager`
- cache clearing delegation
- environment-driven backend selection
- unsupported backend rejection
- BM25 backend cache reset behavior
- file-memory backend factory selection
- noop file-memory backend behavior
- scoped-index file-memory backend cache reuse

## Recommended Validation

Run the local validation for this branch:

```bash
python -m py_compile sagents/context/session_memory/backend.py sagents/context/session_memory/bm25_backend.py sagents/context/session_memory/factory.py sagents/context/session_memory/session_memory_manager.py tests/sagents/context/test_session_memory_manager.py
python tests/sagents/context/test_session_memory_manager.py
python tests/sagents/tool/impl/test_file_memory_backend.py
python tests/test_memory_tool.py
```

Unified entry:

```bash
python scripts/memory_search_validate.py
```

## Notes

- this P3 step does not replace BM25 yet; it isolates it behind backend boundaries
- the goal is to make future session-history and file-memory backend changes independent from `MemoryTool` and `SessionContext`
