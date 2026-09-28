---
layout: default
title: 资源管理
parent: 架构
nav_order: 4
lang: zh
ref: v2-detail-SAGENTS_V2_RESOURCE_MANAGEMENT
---

{% include lang_switcher.html %}

# v2 运行时资源管理

## 宿主接入

```python
from sagents.v2.agent.management import AgentManagementService
from sagents.v2.model import ModelConcurrencyBudget

budget = ModelConcurrencyBudget(limit=8, max_waiting=128, wait_timeout_seconds=60)
service = AgentManagementService(
    root,
    builder_factory=build_package,
    authorize=authorize_package,
    model_budget=budget,
    require_readiness=True,
    auto_release_idle_seconds=300,
)
report = await service.validate(bundle, context, readiness=True)
reclaimed = await service.release_idle(min_idle_seconds=300, limit=4)
metrics = service.capacity()
```

此片段要求宿主提供 root、bundle、context 和回调。所有相关服务与 Builder 必须共享同一个 budget；普通 Builder 用 `with_model_budget(budget)`。没有注入共享对象就没有跨 Application 总额度。

## 资源就绪性

`validate(readiness=True)` 查询 Tool 与 Skill 目录，返回 readiness.ready、missing_tools、missing_skills、unverified。valid 表示结构、组合与 provider 初始化通过，可能同时有 `valid=True` 和 `readiness.ready=False`。

`require_readiness=True` 阻止缺失或无法验证资源的保存和新 Run。同 ref 重复保存及缓存实例也重新验证，返回本次真实报告和 reused=True；这会产生初始化与清理成本。默认关闭严格模式。`agent_package_validate` 也支持 readiness=true。

检查不调用模型、不执行工具、不物化 Skill。必须在真实 Run 中才能验证的绑定标记为 unverified，严格模式拒绝。凭据有效性、远端执行及 Skill 内容可加载仍需单独探测，资源发现不能扩大授权。

## 模型额度与排队

`ModelConcurrencyBudget` 限制同时进入 provider 的流与显式能力探测，名额覆盖流的完整生命周期，失败、取消和提前关闭归还名额。等待工具或递归创建 Agent 不占用模型名额。provider 内部并发请求不一定各占一个额度。

默认最多 128 个等待请求、等待 60 秒；max_waiting=0 只接纳可立即开始的调用。等待超时不截断已进入 provider 的调用。队列满返回 model.queue_full，等待超时返回 model.queue_timeout，均为可重试且可恢复的 RATE_LIMITED；上游 TimeoutError 不冒充队列超时。已有等待者优先，取消不泄漏名额。

snapshot() 返回 limit、active、waiting、max_waiting、wait_timeout_seconds、rejected、timed_out。额度限同一事件循环，不限制 token、全进程 RSS、工具子进程、网络带宽或全部 Run 队列。

Desktop 默认 max_concurrent_model_calls=8、max_waiting_model_calls=128、model_queue_timeout_seconds=60，缓存的运行模型 provider 共用额度。直接 API 限流返回 HTTP 429；Agent 运行保留现场并进入现有恢复交互，可 retry 续接。独立模型验证接口不因此拥有完整宿主资源限制。

## 安全空闲回收

release_idle 是宿主接口，按最后使用时间回收，最多 limit 个。管理操作持有实例使用计数，包括查询、提交、控制及等待构建；在用实例不回收，取消释放计数。

存储必须声明 durable_across_process_restart=True 并支持 has_nonterminal_runs()。检查包括排队、运行、暂停和子 Run，未知及内存存储跳过。文件存储扫描未加载 Session 和 journal，损坏时报错；扫描在后台线程中进行。关闭失败保留实例并进入 draining，后续 close 可重试。

容量满时默认尝试回收闲置 300 秒的安全实例；auto_release_idle_seconds=None 关闭自动回收，0 允许立即回收。无安全候选则返回容量错误。没有定时后台扫描。回收关闭资源、删除缓存，保留持久文件；运行或续接可重新装配同版本。

服务必须独占管理 Application，宿主不能绕过它提交。capacity() 返回缓存、构建、在途操作、使用计数、自动回收、清理与模型额度统计，不作为跨租户模型工具公开。

## 终态归档与读取

status 观察到终态、回收前及正常关闭前，将结果和 Flow 输出写入库存归档。默认 AgentPackageStore 使用 SQLite terminal_statuses；Server 的库存实现使用 MySQL managed_agent_records。回收与关闭按最多 100 条分页处理未归档操作。

读取先检查调用者归属与当前 read_run 授权。已归档结果不需要 Builder、模型客户端或 worker。归档失败仍释放正常关闭资源；自动回收在归档成功后才关闭实例。

SessionStore 仍是权威源。崩溃前可能尚未归档，内置文件存储可只读加载快照和 journal，验证校验和、Session 身份与授权，补归档终态。未终态、旧记录缺少位置及不支持离线读取的存储使用恢复装配路径；不会缓存未终态为最终结果。

## Flow 与共享 JobRuntime

Flow 可达集合包括条件边、并行 branches、subflow 和成员 subagents，通过访问集合终止循环。只为入口及可达成员初始化模型；显式包验证仍检查所有 Agent。

`InMemoryJobRuntime` 默认运行并发 32、准入 1024，并限制单任务输出字节/分块及聚合保留输出。通过 `AgentManagementService(..., job_runtime=jobs)` 或 `SAgentBuilder().with_job_runtime(jobs)` 共享同一对象。

共享 JobRuntime 归宿主所有；先关闭使用者，再 `await jobs.close()`。未注入则每个 Application 各有实例，不具备跨应用总额度。Scheduler 队列保持应用隔离，避免 dispatcher 误领其他应用任务。

## 验证与边界

测试覆盖就绪检查、资源消失、共享额度、取消、流失败、暂停保留、回收重建、持久状态、损坏与关闭失败。参见[Agent 包管理](SAGENTS_V2_AGENT_MANAGEMENT.md)和[单机并发](sagents-v2-single-host-concurrency.md)。

尚不承诺全进程内存限制、跨进程公平调度、任意存储的离线读取、非可信源码隔离安装或真实模型长时间容量。插件自行创建的线程和子进程不因共享 JobRuntime 就受到控制。
