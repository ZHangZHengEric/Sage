# Change Log

## 2026-02-05
- [CLI] Fixed `unrecognized arguments` error in `fibre_cli.py` by wrapping global `argparse` execution in `mcp_servers/search/serper_search.py` with `if __name__ == "__main__":`.
- [FibreAgent] Fixed `ValueError` in sandbox creation by updating `fibre_cli.py` to generate session IDs with hyphens instead of colons (e.g., `2026-02-05_10-28-17_bd8e`), avoiding invalid paths for `venv` creation.
- [Observability] Fixed `TypeError: Object of type MessageChunk is not JSON serializable` in `opentelemetry_handler.py` by adding a custom JSON serializer that handles `dataclasses` and objects with `to_dict` methods.

## 2026-02-04
- [CLI] Fixed critical bug in `fibre_cli.py` where long arguments were unrecognized due to global argument parsing in `mcp_servers/search/serper_search.py`.
- [FibreAgent] Created `app/fibre_cli.py` to support FibreAgent command-line interaction, including async stream processing and simplified tool integration.
- [FibreAgent] Refactoring:
  - `FibreTools`: Simplified `sys_finish_task` to merge `summary` and `details` into a single `result` parameter, focusing on execution process and resources.
  - `FibreTools`: Removed `task_goal` from `sys_spawn_agent` signature and documentation, aligning with the pattern where tasks are assigned via `sys_send_message`.
  - `FibreTools`: Added detailed `param_description_i18n` for better Chinese support and documentation.
  - `FibreOrchestrator`: Optimized `_create_combined_tool_manager` to reuse existing `ToolManager` instance instead of creating a new one, improving efficiency and context preservation.
  - `FibreAgent.run_stream` signature cleaned; prompts moved to `sagents/prompts/fibre_agent_prompts.py`.
- [FibreAgent] Completed implementation of FibreAgent core components:
  - Fixed `FibreOrchestrator` to correctly use `run_stream` for `SimpleAgent` execution.
  - Implemented `FibreSubAgent` logic including initialization and message processing loop.
  - Verified agent spawning and communication flow with `test_fibre.py` using mock model.
  - Ensured system prompts are correctly injected via `session_context`.
- [FibreAgent] Implemented initial structure for `FibreAgent` architecture (Parallel Implementation):
  - Created `sagents/fibre` package.
  - Implemented `FibreAgent` container compatible with `SAgent` interface.
  - Implemented `FibreOrchestrator` for sub-agent management and event loop.
  - Implemented `FibreTools` for `sys_spawn_agent` and messaging capabilities.
- [Design] Refactored Liquid Agent design document: renamed "Liquid" to "Fibre" (fiber), "Droplet" to "Strand" (strand), and "Flow" to "Transmission" (transmission), including Chinese concept updates in `FIBRE_AGENT_DESIGN.md`.
- [Sandbox] Implemented automatic path mapping for string arguments (e.g., commands, scripts) in `Sandbox` to resolve "Read-only file system" errors when agents use `/workspace` absolute paths.
- [Sandbox] Verified and optimized Python package installation: packages are installed in `.pylibs` within the session's working directory, ensuring isolation from the host environment.
- [SageDemo] Optimized session ID management: `session_id` is now persistent across the conversation lifecycle and only regenerates when "Clear History" is clicked, ensuring consistent session context for stateful operations.
- [SkillManager] Fixed bug where custom `skill_dirs` (passed via `--skills_path`) were ignored during skill loading. Now correctly scans all configured directories.
- [Sandbox] Disabled `RLIMIT_AS` (virtual memory limit) on macOS to prevent "Sandboxed process died unexpectedly" errors caused by OS-specific memory handling behavior.
- [SessionContext] Fixed `SandboxFileSystem` serialization error by saving `host_path` string instead of object in `save()` method.
- [SessionContext] Added detailed logging to `__init__` (lines 116-119) to debug skill copying process (logging skill manager status, available skills, and copy result/errors).
- [SageDemo] Verified `sage_demo.py` correctly initializes `SkillManager` with `skills_path` from arguments.
- [SageDemo] Fixed critical bug in `generate_response` where `skill_manager` was not passed to `process_stream`, causing skills to be unavailable during conversation.
- [Sandbox] Added `/usr/share/zoneinfo` and `/etc/localtime` to default allowed paths to fix `pandas`/`dateutil` import errors in sandboxed environment.
- [Sandbox] Added `/etc/mime.types`, `/etc/apache2/mime.types`, `/etc/httpd/mime.types`, and `/usr/local/etc/mime.types` to default allowed paths to fix `openpyxl`/`mimetypes` import errors.
