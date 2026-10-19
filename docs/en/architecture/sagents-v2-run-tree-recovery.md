---
layout: default
title: Run Tree Recovery
parent: Architecture
nav_order: 21
lang: en
ref: v2-detail-sagents-v2-run-tree-recovery
---

{% include lang_switcher.html %}

# Standard recovery of nested child Runs

A paused child Run can continue while its ancestors remain paused. Hosts do not need to run the root Agent, replace the task or provision sandboxes manually.

## Public calls

For explicitly paused Runs, use the following sequence. Approvals and other interactions use their standard Interaction reply contract.

```python
from sagents.v2.contracts.commands import ResumeRun

access = app.service("session.access")
run = await access.get_run(run_id, context)
suspension = await access.get_suspension(run.suspension_id, context)
agent = await app.agent_for_run(run_id, context)
receipt = await app.runtime.resume_run(ResumeRun(
    run_id=run_id,
    expected_revision=run.revision,
    suspension_id=suspension.suspension_id,
    expected_suspension_revision=suspension.expected_revision,
    idempotency_key=resume_request_id,
), context)
if receipt.decision.value == "accepted":
    future = await app.entrypoint().continue_run(run_id, context, agent=agent)
    result = await future
```

After rebuilding App, use the same registrations and persistent state directory. `agent_for_run` retrieves the archived graph, and the standard Driver selects the actual child definition from the original StartRun identity rather than defaulting to the graph root.

## Resource dependencies and leases

Before loop assembly, standard execution follows authorized persisted parent Run commands, acquiring leases from outer dependencies toward the child. Each layer uses its original accepted snapshot without readmission, current-setting substitution, or ancestor model/tool execution. Traversal stops above `private_child`; its descendants restore into that private workspace. Read-only and narrowed policies retain their original restrictions.

An active Run lease supplies an independently closeable additional handle. Only explicit resource recovery may rebuild a released child member; ordinary duplicate sharing still fails. Old handles stay closed and old processes are not replayed.

Child recovery retains ancestor resource references until child binding closure. Completion, cancellation and assembly failure release the child before its dependencies. Active ancestor handles preserve the environment. Once all references close, the physical environment ends while disk workspaces persist. A new sandbox ID may be allocated, preserving Run, Session, configuration identity and workspace boundaries.

Concurrent recovery uses independent cancellation ownership. `ExecutionBindingProvider.acquire()` implementations must honor independent handles, reference counts and Run ownership rather than returning one closeable object to multiple owners.

## Errors and diagnostics

- `execution.parent_binding_not_ready`: `retryable=true`, `safe_to_resume=true`; the standard coordinator acquires dependencies. Direct provider calls bypassing coordination can encounter a missing parent lease.
- `execution.configuration_incompatible`: the original snapshot, workspace, trusted interpreter or capability cannot be recovered. Fail explicitly rather than silently applying current configuration.

`app.execution_configuration(run_id, context)` returns the original snapshot. `execution_diagnostics()` reports the most recently acquired sandbox, interpreter, capabilities and `resource_dependencies`, including original Run IDs, configuration identities and actual leases. Resource-only ancestor restoration updates diagnostics too. These are acquisition facts, not proof that resources remain active.

Recovery does not dispatch completed children or replay completed tools. Uncertain external effects still follow the tool's reconciliation contract; resource reconstruction does not retry them.

## Automated verification

`tests/sagents/v2/test_direct_child_recovery.py` uses standard registration, loading and execution to recover a leaf after all three layers pause, both within one App and after rebuilding App. It verifies original identities, actual role instructions and Skills, paused ancestors, dependency ownership, dispatch counts and final release.

`test_shared_sandbox_leases.py` checks that an active parent remains usable while a released child is restored, without weakening ordinary duplicate-sharing rejection.

## Validation record

On 2026-10-19, macOS / Python 3.13: SDK 3268 passed, 55 skipped; Desktop + Server 870 passed, 1 skipped for external MySQL; standard reference media hosts in development and frozen builds 4 passed. Ruff and diff checks passed. Fault injection verifies rollback on corrupt child snapshots and that old receipts/handles cannot affect restored leases.

After merging the remote reducer schema update, Yiii's unchanged `video-asset-agent` same-App and host-restart pause/resume acceptance cases both passed (2 passed), using its real Skills and three nested built-in Teams. Yiii source was not changed, and no host Driver or execution replacement was added. The remote schema update resolved the earlier loading blocker.
