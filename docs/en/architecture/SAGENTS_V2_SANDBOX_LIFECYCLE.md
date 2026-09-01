# SAgents v2 sandbox suspension, release, and restore

SAgents v2 persists approval state independently from execution compute.
`InteractionRequest`, the Agent `Checkpoint`, and `Suspension` remain in the Session
Aggregate while a sandbox is released, cleanup is retried, or the application restarts.
The frontend continues to render pending Interactions from the server Snapshot and does
not expose internal execution-resource state.

## Ownership

- Tools only declare `JobSpec.pause_behavior` and `execution_affinity`; they cannot
  release a sandbox.
- After a Scheduler Worker owns the Run lease, the Host creates an
  `ExecutionBindingLifecycleCoordinator` to provision, attach, restore, and release.
- SessionStore persists one CAS-protected `ExecutionResourceRecord` per Run. Mutations
  are protected by Scheduler fencing.
- `SandboxProvider.close()` only closes a client handle. Compute is released only when
  the v3 `release()` receipt confirms fencing/termination with
  `compute_released=true`.

Safe isolated pauses use `SNAPSHOT_AND_TERMINATE`; Active Workspace pauses use
`TERMINATE` because files are host-persistent. `POLICY_HOLD` uses `DETACH`. Active
`sandbox + CONTINUE/DETACH` Jobs produce `RELEASE_BLOCKED`; Scheduler cleanup work
re-evaluates the record after those Jobs finish. External Jobs do not block release.

A release failure leaves the Run `SUSPENDED` and its Interaction pending. Cleanup is
retried with exponential backoff from one second to five minutes. Resume allocation
happens in `RESUMING`; the same per-Run Scheduler fence serializes cleanup against
resume, and the Runtime validates Run/spec/policy hashes before continuing the Agent
Loop. Parent and child Runs own separate records, and a parent remains blocked while a
child resource has not reached `RELEASED`.

## Sandbox plugin API v3

The `execution.sandbox` capability and `ResolvedSandboxSpec` are v3. v2 plugins are
rejected without fallback. Providers must implement the idempotent API:

```python
async def release(
    request: SandboxReleaseRequest,
    context: RequestContext,
) -> SandboxReleaseReceipt: ...
```

Providers must accurately advertise `DETACH`, `TERMINATE`, and
`SNAPSHOT_AND_TERMINATE`. Repeating the same `(sandbox_id, idempotency_key)` returns the
same outcome with `duplicate=True`. Snapshot release returns a checkpoint, terminated
compute invalidates old Grants, and closing an SDK/HTTP handle never justifies
`compute_released=true`.

`ExecutionBindingLifecycleCoordinator.metrics_snapshot()` exposes active/retained
counts, pending cleanup, failures/retries, blocked age, and release latency for
diagnostics without changing user-visible copy.
