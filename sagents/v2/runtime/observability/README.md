# Observability

模块统一管理观测采集、证据查询和资源关闭。观测数据不参与 Session/Run 恢复，不能反向驱动执行状态，也不为审计扩展业务存储。

| 位置 | 职责 |
| --- | --- |
| `contracts.py` | 日志、Span、诊断采集和查询的稳定契约 |
| `provider.py` | 唯一后端选择入口、内部能力装配、资源所有权与关闭顺序 |
| `registrations.py` | `observability.provider` 的插件注册与配置 schema |
| `logs.py`、`log_format.py` | 结构化日志、关联上下文、过滤分发、格式化与脱敏 |
| `traces.py`、`content.py`、`timing.py` | 通用 Trace 生命周期、内容策略与计时辅助 |
| `evidence/` | 请求转换、诊断脱敏、原始证据传输/重建、模型/工具投影和快照拼装 |
| `performance/` | 与后端无关的性能缓冲、Trace 投影及耗时聚合 |
| `plugins/` | 日志输出、文件/SQLite 诊断、外部观测协议与查询实现 |
| `plugins/_shared/` | 后端共用的 OTLP 传输、查询预算与缓存 |

## 调用规则

宿主通过包入口创建 Provider；执行侧使用日志、Trace 和诊断采集契约。宿主查询使用：

- `export_evidence(session_id, run_ids)`：查询宿主已授权的 Run 集合，空集合不扩大查询范围。
- `list_model_requests(...)`、`get_model_request(...)`：模型记录查询。只有显式装配的本地历史读取器支持省略 Run 集合；此时宿主仍必须先授权 Session。
- `performance_available`、`report_performance(...)`：性能查询是否可用以及统一的异步报表入口。
- `trace_query`：可选的 `TraceQuery`，提供摘要、分页和详情；不支持时为 `None`。
- `close()`：由所有者调用；先刷入诊断及性能资料，再关闭 Trace 导出器和日志输出。

鉴权、HTTP 参数校验和页面导航留在宿主。宿主不导入具体后端类，不判断后端类型，不读取诊断数据库路径，不调用后端私有方法。Provider 的工厂负责把实际可用的查询能力装配到统一入口；文件诊断不提供性能报表，纯导出后端不伪造查询能力。

`evidence/` 与 `performance/` 不依赖 `plugins/`、HTTP 客户端或数据库。性能计算只接收规范化记录，SQL、索引、回填和后端分页位于相应适配器。不同适配器复用通用转换函数，不调用彼此的私有实现。

`evidence/assembly.py` 集中合并专用诊断记录、流式分片及丢失标记，后端只负责取数和附加采集状态。`performance/aggregation.py` 统一归一化内存记录和 Trace 解码后的记录，采集端直接计算摘要，不经 JSON 编码/解码往返。性能缓冲的状态推进与 Span 构建在同一实现文件内分开处理；日志过滤和分发集中在 `logs.py`。Provider 工厂与文件后端迁移继续保留在各自实现文件中。

运行与模型观测分别由 `agent/observed.py`、`model/middleware/recording.py` 在执行语义所在处产生；本模块负责承载、处理与查询这些观测。增加后端时应复用这些观测点。

## 维护

修改统计口径时检查本地与外部证据的计算一致性；修改采集链路时保留有界缓冲、数据丢失标记、取消和关闭顺序。后台采集失败不应中断业务执行，查询失败应明确返回不可用。

既有 SQLite 诊断索引的显式回填命令：

```bash
python -m sagents.v2.runtime.observability.plugins.sqlite.performance --backfill /path/to/evidence.sqlite3
```
