# Dependency split checklist

- [ ] Inventory dependency ownership and application/toolchain verification matrix.
- [ ] Move v1 requirements and update all active v1 consumers.
- [ ] Define v2 core, Server, Desktop and test extras from real imports.
- [ ] Make Server Docker and Desktop bundling use the v2 metadata.
- [ ] Split CI environments; preserve cross-version and MCP tests.
- [ ] Update installation and test documentation and stale diagnostics.
- [ ] Build wheel/sdist; install fresh v1/v2 environments; pip check and startup smoke.
- [ ] Run all backend suites and fix dependency regressions.
- [ ] Test/build Web UIs, Flutter Desktop, Rust terminal, browser extension and wiki; verify packaged skill resources.
- [ ] Launch packaged host applications and verify available native artifacts.
- [ ] Obtain platform-specific verification for all supported release targets.
- [ ] Final review and evidence report; completion audit against full objective.
