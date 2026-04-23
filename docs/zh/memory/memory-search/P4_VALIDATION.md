# Memory Search P4 验证说明

这份文档记录当前 P4 阶段的 memory backend / strategy 演进工作。

## 范围

P4 建立在 P3 的 backend 拆分之上，继续把检索路径做成可配置、可诊断。

当前改进包括：

- `sagents/context/memory_backend_registry.py` 中共享的 backend 选择注册表
- session history / file memory 的统一 backend 解析优先级：
  - 显式参数
  - `agent_config`
  - 环境变量
  - 默认值
- `sagents/context/session_memory/session_memory_manager.py` 中的 session-history strategy 解析
- 支持以下新配置键：
  - `memory_backends.session_history`
  - `memory_backends.file_memory`
  - `memory_backends.session_history_strategy`
- 兼容以下旧键：
  - `session_memory_backend`
  - `file_memory_backend`
  - `session_memory_strategy`
- `SessionContext` 和 `MemoryTool` 上的运行链路透传
- `sage doctor` / `sage config show` 上的 CLI 诊断输出

## 测试套件

主回归测试：

```bash
python tests/sagents/context/test_session_memory_manager.py
python tests/sagents/tool/impl/test_file_memory_backend.py
python tests/sagents/tool/impl/test_memory_tool.py
python tests/app/cli/test_doctor_memory_backends.py
```

当前覆盖包括：

- backend 解析优先级
- strategy 解析优先级
- legacy 配置键兼容
- 不支持的 backend 拒绝
- 不支持的 strategy 拒绝
- session-history 在 `grouped_chat` / `messages` 之间的分发
- file-memory 在 `noop` / `scoped_index` 之间的选择
- `ToolManager` 级别的 `search_memory` 调用
- doctor/config 对 backend 和 session-history strategy 的诊断输出
- doctor/config 在 backend 或 strategy 非法时的结构化错误输出

## 推荐验证

建议在当前分支运行：

```bash
python -m py_compile app/cli/service.py sagents/context/memory_backend_registry.py sagents/context/session_memory/session_memory_manager.py sagents/tool/impl/memory_tool.py tests/app/cli/test_doctor_memory_backends.py tests/sagents/context/test_session_memory_manager.py tests/sagents/tool/impl/test_file_memory_backend.py tests/sagents/tool/impl/test_memory_tool.py
python tests/app/cli/test_doctor_memory_backends.py
python tests/sagents/context/test_session_memory_manager.py
python tests/sagents/tool/impl/test_file_memory_backend.py
python tests/sagents/tool/impl/test_memory_tool.py
python scripts/memory_search_validate.py --noise-files 30 --top-k 2
```

统一入口：

```bash
python scripts/memory_search_validate.py
```

## 说明

- P4 仍然保持当前 `search_memory` 的外部契约不变
- 这一阶段解决的是可配置性和诊断问题，还没有进入新的存储后端迁移
