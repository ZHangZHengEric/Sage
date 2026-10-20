# Server v2 会话分页与身份执行边界

`GET /api/threads` 和 `GET /api/admin/threads` 返回 `{items, next_cursor}`，默认 50 条、最多 200 条，按 `updated_at DESC, thread_id DESC` 查询。`cursor` 是上一页返回的游标；更换 `search` 或 `agent_id` 后必须从首页开始。标题、Agent ID 和匹配的 Agent 名称在数据库筛选后再取页。`GET /api/threads/{id}` 及管理员同名接口为历史深链接读取元数据，不必遍历所有列表页。

`GET /api/approvals` 返回 `{items, next_cursor}`，以线程主键游标扫描最多 `limit` 个候选，并先筛选暂停 Session；空的审批结果也可能含下一扫描游标。审批维护每轮扫描至多 200 条，进程内保存下一主键位置，到末尾后重头扫描，不新增业务存储。因维护轮次固定每分钟，历史量大时一整轮扫描需要多个周期；过期审批在决定入口仍会立即拒绝。

密码 hash/verify 使用专用 2 线程执行器，最多再排队 16 项，超出返回可重试 429。请求取消不会提前释放仍在执行的密码工作占用，关闭 Host 时等待已接收工作完成。

## 已存在数据库的索引迁移

新建 `threads` 表会带下列索引；启动流程只创建缺失表，不会自动修改既有表，也不删原索引。已有 MySQL 部署需由发布流程显式执行增量迁移，先检查 `SHOW INDEX FROM threads`，仅创建缺失的命名索引，并用实际列表查询 `EXPLAIN` 验证。应按数据库版本与线上表大小选择 DDL 窗口和在线建索引选项。

```sql
CREATE INDEX ix_threads_user_updated_id ON threads (user_id, updated_at, thread_id);
CREATE INDEX ix_threads_user_agent_updated_id ON threads (user_id, agent_id, updated_at, thread_id);
CREATE INDEX ix_threads_updated_id ON threads (updated_at, thread_id);
CREATE INDEX ix_threads_agent_updated_id ON threads (agent_id, updated_at, thread_id);
```

普通用户无筛选/指定 Agent 和管理员无筛选/指定 Agent 分别使用对应前缀。包含匹配的标题搜索仍需在已限定的所有者/Agent 范围进行文本扫描；当前方案没有引入全文索引或其他业务表。

回滚索引仅删除本次新建且确认无其他依赖的索引：

```sql
DROP INDEX ix_threads_user_updated_id ON threads;
DROP INDEX ix_threads_user_agent_updated_id ON threads;
DROP INDEX ix_threads_updated_id ON threads;
DROP INDEX ix_threads_agent_updated_id ON threads;
```

这次变更的 API/Web 需一起发布。分页过程中会话更新会使该会话移到更早页面；Web 追加时按 ID 去重，刷新首页重新获取当前排序。维护使用不可变主键顺序，不受更新时间变化影响。
