# Memory Search 验证总入口

这是当前 memory search 工作线的统一验证入口。

阶段说明分别在：

- `MEMORY_SEARCH_P1_VALIDATION.md`
- `MEMORY_SEARCH_P2_VALIDATION.md`
- `MEMORY_SEARCH_P3_VALIDATION.md`
- `MEMORY_SEARCH_P4_VALIDATION.md`
- `MEMORY_SEARCH_P5_VALIDATION.md`

## 当前范围

当前 memory search 线分成这些阶段：

- P1：搜索质量、排序、preview、标识符 / 路径感知
- P2：file memory 和 session history 的 retriever 边界稳定化
- P3：session-memory backend 拆分和 factory 接线
- P4：backend / strategy 可配置化和 CLI 诊断
- P5：诊断、配置模板和统一验证的交付收口

## 统一验证命令

```bash
python scripts/memory_search_validate.py
```

常用变体：

```bash
python scripts/memory_search_validate.py --noise-files 300 --top-k 5
```

这条命令会依次运行：

- 当前 memory-search 实现和测试文件的 `py_compile`
- `tests/sagents/tool/impl/test_memory_index_fts.py`
- `tests/sagents/tool/impl/test_memory_tool.py`
- `tests/sagents/context/test_session_memory_manager.py`
- `tests/app/cli/test_doctor_memory_backends.py`
- `scripts/memory_search_benchmark.py`
