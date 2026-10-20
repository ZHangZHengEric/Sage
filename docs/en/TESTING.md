---
layout: default
title: Testing
nav_order: 12
lang: en
ref: v2-TESTING
---

{% include lang_switcher.html %}

# Testing

Tests should detect meaningful regressions while remaining inexpensive to understand, change, and execute. There is no target test count. This guide applies to SDK and application tests; select the component and version requested by the change.

## Define the evidence first

Before adding a test, identify the behavior that can regress, the observable result that distinguishes correct behavior, and the existing tests that already cover it. For a configuration change, ask whether a pure rule or validation test is enough. For a bug, keep a case that fails for the original defect.

Do not add tests merely because a function exists. Low-impact, reversible changes do not need new tests that restate their implementation. Preserve public wire/storage contracts and supported migration behavior even when their tests look simple.

## Choose the smallest useful boundary

| Boundary | What it establishes | Typical setup |
| --- | --- | --- |
| Pure rule or validation | Normalization, classification, limits, schemas | Direct function/model call |
| Provider or adapter contract | Actual payloads, error mapping, lifecycle and cleanup | Real adapter with a fake external client |
| Runtime integration | Accepted configuration reaches execution and durable state | Scripted model, real runtime, temporary store |
| Process/database acceptance | Restart durability, OS enforcement, database transactions | Real subprocess, native sandbox, test database |
| Live provider acceptance | Real upstream behavior | Explicit opt-in credentials and cost |

A mock SQL cursor does not prove database compatibility. An in-memory store does not prove durability after process death. An SDK test does not establish that a host UI works. Keep these evidence boundaries explicit in reports.

## Select cases by behavior

Use parameterization for independent, distinguishable cases with useful IDs. Full products are justified when dimensions interact: approval plus restart, parser state plus stream error, tenant plus ownership, or commit failure plus database backend. Preserve these combinations.

When dimensions are independent, test aliases/defaults comprehensively at the rule layer and keep representative integrations for each real consumer. Include missing, boundary, invalid, and explicit-override cases where they exercise different decisions. Explain why omitted combinations add no new behavior.

Catalog checks such as translation keys can be grouped by locale when the failure message lists every bad key. Keep independent protocol mappings and failure modes individually identifiable. Moving cases into a loop reduces collected nodes, but may not reduce runtime or maintenance cost.

## Share setup without hiding contracts

Reuse existing fixtures and public builders. Extract repeated event samples, model capabilities, or backend factories into small fixture modules when they are genuinely shared. Keep the expected behavior visible in the test. Do not turn the suite into a generic framework or add one-line wrappers without useful shared setup.

Check inventory boundaries before consolidation. For example, a settings catalog may omit management-only tools. A schema audit that covers all decorated tools must keep those tools, even if the public catalog is easier to query. New backends should run the common contracts plus their own locking, transaction, and failure tests.

Examples: [shared SQL contracts](https://github.com/ZHangZHengEric/Sage/blob/main/tests/sagents/v2/test_sql_session_store_contract.py), [event samples](https://github.com/ZHangZHengEric/Sage/blob/main/tests/sagents/v2/event_fixture.py), and [decorated tool discovery](https://github.com/ZHangZHengEric/Sage/blob/main/tests/sagents/v2/tool_fixture.py).

## Assert behavior at the boundary

Assert emitted frame names, loss codes/fidelity, actual SQL statements and bound values, canonical events, durable results, dispatch counts, and side effects. “Frames or losses exist” is insufficient if a supported mapping could become unsupported and still pass. For rejected operations, verify that execution or persistence did not occur.

Avoid assertions about source substrings, absent historical files, arbitrary class names, and copied prose that is not part of the contract. Use AST checks for real dependency constraints. At a wire boundary, compare transported prompt content with the request supplied to the adapter; test locale selection and authored-content preservation in the context suite.

Mocks belong at external boundaries. They should not implement the same algorithm that the test claims to verify. When an assertion is easy to satisfy accidentally, temporarily inject a wrong mapping, lost field, extra dispatch, or failed write and confirm that the test detects it.

## Synchronize on observable progress

Prefer `asyncio.Event`, barriers, completed futures, or bounded polling of actual state over arbitrary sleeps. Wait for the runner to enter before cancelling it. A negative concurrency assertion needs evidence that the competing operation reached the contested boundary, not merely that its task was created.

Keep real timing for deadline enforcement, backoff interruption, CPU/disk limits, and assertions that an operation stays blocked. Do not replace these with `sleep(0)` or a no-op clock. A test about recovery-questionnaire contents can set retry delays to zero while preserving retry attempts; separate tests must still cover backoff and cancellation.

## Validate and report accurately

Run focused tests after each coherent batch, then the affected suites. Preserve unrelated working-tree changes. A failed test is not a reason to add a skip, widen an expectation, or delete a scenario. Distinguish implementation failures from missing dependencies, unsupported OS facilities, execution-sandbox restrictions, and a child `python` resolving to a different interpreter.

From the repository root in the configured Python 3.12+ environment:

```bash
python -m pytest tests/sagents/v2 --collect-only -q
python -m pytest tests/sagents/v2/test_prompt_language_matrix.py -q
python scripts/shared/checks/check_architecture.py
python -m pytest tests/sagents/v2 -m 'not live' -q --durations=10
python docs/scripts/check_docs.py
```

The [CI workflow](https://github.com/ZHangZHengEric/Sage/blob/main/.github/workflows/ci-tests.yml) defines version-specific environments and native sandbox dependencies. SQL contracts require `SAGE_V2_TEST_MYSQL_DSN` or `SAGE_V2_TEST_POSTGRES_DSN`; use dedicated test databases. Live-provider tests remain opt-in. Do not claim those paths passed when they were skipped or deselected.

Report the change in covered behavior/setup, focused and full results, relevant durations, and any limits. Distinguish test functions, collected parameterized nodes, executed cases, skips, and live cases. A static inventory or focused review is not a complete semantic review or a production proof.

## Agent workflow

1. Read the scoped instructions and locate existing tests for the behavior.
2. Write down the regression and the smallest boundary that can detect it.
3. Reuse or extend existing coverage; justify any new matrix or full Agent execution.
4. Implement one coherent batch, check that failure assertions are meaningful, and run focused verification.
5. Review removed coverage explicitly; retain independent safety and fault boundaries.
6. Run affected suites and documentation checks, then report exact results and unverified paths.

The scoped entry point for future agents is [tests/AGENTS.md](https://github.com/ZHangZHengEric/Sage/blob/main/tests/AGENTS.md). This process does not authorize unrelated production changes, deployment, live-provider costs, or extra business storage for audit purposes.
