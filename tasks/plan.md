# Versioned dependency split and application verification

## Accepted objective
Complete the v1/v2 dependency split, update every install/CI/package consumer, and verify all applications under app can run and package. Preserve existing unrelated working-tree changes. No business storage or frontend subtitle changes.

## Dependency boundaries
- app/v1 owns legacy requirements, including separate test/build requirements where needed.
- Root pyproject.toml defines v2 core and explicit Server/Desktop/test extras. Preserve the public v1 CLI dispatch; v1 dependencies are installed explicitly.
- Server v2 Docker derives its dependency installation from pyproject rather than a second manually maintained runtime list.
- CI installs v1 and v2 in separate environments; cross-version tests explicitly combine dependencies.
- Skill-local requirements remain owned by their skill; packaged content is checked as resources.

## Ordered work
1. Inventory imports, entry points, native toolchains, and existing modifications. Verify dependency ownership against actual imports.
2. Move legacy requirements and update v1 development, examples, Docker, packaging, and documentation references. Check path resolution and shell syntax.
3. Replace broad root dependencies with v2 core and Server/Desktop/test extras. Update v2 CLI diagnostics and Desktop/Server packaging. Build wheel/sdist and install in fresh environments; use pip check and imports/startup checks.
4. Split CI environments and update development/test documentation. Verify workflow matrices preserve all suites.
5. Run backend suites in fresh environments and resolve dependency/install failures. Run frontend, Flutter, Rust, browser-extension, wiki and skill-resource checks; build host-platform artifacts and run packaged smoke tests.
6. Review final changes and write a requirement-by-requirement verification report, with actual commands, outcomes, artifacts and any unverified platforms or external-service dependencies.

## Acceptance and verification
- No current consumer installs a removed root requirements file.
- v2 installs and tests independently of v1 requirements; declared extras contain all required direct dependencies.
- v1 workflows remain functional using app/v1 requirements.
- Wheel/sdist and host-native application artifacts build and launch successfully; tests cover the real application entries.
- Windows/Linux/macOS verification is reported separately; unavailable platform evidence is not claimed as passed.
- Keep the durable goal active until all explicit requirements have authoritative evidence.
