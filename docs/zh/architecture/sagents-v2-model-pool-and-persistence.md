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

MySQL 提交由协调器按已持久化事件数，仅序列化待追加部分，再交给原事务写入。完整快照导出默认仍输出完整历史。

若内存历史短于已持久化前缀，导出完整当前历史，由 SQL 事务删除旧记录后重建。删除 Run 的清理及成功提交后更新计数的顺序不变。串行 writer 连接仍顺序执行 SQL 事务，以保持写锁与提交一致性。

该优化减少事件的重复序列化，不消除会话元数据、命令结果和分叉基础事件的处理成本，也不提供分布式 writer。

## Redis 执行态与 MySQL 归档

配置 `SAGE_SERVER_REDIS_URL=redis://localhost:6379/1`，同时保留
`SAGE_SERVER_MYSQL_URL`，Server 会选择 `sage.session.redis-mysql`。未配置 Redis
时仍使用原 MySQL 实现。SDK Package 可以直接选择该插件，必填 `dsn` 和
`redis_url`；`table_prefix` 复用原表，`key_prefix` 默认根据数据库地址、库名和表前缀
生成，不含密码。托管 Package 的不同 MySQL 表前缀对应不同 Redis 命名空间。

每一步仍通过原 SessionStore 接口提交事件、版本号、恢复点和幂等结果，Redis 事务
原子追加增量及更新索引。Run 完成、失败、取消、挂起，或累计 32 次提交时，
同一事务登记待归档 Session。后台复用原有 session_mutations 和 run_events 表，
按连续 revision 分批归档，每批最多 32 条增量、目标不超过 256 KiB；单条不可分割
记录超过目标时单独处理。事件 SQL 批次最多 128 行，并同时按字节数拆分。每批事务
原子提交事件、增量、索引和版本；重试从 MySQL 已提交 revision 继续，不新增审计表。
归档期间发生新提交时，保留待归档标记，不清理新数据。

热提交不再每 256 次整包重写快照。后台归档后才压缩 Redis 快照，以最多 16K 字符
（UTF-8 最多 64 KiB）的块暂存，再原子发布快照指针并清除旧增量。读取期间遇到
压缩切换会重试；活跃会话的快照块与主记录一起保持无 TTL。已有整包 base 可读取，
首次归档仍需原子建立该旧 base，之后按增量提交。新快照布局要求所有 reader 同步升级。

JSON 重放与后台快照序列化在线程中执行；重放逐条校验变更行，最后构建一次整体状态，
避免逐条复制整个历史阻塞事件循环和续租。审批过期维护只投影候选 Run 的最新状态，
不为检查已结束会话而加载完整历史。

- 活跃和未归档数据没有 TTL。成功归档且所有 Run 均已结束或挂起后，Redis 缓存默认
  保留 3600 秒（`retention_seconds`）；后续读取可从 MySQL 重新加载。
- `archive_interval_seconds` 默认 1 秒；结束事件会立即唤醒后台归档。MySQL 写入失败
  会保留数据和重试标记。MySQL 冷读取、首次幂等查找仍依赖 MySQL 可用。
- 重启时从 Redis 的 resident 集合恢复未完成 Run；后台扫描持久化的 pending 集合
  补做归档。进程关闭时最多等待 5 秒归档，未完成部分交给下一次启动。
- 同一命名空间可由多个 Sage 实例访问，使用可续期的会话操作锁协调写入，
  支持跨进程事件订阅。调度器独立选择，启用共享存储不会自动启用多实例执行。
- 删除先在 Redis 原子写入 tombstone、删除查找索引，再异步删除 MySQL 数据。
  不确定的事务响应通过提交 token 确认；无法确认时，下一次读取重新加载权威状态。
- 派生缓存只存 Redis，可以重建。附件字节和引用一起进入 Redis，再随归档保存到
  MySQL；未归档字节不设置过期时间。

Redis 承担运行数据的持久化责任。启动会检查 `INFO memory` 的 `maxmemory_policy`
为 `noeviction`，以及 `INFO persistence` 的 `aof_enabled=1`，不满足则拒绝启用。
账号需要访问这些 INFO 信息。AOF 的 fsync 策略仍由部署管理：`everysec` 在 Redis
主机故障时可能丢失约一秒数据；需要更严格的落盘语义时使用 `always` 并实测延迟。
参见 [Redis 持久化文档](https://redis.io/docs/latest/operate/oss_and_stack/management/persistence/)
及 [redis-py 事务文档](https://redis.io/docs/latest/develop/clients/redis-py/transpipe/)。

切换存储模式前先停止接收新 Run，并等待执行中 Run 结束、待归档集合清空。不要在有
未归档数据时关闭 Redis 模式；修改 MySQL 地址同样会改变默认 Redis 命名空间，
应先排空旧命名空间，或明确保留原 key_prefix。不要让旧 MySQL writer 与新 Redis writer 同时使用
同一组表。本次代码不修改部署环境或迁移生产数据。

生命周期增量使用 `patches.runs` 记录小字段，不再重复序列化未变化的
`start_command` 和 `request_context`。首次创建和完整快照保留完整数据；回放合并
patch 后仍能还原请求、事件和恢复点。读取这些新增 journal patch 的所有进程都需
升级到支持 patch 的版本。

本地固定 60 KB 初始输入、200 次状态提交的合成基准，payload 中位数从 63650.5
字节降至 2736.5 字节，序列化中位数从 0.1984 ms 降至 0.0629 ms。该结果只证明
重复字段消除的收益，不包含 Redis/MySQL 网络、真实模型或端到端延迟。

## 分布式 SessionStore 与 Scheduler 插件

`sage.session.redis-mysql` 提供共享会话状态。Server 配置 MySQL、Redis 地址后，显式设置
`SAGE_SERVER_SCHEDULER_PLUGIN=sage.scheduler.redis-distributed`，启用分布式调度器
及独立命名的后台任务插件 `sage.job.redis-distributed`。Run 租约为 30 秒，
全局和用户并发额度共享，托管 App 使用独立执行队列。各节点须采用一致的数据库、
Redis、额度配置；托管存储根目录在各节点上须具有一致标识。默认选择保持原行为。

SessionStore 不持有进程级 owner。可续期的短期保护分别覆盖单次会话修改与
用户范围的请求幂等键，子会话创建和会话树删除还协调拓扑变化。Redis 事务在实际
提交时检查操作保护令牌和执行者令牌。本地缓存持会话锁刷新，元数据投影直接读取
共享状态。订阅默认每 100 毫秒按游标补读持久事件；逐字输出的共享 preview 缓冲
最多保留 2048 条、300 秒，过期或截断时明确返回 gap。归档复用原有 MySQL 表和
revision 事务，不新增审计表。已删除会话的 tombstone 在 Redis 中保持权威性。

Scheduler 通过 Redis CAS 原子更新有界共享队列快照。不同 App 的队列只领取本应用
工作项，额度统一计算。Run 修改期间阻止租约接管，存储事务拒绝已过期或被替换的
操作令牌。Dispatcher 会确认其他实例的完成状态，并周期补投已接受但未入队的 Run。
该实现面向有界队列的一致性，共享协调快照不代表无限调度吞吐。分布式存储和调度器
须使用同一 Redis 地址，分布式调度器要求共享存储支持提交时的执行者令牌检查；不匹配时启动失败。

合并后的插件保留原分布式版的默认 Redis 前缀
`sage:session:{<identity hash>}:distributed`、journal 格式及 MySQL 表。
升级前停止所有旧 writer。原分布式部署将插件 ID 改为 `sage.session.redis-mysql`，
并显式选择分布式调度器以保留多实例执行。原单写者部署须在所有实例上设置
`SAGE_SERVER_SESSION_STORE_KEY_PREFIX`（SDK 使用 `key_prefix`）为准确的原命名空间，
或者排空执行中 Run 和待归档数据后采用新默认前缀。MySQL 表前缀须保持一致。
托管 App 会在显式 Server 前缀后追加 `:managed_<app hash>`，原有托管命名空间须
逐个迁移或先排空待归档状态。旧、新 writer 不能同时运行；不自动复制命名空间、
保留旧插件别名或迁移生产数据。新 Job 插件通过 Redis CAS 共享任务状态、
字节输出游标、请求幂等及全局额度；取消请求由原节点执行，并在进程清理结束后发布终态。
节点租约默认 30 秒，失效后 Job 标为 `failed/job.worker_lost`，保留已有输出，不重放命令。
旧节点的输出和完成提交均须验证任务令牌及有效租约。终态输出有 TTL、重连窗口和容量上限，
节点关闭只停止自己持有的 Job。官方 Shell 工具按 Run 所有权授权跨节点查询和取消。

工作区跨节点插件暂不提供，也没有 `shared_workspace_root` 配置。本地记忆数据库、工作区文件
和沙箱进程仍需要对应的共享资源或所属实例路由方案，当前不能视为完整的跨节点部署。
进程故障不会迁移存活中的系统进程，租约接管也不保证外部工具
副作用恰好执行一次。

## 验证

项目要求 Python 3.12+。使用当前测试与基准核对行为，不将历史通过数量视作当前验收结果：

```bash
python -m pytest tests/app/v2/server/test_model_pool.py
python scripts/v2/benchmark_session_projection.py --events 10000 --repeats 10
python scripts/v2/benchmark_session_commit.py --commits 200 --input-bytes 60000
python -m pytest tests/sagents/v2/test_redis_mysql_session_store.py tests/sagents/v2/test_mysql_session_archive.py
```

模型池测试覆盖并发初始化、用户和凭据隔离、容量、失败、取消、缓慢淘汰及关闭失败。SQL 投影测试覆盖增量追加、没有新增、历史截断、删除 Run 与完整导出。模拟数据库连接的测试不等同于真实 MySQL 验收。

基准只计合成长事件列表的协调器序列化，不计 SQL、网络、模型或任务完成率；不能换算为生产 QPS。真实端点的长时间负载需要单独验证。

实现入口：[model_pool.py](https://github.com/ZHangZHengEric/Sage/blob/main/app/v2/server/runtime/model_pool.py)。
