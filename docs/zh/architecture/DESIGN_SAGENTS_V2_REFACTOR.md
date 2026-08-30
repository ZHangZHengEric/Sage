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

模型诊断采用和 V1 相同的单一 provider-facing 视图：每条记录只保存一份实际
请求、一份规范化响应、请求 `kind` 及必要关联元数据，不再重复保存内部请求。
记录与所属 Run 放在同一个物理目录：
`sessions/<session_id>/runs/<run_id>/llm_requests/`。文件名为
`<8 位 index>_<kind>_<UTC 时间>.json`，因此按文件名排序就是模型请求的开始
顺序。LLM 请求不另建 diagnostics 树或 journal，且仍不参与 Session 恢复。首次
加载时会把旧 diagnostics 树中的请求移动到对应 Run，成功后清理旧空目录。

## 插件实现

`runtime/extensions/` 只包含 Descriptor、Registration、Registry、Resolver、Host
和 Scope。Model、Tool、Skill、Memory、SessionStore 和 Flow node 的实现都位于各自
领域的 `plugins/` 或实现目录。

Registry 保存真实 factory，而不是仅供 UI 展示的元数据。Builder 在启动时解析
一次插件和依赖，运行时只使用注入的接口。

第三方进程内插件通过 Python Entry Point 组 `sage.extensions` 发布，每个 Entry
Point 的名称必须等于稳定的插件 ID，目标必须是一个 `ExtensionRegistration`
对象。`sage.yaml.plugins` 是显式加载白名单：Builder 只导入清单中声明且尚未由
宿主手工注册的插件。声明中的 `config` 是插件默认配置，具体 runtime selection
中的配置优先。插件缺失、重复发布、ID 不一致或扩展 API 版本不兼容都会在构建
阶段以类型化错误失败。生产环境中的包安装仍由管理员或部署系统负责，manifest
本身不会执行 `pip install`。

## 多 Agent Server 托管

第三方 Server 通过公共 `AgentHost` 按
`(package_id, version, agent_id, manifest_hash)` 路由并缓存运行时。Registry 只需
实现 `AgentPackageSource.get(package_id, version)`，因此产品可以替换为自己的
数据库实现。Host 默认只接受已发布包、校验记录中的 manifest hash，并把权威包
身份写入 Run metadata；普通调用方不需要重复提交或解析 `sage.yaml`。

`AgentHost` 不拥有 HTTP、认证、租户归属、插件安装或持久化 Registry，这些仍是
嵌入它的 Server 的职责。相同 Agent 的并发首次请求只构建一次运行时；关闭或淘汰
缓存时只释放 `SAgentBuilder` 创建并拥有的资源，存在本地活动 Run 时拒绝关闭。

## 阅读顺序

```text
sagent.py
→ builder.py
→ agent/factory.py
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
