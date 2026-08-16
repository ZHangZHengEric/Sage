# Session Storage 抽象

`SessionStore` 是 Agent 会话持久化的统一边界。运行时、会话恢复、消息编辑、
统计和日志清理不应自行拼接 `session_root` 下的文件名。

对外只公开存储接口、配置模型和 `create_session_store()` 工厂。具体后端类及其
构造参数属于 storage 包内部实现，业务调用方不应导入。

## 数据语义

- Catalog：Session 定位、存在性和父子关系。
- Authoritative state：Session snapshot、message snapshot 和 message event。
- Derived state：compact manifest 和 tools usage。
- Telemetry：Session log、LLM request、request token usage 和 MCP calls。CLI 只能
  通过 Store 读取近期 Session log、查询后端健康状态，不得解析日志或 catalog 路径。

Message snapshot 与 event journal 共同构成消息账本。后端必须先持久化 snapshot，
成功后才能清理已纳入 snapshot 的 event。Filesystem 实现沿用既有的进程内锁，
保持原有并发行为。

## Filesystem 兼容契约

FilesystemStore 保持已有目录结构、JSON 字段、缩进、文件命名和写入行为：

```text
<session_root>/sessions_index.sqlite
<session_root>/<session_id>/messages.json
<session_root>/<session_id>/messages.journal.jsonl
<session_root>/<session_id>/session_context.json
<session_root>/<session_id>/compact_manifest.json
<session_root>/<session_id>/tools_usage.json
<session_root>/<session_id>/llm_request/*.json
<session_root>/<session_id>/tokens_usage/<request_id>.json
<session_root>/<session_id>/mcp_calls/<request_id>.json
<session_root>/<session_id>/session_<session_id>.log
```

子 Session 仍保存在父 Session 的 `sub_sessions/<child_id>` 下。Catalog 中仍存相对
路径，因此整个 `session_root` 可以移动。

## 注入后端

后端可以注入 `SessionManager`、全局初始化函数或 `SAgent`：

```python
storage_config = SessionStorageConfig(
    backend="filesystem",
    options={"root": "/var/lib/sage/sessions"},
)
agent = SAgent(
    session_root_space="/var/lib/sage/sessions",
    storage_config=storage_config,
)
```

不显式传配置时，工厂读取：

- `SAGE_SESSION_STORAGE_BACKEND`：默认 `filesystem`。
- `SAGE_SESSION_STORAGE_OPTIONS`：JSON object；filesystem 可配置 `root`。

如果 options 没有指定 `root`，工厂沿用现有的 `session_root_space`，所以旧调用方
无需修改。

新增后端应实现完整的 `SessionStore`，保证方法幂等性、同一 Session 内的写入顺序，
并为阻塞 I/O 提供线程安全实现。当前接口为同步接口；原本异步落盘的 LLM/MCP
调用仍通过工作线程执行，避免改变既有调用和错误处理语义。

`workspace` 相关方法是兼容现有 Session 元数据和运行时工作区的定位能力。非文件
后端可以返回稳定的逻辑 locator，但业务代码不得自行在 locator 后拼接文件名。
