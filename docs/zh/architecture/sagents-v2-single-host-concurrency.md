---
layout: default
title: 单机并发
parent: 架构
nav_order: 9
lang: zh
ref: v2-detail-sagents-v2-single-host-concurrency
---

{% include lang_switcher.html %}

# v2 单机并发

## 提交与租约

一个应用进程可以交错处理多个用户和 Session 的模型请求、工具和持久化。内存及文件 Scheduler 的 `execute_fenced` 仅在检查、登记和清理租约保护时持有全局锁，实际存储写入保留对应 Run 的保护标记。

- 不同 Run 可以并行提交，同一 Run 顺序执行。
- 提交中的 Run 不回收、不取消或释放租约，不提前腾出租户名额。
- 写入期间可续租；进入保护区的写入保留原租约权威。
- 提交成功、失败或反复取消后清理保护标记；关闭等待已进入保护区的写入退出。
- 等待 claim 会在相关租约到期时醒来，不依赖其他请求通知。

文件调度器状态落盘仍是原子顺序写入，SQL SessionStore 的 writer 仍顺序执行事务。调度层减少跨 Session 串行等待，不改变存储自己的保证。

## Server 配置

Server 保持长驻 Application；普通聊天与 managed Applications 使用独立队列和共享 `SchedulerQuotaGroup`，总额度不随包数量成倍增长。

| 环境变量 | 默认值 | 作用 |
| --- | ---: | --- |
| `SAGE_SERVER_MAX_CONCURRENT_RUNS` | 8 | 正在执行的根 Run 总上限 |
| `SAGE_SERVER_MAX_CONCURRENT_RUNS_PER_USER` | 2 | 原子用户执行配额 |
| `SAGE_SERVER_MAX_PENDING_RUNS` | 1024 | 共享等待队列上限 |

以下是可调整的单机验收起点，不是容量承诺：

```dotenv
SAGE_SERVER_MAX_CONCURRENT_RUNS=32
SAGE_SERVER_MAX_CONCURRENT_RUNS_PER_USER=4
SAGE_SERVER_MAX_PENDING_RUNS=1024
```

模型限流或数据库成为瓶颈时应降低执行并发，观察排队与 P95/P99 延迟；增加队列长度不等于提高吞吐。直接使用 Builder 时，`execution.scheduler` 配置对应 `max_concurrent_runs`、`max_concurrent_runs_per_tenant` 和 `max_pending_items`。Job 额度见[资源管理](SAGENTS_V2_RESOURCE_MANAGEMENT.md)。

## 验证与部署边界

```bash
python -m pytest tests/sagents/v2/test_single_host_fencing.py
python scripts/benchmark_v2_single_host.py --sessions 64 --writes 8 --io-ms 2
python scripts/benchmark_v2_single_host.py --sessions 128 --writes 8 --io-ms 2
```

测试覆盖跨 Run 并行、同 Run 顺序、续租、回收、配额、取消、关闭和 Dispatcher → LeaseFencedSessionStore → SessionStoreCoordinator 协调路径。基准模拟慢异步存储，不包含真实模型或数据库；历史通过数量和合成延迟不是生产容量保证。

Server 仍要求单 worker。持久化、租约 fencing、进程内事件订阅及 JobRuntime 是不同保证；不能因使用 MySQL 就宣称支持多进程或多宿主执行。
