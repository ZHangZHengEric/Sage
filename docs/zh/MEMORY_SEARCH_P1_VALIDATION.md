# Memory Search P1 验证说明

这份文档记录当前 memory search P1 阶段的范围和可重复执行的验证命令。

## 范围

P1 主要解决搜索质量和稳定性问题，不改动更大的运行时架构。

当前改进包括：

- 多词候选召回优先使用 `AND`，再退回到 `OR`
- 文件排序综合考虑 query term 覆盖度、chunk 多样性、cohesion 和 span
- row 级 rerank 同时考虑路径 token 和内容 token
- preview 会跳过高度重叠的冗余 chunk
- tokenizer 扩展支持：
  - `snake_case`
  - `camelCase`
  - 中英混合查询
- 文件级和 chunk 级索引都包含路径和目录 token

## 测试套件

主回归测试：

```bash
python tests/test_memory_index_fts.py
```

当前覆盖包括：

- 精准 chunk 命中检索
- stale sidecar 清理
- 多 chunk 排序
- 多词覆盖排序
- chunk cohesion 和更紧凑的 span 优先
- 冗余 preview 抑制
- 标识符感知检索
- 目录 / 路径感知检索
- 更贴近 CLI / runtime 的真实 query
- 中英混合 query
- 中等规模的性能 sanity 检查

## Benchmark 脚本

```bash
python scripts/memory_search_benchmark.py
```

统一入口：

```bash
python scripts/memory_search_validate.py
```
