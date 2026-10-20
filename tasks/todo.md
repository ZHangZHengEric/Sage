# Dependency split checklist

- [x] Inventory dependency ownership and application/toolchain verification matrix.
- [x] Move v1 requirements and update all active v1 consumers.
- [x] Define v2 core, Server, Desktop and test extras from real imports.
- [x] Make Server Docker and Desktop bundling use the v2 metadata.
- [x] Split CI environments; preserve cross-version and MCP tests.
- [x] Update installation and test documentation and stale diagnostics.
- [x] Build wheel/sdist; install fresh v1/v2 environments; pip check and startup smoke.
- [x] Run all backend suites and fix dependency regressions.
- [ ] Finish v2 Web/Flutter Desktop, Rust terminal and packaged skill resource verification; preserve completed v1 UI/wiki/extension checks.
- [x] Stop further v1 Server image and v1 Desktop builds as explicitly requested.
- [ ] Launch packaged host applications and verify available native artifacts.
- [ ] Record current-host validation and explicitly list other platforms not executed; no publishing or remote CI dispatch is requested.
- [ ] Final review and evidence report; completion audit against full objective.
