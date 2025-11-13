# Knowledge Base FastMCP (Python)

基于 Go 版 `knowledge_base_go` 重构的 Python FastAPI 异步实现，保持 API 契约一致。

## 快速启动

- 依赖：`fastapi`, `uvicorn`, `sqlalchemy>=2`, `aiosqlite`
- 环境变量：`KB_DB_URL`（可选，默认 `sqlite+aiosqlite:///./kb.sqlite3`）

```bash
python -m uvicorn mcp_servers.konwledge_base.main:app --reload
```

## 路由概览（对齐 Go 版）

- `POST /knowledge_base/search/kdb`
- `POST /knowledge_base/kdb/add`
- `POST /knowledge_base/kdb/update`
- `GET  /knowledge_base/kdb/info?kdbId=...`
- `POST /knowledge_base/kdb/list`
- `POST /knowledge_base/kdb/delete`
- `POST /knowledge_base/kdb/clear`
- `POST /knowledge_base/kdb/redoAll`
- `POST /knowledge_base/kdb/doc/list`
- `GET  /knowledge_base/kdb/doc/info?kdbId=...&dataId=...`
- `POST /knowledge_base/kdb/doc/addByZipUrl`
- `POST /knowledge_base/kdb/doc/addByUrls`
- `GET  /knowledge_base/kdb/doc/taskProcess?kdbId=...&taskId=...`
- `POST /knowledge_base/kdb/doc/taskRedo`
- `POST /knowledge_base/kdb/doc/delete`
- `POST /knowledge_base/kdb/doc/redo`

## 注意

- 当前版本已实现 KDB 与文档的异步CRUD与任务登记逻辑；搜索接口预留ES集成实现，暂返回空集合。