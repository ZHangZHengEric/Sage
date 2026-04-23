# Memory Search P3 验证说明

这份文档记录当前 P3 阶段的 session-memory backend 拆分工作。

## 范围

P3 主要把 session history 的具体后端实现从 manager / runtime 接线层里拆出来。

当前改进包括：

- `sagents/context/session_memory/backend.py` 中的 backend 契约
- `sagents/context/session_memory/bm25_backend.py` 中独立的 BM25 实现
- session memory 的 `noop` 占位 backend
- `sagents/context/session_memory/factory.py` 中的 factory 入口
- `SessionMemoryManager` 缩减成管理 / 代理层
- `SessionContext` 通过 factory 创建 manager，而不是直接写死一种实现
- file memory 这一侧也补齐了对应的 backend / factory 接线

## 测试套件

主回归测试：

```bash
python tests/sagents/context/test_session_memory_manager.py
python tests/sagents/tool/impl/test_file_memory_backend.py
```

统一入口：

```bash
python scripts/memory_search_validate.py
```
