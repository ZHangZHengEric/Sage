# Memory Search P2 验证说明

这份文档记录当前 memory search P2 阶段的范围和验证命令。

## 范围

P2 主要稳定 `search_memory` 内部两条检索路径的边界：

- file memory retrieval
- session history retrieval

外部仍然保持现有的 `search_memory` 返回契约。

当前改进包括：

- 两个 retriever 都提供显式 `clear_cache()` 入口
- `search_memory` 在成功和失败路径上都返回稳定字段
- 回归测试覆盖：
  - file retriever cache reuse
  - file retriever stale refresh
  - session history cache reuse
  - session history 因 message / config 变化而失效
  - `ToolManager` 调用时 `session_id` 注入

## 测试套件

主回归测试：

```bash
python tests/sagents/tool/impl/test_memory_tool.py
```

统一入口：

```bash
python scripts/memory_search_validate.py
```
