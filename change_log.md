# Change Log

## 2026-02-04
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
