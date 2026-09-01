# SAgents v2 沙箱暂停、释放与恢复

SAgents v2 将审批状态与执行计算分开持久化。`InteractionRequest`、Agent
`Checkpoint` 和 `Suspension` 属于 Session Aggregate，因此沙箱释放、应用重启或
清理重试都不会移除待处理审批。前端继续只读取 Snapshot 中的 pending
Interaction，不展示内部资源记录。

## 责任边界

- Tool 只能通过 `JobSpec.pause_behavior` 与 `execution_affinity` 声明后台任务行为，
  不能直接销毁沙箱。
- Host 在 Scheduler Worker 获得 Run lease 后创建
  `ExecutionBindingLifecycleCoordinator`，由它统一 provision、attach、restore 和
  release。
- SessionStore 以 CAS 保存每个 Run 的 `ExecutionResourceRecord`；所有写入受
  Scheduler fencing 保护。
- `SandboxProvider.close()` 只关闭客户端句柄。只有 v3 `release()` receipt 中经
  Provider 确认的 `compute_released=true` 才表示计算实例已经被 fencing/终止。

安全暂停对隔离沙箱使用 `SNAPSHOT_AND_TERMINATE`，对宿主持久化 Active
Workspace 使用 `TERMINATE`。`POLICY_HOLD` 使用 `DETACH`。运行中的
`sandbox + CONTINUE/DETACH` Job 会把记录置为 `RELEASE_BLOCKED`；Job 完成后由
Scheduler cleanup work 重新评估。`external` Job 不阻塞释放。

释放失败不会改变 `SUSPENDED` Run 或 Interaction。记录进入 `RELEASE_FAILED`，
按 1 秒到 5 分钟指数退避重试。恢复时 Run 已处于 `RESUMING`，同一 Run 的
Scheduler fence 保证 cleanup 与 resume 不并发；Runtime 会先确认旧实例被
fencing，再 attach、restore 或 provision，校验 Run/spec/policy hash 后才继续
Agent Loop。

父子 Run 分别持有资源记录。父 Run 会记录未释放的 child Run，并在子资源全部
进入 `RELEASED` 前保持 `RELEASE_BLOCKED`。

## Sandbox 插件 v3

`execution.sandbox` capability 和 `ResolvedSandboxSpec` 已升级为 v3。v2 插件不会
被加载，也没有兼容回退。Provider 必须实现幂等：

```python
async def release(
    request: SandboxReleaseRequest,
    context: RequestContext,
) -> SandboxReleaseReceipt: ...
```

Provider 必须支持并准确声明 `DETACH`、`TERMINATE`、
`SNAPSHOT_AND_TERMINATE` disposition。相同 `(sandbox_id, idempotency_key)` 必须
返回同一个结果并标记 `duplicate=True`；快照释放必须返回 checkpoint；终止后旧
Grant 必须失效。插件不得在仅关闭 SDK/HTTP 客户端句柄时返回
`compute_released=true`。

诊断可通过 `ExecutionBindingLifecycleCoordinator.metrics_snapshot()` 获取 active、
retained、pending、失败/重试、blocked age 与 release latency，不改变用户可见文案。
