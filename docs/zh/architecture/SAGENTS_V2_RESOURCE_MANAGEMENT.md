# SAgents V2 运行时资源管理

日期：2026-09-13。范围为 SAgents V2 及 Desktop V2，不包含监督学习。

## 宿主接入

```python
from sagents.v2.agent.management import AgentManagementService
from sagents.v2.model import ModelConcurrencyBudget

# 所有相关服务与 Builder 必须复用同一个对象，才有共同的模型并发上限。
budget = ModelConcurrencyBudget(limit=8, max_waiting=128, wait_timeout_seconds=60)
service = AgentManagementService(
    root,
    builder_factory=build_package,
    authorize=authorize_package,
    model_budget=budget,
    require_readiness=True,
    auto_release_idle_seconds=300,  # 默认；None 关闭容量触发回收，0 允许立即回收
)
report = await service.validate(bundle, context, readiness=True)
# 宿主选择合适的维护时机调用；没有默认后台回收任务。
reclaimed = await service.release_idle(min_idle_seconds=300, limit=4)
metrics = service.capacity()
```

普通 SAgentBuilder 可调用 `with_model_budget(budget)`；管理服务会将注入的额度传给其 Builder。默认不注入额度时，不额外承诺跨 Application 的限制。第三方 Builder 需实现对应接入方法。

## 资源就绪性

`validate(readiness=True)` 在初始化期间查询 Tool 与 Skill 目录，返回 `readiness.ready`、`missing_tools`、`missing_skills`、`unverified`。`valid` 仍表示结构、组合与 provider 初始化通过。缺失资源可以表现为 `valid=True` 且 `readiness.ready=False`，避免把两种判断混为一谈。

宿主设置 `require_readiness=True` 后，资源缺失或无法验证会阻止保存和新 Run。重复保存同一版本、运行已经缓存的版本，也会重新验证当前宿主资源；会增加初始化与清理成本，不应把它当作免费的检查。此选项默认关闭，保留原有宿主装配行为。

管理工具 `agent_package_validate` 同样接受 `readiness=true`。只保存源码、只保存版本引用，都不是资源就绪证明。

该检查不调用模型、不执行工具、不物化技能。需要真实 Run 才能建立的绑定明确列为 unverified，严格模式拒绝；凭据实际有效性、远端执行与 Skill 内容可加载仍需要宿主进一步探测。授权策略继续独立执行，检查不能扩大资源权限。

## 共享模型并发额度

`ModelConcurrencyBudget` 限制同时进入 provider 的模型流与显式能力探测。名额覆盖流的整个生命周期；异常、取消与显式提前关闭归还名额。等待工具或递归创建 Agent 不占模型名额，避免把整个父任务锁住后再等待子任务取得同一额度。

`snapshot()` 返回 limit、active、waiting、max_waiting、wait_timeout_seconds，以及累计 rejected、timed_out。额度是同一事件循环内的宿主对象；它不是跨进程锁，也不限制总 token、工具子进程、全部 Run 的队列长度、内存或网络带宽。模型调用等待队列本身已有下述上限。模型 provider 内部并行发送的多个请求也不等同于多个额度。

Desktop V2 已将缓存的模型 provider 接入同一个额度，因此正常运行路径上的主模型、成员模型、判定、记忆查询和工具选择模型共享限制。`DesktopV2Service(max_concurrent_model_calls=8)` 是默认值；宿主可传入其他正整数。独立的模型验证接口不因此获得全宿主资源限制。

## 模型排队与过载处理

模型额度默认允许 128 个等待请求，等待上限 60 秒；这两个参数分别为 `max_waiting` 和 `wait_timeout_seconds`。`max_waiting=0` 表示只接受能够立即取得名额的请求。等待超时仅覆盖入场前排队，不截断已经进入 provider 的模型调用。

队列满返回 `model.queue_full`，排队超时返回 `model.queue_timeout`；两者都是可重试、可恢复的 RATE_LIMITED 错误。请求不会进入 provider，错误元数据保留当时的预算统计。已有等待者优先取得归还的名额；取消（包括名额已分配但任务尚未恢复执行的时刻）不会丢失名额。上游抛出的 TimeoutError 保持上游错误语义，不计为排队超时。

Desktop V2 可通过 `max_waiting_model_calls`、`model_queue_timeout_seconds` 配置对应参数，默认同上。直接 API 限流映射 HTTP 429 并保留错误代码和 retryable 字段。运行中的 Agent 则沿用现有错误恢复交互，保留现场并暂停；名额恢复后选择 retry 可以续接同一个 Run，无须重新创建任务。全部 9 种受支持语言的错误文案已补齐。

这不是全局任务调度器；后台队列、公平租户配额、工具子进程与内存预算仍需单独控制。

## 安全空闲回收

`release_idle` 是仅宿主可调用的接口，按最后使用时间排序，最多回收 limit 个达到空闲时间的实例。

- 每个管理操作持有其实际使用实例的使用计数；计数非零的实例不回收。查询结果、提交续接、控制操作和等待构建都受保护，取消请求会释放计数。其他未被使用的实例仍可回收。
- SessionStore 必须声明 `durable_across_process_restart=True` 并支持 `has_nonterminal_runs()`；未知实现与内存型存储跳过，避免回收后丢失多轮会话。检查包括队列、运行、暂停和子 Run，不能用“无可调度任务”替代“无非终态任务”。
- 文件存储同时检查尚未加载的持久 Session 与 journal；损坏数据报错而非忽略。扫描在后台线程执行，仅在显式回收或缓存容量不足时发生。
- 关闭失败保留实例、进入 draining，后续 `close()` 可重试，不重新接受任务。
- 回收删除缓存与关闭资源，保留持久文件。回收前分页归档已完成操作，后续历史查询直接读取归档；执行或续接仍可重新装配同版本会话。

当新 Application 需要名额且缓存达到上限时，默认尝试回收最后一次管理使用已超过 300 秒的实例，按最久未使用优先选择。阈值可通过 `auto_release_idle_seconds` 配置，传 None 关闭自动回收。运行中或暂停的实例始终保留；没有安全候选时返回容量错误。没有后台定时扫描。

此接口要求 managed Application 由服务独占管理，不能让宿主绕过服务直接提交任务。对于长历史存储，回收扫描仍应测量成本。`capacity()` 提供缓存、构建、在途操作、持有使用计数的实例数量、自动回收阈值、清理与模型额度统计；不会作为跨租户模型工具暴露。

## 终态结果归档

`status` 观察到终态、实例回收前，以及正常关闭前，会把已完成操作的状态、结果与 Flow 输出保存到库存 SQLite 的 `terminal_statuses`。回收与关闭按最多 100 条的页读取尚未归档的操作，避免一次加载全部历史。快照绑定调用者、operation、ref 和持久 Run handle。

读取归档仍先验证调用者归属并执行当前 `read_run` 授权。因此服务重启、模型插件卸载或缓存已满时，已归档历史也可读取，不需要 Builder、模型客户端或 worker。归档失败不跳过正常关闭的资源释放；自动回收则在完成归档后才关闭实例。

归档是终态结果的读取副本，SessionStore 仍是运行时权威状态源。若进程在第一次查询、回收或正常关闭之前崩溃，某些已完成任务可能尚未归档；内置文件存储现可从库存记录的实际存储位置读取快照与 journal，复用校验、Session 身份及调用者授权，不启动模型、不写源文件，读到终态后补归档。未终态、旧记录缺少位置或第三方存储仍走 Application 恢复路径。当前没有为任意第三方 SessionStore 实现通用的离线读取接口，也不会把未终态记录缓存为最终结果。

严格就绪模式重复保存同一 ref 时，现在返回本次真实验证报告及 `reused=True`，不再错误声称跳过了 provider 初始化。

## Flow 装配

入口 Flow 的可达集合包括所有条件边、并行 branches、subflow 和可达成员的 subagents，循环使用访问集合终止。模型只为入口及可达成员初始化；未参与该入口的 Agent 不再强制初始化。显式包验证仍检查包内每个 Agent，不借此隐藏其他版本成员的问题。

## 验证与剩余工作

回归覆盖缺失资源拒绝保存、已保存资源消失后的重新检查、独立 Application 共用额度、等待取消、流失败与提前关闭、暂停保留、完成后回收与重建、重启后的持久状态检查、损坏状态和清理失败，以及并行子流程的可达成员装配。

仍需实现：整个宿主进程的内存预算与公平调度、第三方存储的通用离线读取、Desktop 完整 package Studio、非可信源码隔离构建与依赖安装，以及真实模型长时间负载基准。这些均未由本轮测试替代。

最终回归结果见 [整体审查](V2_COMPREHENSIVE_REVIEW.md)。原生沙箱排除范围保留，不计为通过。

## 跨 Application 共享 JobRuntime

已有 `InMemoryJobRuntime` 提供运行并发、任务准入、单任务输出字节/分块和聚合保留输出上限。现在宿主可以将同一个实例传入 `AgentManagementService(..., job_runtime=jobs)`，或 `SAgentBuilder().with_job_runtime(jobs)`，让多个 managed Application 共同使用这些限制。默认运行并发 32、准入 1024；可按机器配置调整。

注入对象归宿主所有，单个 Application 或管理服务关闭不会关闭它。宿主应先关闭使用者，再 `await jobs.close()`。未注入时保留各 Application 自有实例，不能声称已有跨应用总额度。Desktop V2 当前单 Application 中的任务已共用现有 JobRuntime。

只有经过此 JobRuntime 的任务和输出受这些限制；插件私自创建线程/子进程、全进程 RSS、全部 Agent Run 队列与租户公平调度不因此受控。Scheduler 保持每个 Application 独立，避免不同 dispatcher 误领其他应用任务。
