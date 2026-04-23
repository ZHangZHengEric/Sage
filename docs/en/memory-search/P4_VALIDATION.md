# Memory Search P4 Validation

This document captures the current P4 scope for memory backend and strategy evolution work.

## Scope

P4 builds on the backend split from P3 and makes the retrieval path more configurable and diagnosable.

Current improvements include:

- a shared backend-selection registry in `sagents/context/memory_backend_registry.py`
- backend resolution precedence for session history and file memory:
  - explicit parameter
  - `agent_config`
  - environment variable
  - default
- session-history retrieval strategy resolution in `sagents/context/session_memory/session_memory_manager.py`
- support for:
  - `memory_backends.session_history`
  - `memory_backends.file_memory`
  - `memory_backends.session_history_strategy`
- compatibility with legacy keys:
  - `session_memory_backend`
  - `file_memory_backend`
  - `session_memory_strategy`
- runtime propagation through `SessionContext` and `MemoryTool`
- CLI diagnostics through `sage doctor` and `sage config show`

## Test Suite

Primary P4 regression suites:

```bash
python tests/sagents/context/test_session_memory_manager.py
python tests/sagents/tool/impl/test_file_memory_backend.py
python tests/sagents/tool/impl/test_memory_tool.py
python tests/app/cli/test_doctor_memory_backends.py
```

Current coverage includes:

- backend resolution precedence
- strategy resolution precedence
- legacy config key compatibility
- unsupported backend rejection
- unsupported strategy rejection
- session-history grouped-chat vs messages dispatch
- file-memory noop vs scoped-index backend selection
- `ToolManager` tool-level `search_memory` execution
- doctor/config diagnostics for resolved backends and session-history strategy
- doctor/config structured error handling for invalid backend or strategy values

## Recommended Validation

Run the local validation for this branch:

```bash
python -m py_compile app/cli/service.py sagents/context/memory_backend_registry.py sagents/context/session_memory/session_memory_manager.py sagents/tool/impl/memory_tool.py tests/app/cli/test_doctor_memory_backends.py tests/sagents/context/test_session_memory_manager.py tests/sagents/tool/impl/test_file_memory_backend.py tests/sagents/tool/impl/test_memory_tool.py
python tests/app/cli/test_doctor_memory_backends.py
python tests/sagents/context/test_session_memory_manager.py
python tests/sagents/tool/impl/test_file_memory_backend.py
python tests/sagents/tool/impl/test_memory_tool.py
python scripts/memory_search_validate.py --noise-files 30 --top-k 2
```

Unified entry:

```bash
python scripts/memory_search_validate.py
```

## Notes

- P4 still keeps the current external `search_memory` contract stable
- this stage improves configurability and diagnostics; it does not introduce a new storage backend migration yet
