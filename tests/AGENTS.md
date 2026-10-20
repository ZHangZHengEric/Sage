# Test authoring

Read [the testing guide](../docs/en/TESTING.md) before adding or restructuring tests. These rules apply to tests throughout this directory; keep changes within the requested component/version.

- State the regression, observable result, and existing coverage before writing a new test. Extend an existing test when it protects the same behavior.
- Use the smallest real boundary that can fail: pure rule, provider contract, runtime integration, then process/database acceptance. Do not create an App or run an Agent to test spelling aliases, schema defaults, or equivalent configuration values.
- Parameterize distinct cases. Use a full Cartesian product only when the dimensions interact; retain all coupled security, approval, transaction, concurrency, and recovery cases.
- Group repetitive catalog checks only when failures remain identifiable, preferably reporting all failing keys. Reducing pytest node counts alone is not an optimization.
- Assert observable behavior and side effects. Compare actual wire/SQL output, not source strings or old filenames. AST checks are appropriate for genuine dependency boundaries, not arbitrary class names or layout.
- Share repeated setup in narrowly scoped fixture modules. Do not import test methods as fixtures, build a general test framework, or replace a complete internal tool/provider inventory with a narrower public inventory.
- Use events/barriers or observable state with a timeout for synchronization. Keep real timing for deadlines, backoff cancellation, resource limits, and checks that an operation remains blocked. Never replace required synchronization with an unconditional `sleep(0)`.
- Keep mocks at external boundaries. Assert that rejected operations did not dispatch, persist, or perform a side effect. Where useful, inject an incorrect result to confirm the test fails.
- Preserve the requested behavior and storage boundaries. Do not add production logic, business storage, compatibility paths, skips, or weaker expectations merely to make tests pass.
- Run focused checks per batch, then affected suites. Report collected nodes separately from executed tests, and identify skips, deselected live tests, platform limits, warnings, and unavailable database/provider evidence.
