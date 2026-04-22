# Memory Search P5 验证说明

这份文档记录当前 P5 阶段的 memory-search 收口与交付增强工作。

## 范围

P5 重点不是再改检索策略，而是把 P1 到 P4 的能力补成可提交状态。

当前改进包括：

- `sage doctor` / `sage config show` 在 memory backend 或 strategy 非法时也会返回结构化诊断，而不是直接崩溃
- 非法配置会落到：
  - `memory_backends.*`
  - `memory_strategies.*`
- `collect_config_info()` 会展示 memory 相关环境变量来源：
  - `SAGE_SESSION_MEMORY_BACKEND`
  - `SAGE_FILE_MEMORY_BACKEND`
  - `SAGE_SESSION_MEMORY_STRATEGY`
- `sage config init` 生成的 env 模板里会带上注释形式的 memory-search 可选覆盖项
- 统一验证入口已经纳入 CLI doctor/config 回归测试

## 测试套件

主回归测试：

```bash
python tests/app/cli/test_doctor_memory_backends.py
python scripts/memory_search_validate.py --noise-files 30 --top-k 2
```

当前覆盖包括：

- doctor/config 在 backend 和 strategy 正常值下的诊断输出
- doctor/config 在 backend 和 strategy 非法值下的结构化错误输出
- memory backend/strategy 相关 `env_sources`
- `sage config init` 模板中的 memory-search 覆盖项

## 推荐验证

```bash
python -m py_compile app/cli/service.py tests/app/cli/test_doctor_memory_backends.py scripts/memory_search_validate.py
python tests/app/cli/test_doctor_memory_backends.py
python scripts/memory_search_validate.py --noise-files 30 --top-k 2
```

## 说明

- P5 不改变 `search_memory` 的外部契约
- 这一阶段解决的是配置、诊断和本地验证的交付质量
