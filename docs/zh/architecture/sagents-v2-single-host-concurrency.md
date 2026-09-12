# SAgents V2 单机并发

本轮优化针对一个应用进程内的多用户、多会话 Agent 并发。运行中的网络请求、工具和不同会话的持久化可以交错执行；同一 Run 的状态提交与租户配额仍保持一致性。

## 消除跨会话串行等待

原来的 `execute_fenced` 在 SessionStore 写入期间一直持有 Scheduler 全局锁。即使 SessionStore 本身按会话分锁，不同 Run 的写入仍被调度层串行化，其他 worker 的 claim 和心跳也会等待。

现在内存及文件调度器均只在检查、登记和清理租约保护时持有全局锁。实际写入期间保留对应 Run 的保护标记：

- 不同 Run 的提交可以并行，同一个 Run 的提交依然顺序执行。
- 正在提交的 Run 不会被回收、取消或释放租约，其租户额度也不会提前腾出。
- 心跳可以在写入期间续租；已进入保护区的写入持续持有原租约权威。
- 提交结束或失败后清理保护标记；反复取消也不会留下永久锁定状态。
- 关闭调度器会等待已进入保护区的写入退出。
- 等待 claim 会在相关租约到期时自动醒来，不依赖另一个请求产生通知。

文件调度器自身的状态落盘仍是原子的顺序写入；SQL SessionStore 的写连接仍顺序执行事务。本轮消除的是调度层对所有 SessionStore 的额外串行限制，并未改变这些存储的持久化保证。

## Server 并发配置

Server 现在将以下环境变量传递给 Scheduler 和 Dispatcher。保持一个长驻 Application，在同一进程中处理多个并发请求即可。

| 环境变量 | 默认值 | 用途 |
| --- | ---: | --- |
| `SAGE_SERVER_MAX_CONCURRENT_RUNS` | 8 | 正在执行的根 Run 总上限 |
| `SAGE_SERVER_MAX_CONCURRENT_RUNS_PER_USER` | 2 | 每用户执行上限，映射到原子租户配额 |
| `SAGE_SERVER_MAX_PENDING_RUNS` | 1,024 | Scheduler 等待队列上限 |

例如，可在目标机器和模型限额允许时，以以下配置开始单机验收：

```dotenv
SAGE_SERVER_MAX_CONCURRENT_RUNS=32
SAGE_SERVER_MAX_CONCURRENT_RUNS_PER_USER=4
SAGE_SERVER_MAX_PENDING_RUNS=1024
```

这组数值是可调起点，不是所有机器的最佳值。不要将增加排队上限等同于提高吞吐。模型限流或数据库成为瓶颈时，应降低执行并发，观察队列等待与 P95/P99 延迟。

直接使用 `SAgentBuilder` 时，在 `execution.scheduler` 的插件 config 中使用 `max_concurrent_runs`、`max_concurrent_runs_per_tenant`、`max_pending_items`。Job 的执行、接纳和输出预算见[资源审查报告](sagents-v2-efficiency-quality-audit.md)。

## 验证与复现

`tests/sagents/v2/test_single_host_fencing.py` 对两种调度器验证跨 Run 并行、同 Run 顺序、续租、过期回收、配额、取消与关闭。另有完整协调路径测试：64 个 Run、8 个用户、16 个执行名额，每用户 2 个名额，经过 Dispatcher → LeaseFencedSessionStore → SessionStoreCoordinator，验证达到 16 个并行提交，所有 Run 完成且每个会话的事件序列连续。测试用等待闸门模拟慢存储；不包含真实模型调用。

运行可复现的调度锁基准：

```bash
python scripts/benchmark_v2_single_host.py --sessions 64 --writes 8 --io-ms 2
python scripts/benchmark_v2_single_host.py --sessions 128 --writes 8 --io-ms 2
```

同一实现中复现原全局锁算法作为基线。每个 Run 执行 8 次模拟 2 ms 异步写入，本地一次结果：

| Run 数 | 原总耗时 | 新总耗时 | 原 / 新写入 P95 | 原 / 新并行写入峰值 |
| --- | ---: | ---: | ---: | ---: |
| 64 | 1,185.73 ms | 21.55 ms | 153.00 / 3.41 ms | 1 / 64 |
| 128 | 2,251.92 ms | 19.98 ms | 298.05 / 2.94 ms | 1 / 128 |

这验证了跨 Run 锁等待的消除；计时波动会使两个并发档位的耗时不严格单调。该基准不代表真实数据库速度、模型吞吐或生产 QPS。

最终 V2 / Desktop / Server 联合回归：**2,329 passed、20 skipped、6 warnings，37.76 秒**。本轮还启用并通过了默认关闭的 100 会话、30 秒持续并发测试。跳过项主要是未配置的真实模型、MySQL / PostgreSQL、专用 Linux 资源控制环境；已有告警来自间接导入的旧依赖弃用接口。修改的 Python 文件 Ruff 检查及 `git diff --check` 均通过。
