---
layout: default
title: 模型池与持久化
parent: 架构
nav_order: 8
lang: zh
ref: v2-detail-sagents-v2-model-pool-and-persistence
---

{% include lang_switcher.html %}

# v2 模型池与增量持久化

这一页解释两项独立优化：复用模型客户端，减少重复创建连接对象；只序列化新事件，减少长会话保存时的重复工作。它们都不改变会话内容，也不决定同时能运行多少任务。

## 有界模型客户端池

Server 宿主持有客户端，Run 借用租约。相同用户、模型记录、协议、地址、模型名和凭据复用客户端；不同用户或变更后的凭据使用不同条目。池键是这些字段的 SHA-256 摘要，不输出原始凭据。

- `SAGE_SERVER_MAX_MODEL_CLIENTS` 默认 64，必须为正数，限制客户端实例而非 HTTP 连接数。执行并发另由 Scheduler 限制。
- 同一配置的并发初始化合并为一次；单个等待者取消不取消其他 Run 共享的初始化。
- 完成、失败和取消都释放租约。仅无租约条目可按最近借用顺序 LRU 淘汰；正在关闭的条目仍计入容量。
- 池满且没有可淘汰条目时返回可重试限流错误 `server.model_pool_full`，不无限堆积等待者。
- 不使用定时 TTL；空闲客户端保留到淘汰或宿主关闭。凭据更新后的新 Run 使用新客户端，旧 Run 可继续完成。
- 关闭等待租约归还，再关闭客户端；调用者取消不打断后台清理，后续关闭可重新等待。清理失败会报错并停止接纳新客户端。
- 外部注入的 fallback 仍由原所有者管理。

根据活跃用户与模型配置数调整容量。增加执行名额而保持很小的客户端池可能只会增加限流。

## SQL 事件增量序列化

MySQL / PostgreSQL 提交由协调器按已持久化事件数，仅序列化待追加部分，再交给原事务写入。完整快照导出默认仍输出完整历史。

若内存历史短于已持久化前缀，导出完整当前历史，由 SQL 事务删除旧记录后重建。删除 Run 的清理及成功提交后更新计数的顺序不变。串行 writer 连接仍顺序执行 SQL 事务，以保持写锁与提交一致性。

该优化减少事件的重复序列化，不消除会话元数据、命令结果和分叉基础事件的处理成本，也不提供分布式 writer。

## 验证

项目要求 Python 3.12+。使用当前测试与基准核对行为，不将历史通过数量视作当前验收结果：

```bash
python -m pytest tests/app/v2/server/test_model_pool.py
python scripts/v2/benchmark_v2_session_projection.py --events 10000 --repeats 10
```

模型池测试覆盖并发初始化、用户和凭据隔离、容量、失败、取消、缓慢淘汰及关闭失败。SQL 投影测试覆盖增量追加、没有新增、历史截断、删除 Run 与完整导出。模拟数据库连接的测试不等同于真实 MySQL / PostgreSQL 验收。

基准只计合成长事件列表的协调器序列化，不计 SQL、网络、模型或任务完成率；不能换算为生产 QPS。真实端点的长时间负载需要单独验证。

实现入口：[model_pool.py](https://github.com/ZHangZHengEric/Sage/blob/main/app/v2/server/runtime/model_pool.py)。
