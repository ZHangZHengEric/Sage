# SAgents V2 重组后的实现说明

当前实现采用“领域模块化 + 微内核插件机制”。正式入口是：

```python
from sagents.v2 import SAgent, SAgentBuilder
```

## 最重要的边界

SAgents 不管理全局所有 Session。它只对一个已知 `session_id` 及其中的 Run
执行创建、恢复、CAS、事件、checkpoint、interaction、steering、fork 和删除。

以下能力属于 Desktop、服务端或其他上层产品：

- Session 列表、搜索、排序和分页；
- 用户维度索引；
- 标题、收藏、归档和标签；
- 跨 Session lineage 查询。

Desktop V2 的参考实现使用自己的 `session-index.json`。删除该索引不会损坏
SAgents 的 Session journal；索引写入失败也不应成为 Session 提交的一部分。

## 唯一权威来源

`FilesystemSessionStore` 为每个 Session 保存独立 `journal.jsonl`。它不建立全局
Session catalog，进程启动也不会把整个 store root 恢复成全局集合。已知
`session_id` 会直接打开对应目录。

`derived/` 只保存可删除、可重建的数据，例如 context summary 和 Skill 激活。
模型诊断由 `FilesystemDiagnosticSink` 保存，不能参与恢复。长期 Memory 由独立
`MemoryProvider` 管理，不能作为 Session 的第二份存储。

## 插件实现

`runtime/extensions/` 只包含 Descriptor、Registration、Registry、Resolver、Host
和 Scope。Model、Tool、Skill、Memory、SessionStore 和 Flow node 的实现都位于各自
领域的 `plugins/` 或实现目录。

Registry 保存真实 factory，而不是仅供 UI 展示的元数据。Builder 在启动时解析
一次插件和依赖，运行时只使用注入的接口。

## 阅读顺序

```text
sagent.py
→ builder.py
→ contracts/
→ runtime/kernel.py
→ runtime/session/
→ agent/
→ context/
→ model/
→ tool/
→ memory/
→ runtime/extensions/
→ package/
```

详细目录、生命周期、内置插件和第三方开发示例见
[`sagents/v2/README.md`](../../../sagents/v2/README.md)。
