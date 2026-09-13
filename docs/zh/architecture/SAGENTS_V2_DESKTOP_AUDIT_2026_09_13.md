# SAgents V2 与 Desktop V2 检查记录

日期：2026-09-13。工作区：`main`，基线 `657c5c85`，包含尚未提交的 Agent Management 实现。
当前修改范围包括 SAgents V2、Desktop V2 及相关测试、文档；不涉及监督学习闭环，旧 `app/desktop` 未修改。

## 检查结果

| 问题 | 触发与影响 | 修复和验证 |
| --- | --- | --- |
| Flow 插件选择错误 | 同一插件提供多个 `flow.node` 时，Builder 总取第一个 offer，忽略 manifest 选择的名称，导致错误节点运行或任务失败 | 将选择的名称传到扩展解析和 provider 获取；用首个 provider 故意不可运行的插件复现，再验证指定节点输出 42 |
| Agent 文本自动保存丢字段、可能写错目标 | 650ms 内编辑多个字段，共用 Timer 会取消前一个保存；切换 Agent 后回调读取的是已切换的控制器与目标 | 累积字段快照，使用独立的 Agent 防抖队列；切换、创建、删除 Agent 和关闭设置前等待文本保存；失败保留待保存内容。已用连续编辑、切换、关闭、慢请求与失败重试五项 widget 回归验证，修复包含在当前工作区 |
| Agent 构建互相阻塞 | 全局锁跨越异步 Builder 初始化，一个慢插件会阻塞其他 Agent/用户；重复初始化也需要协调 | 锁只保护索引；不同配置并行构建，同一配置共享一个初始化任务；容量统计包括在建实例；调用取消不取消共享构建，服务关闭等待并回收。新增并发、容量、取消和关闭组合测试 |

## Desktop 中已能确认的协作能力

当前 checkout 的前端具备 Team/Fibre 协作成员选择、子会话与执行过程展示，后端具备成员配置保存接口：

- `app/desktop_v2/lib/src/ui/settings_screen.dart`：协作成员配置及 Agent 设置。
- `app/desktop_v2/lib/src/ui/workspace/process.dart`：子会话树与过程展示。
- `app/desktop_v2/backend/catalog_service.py`：`available_sub_agent_ids` 校验和保存。

这些是已经存在的协作基础。当前源码检索尚未定位到独立 Studio 实体、群消息投递服务或以 Studio 命名的前端入口。
`DESKTOP_V2_STUDIO_DESIGN.md` 仍标注为提案，但不能仅据此推断所有协作界面都未实现；用户所指的具体 Studio 入口仍需对应到源码核对。

## 验证范围

- Desktop V2 Python 后端：168 项通过。
- Flutter analyze：通过。
- Flutter widget/unit 测试：202 项通过，含五项自动保存测试和三项请求乱序/生命周期测试。
- Agent Management 专项：33 项通过，含标准插件、多轮交互、持久化恢复和递归创建。
- SAgents V2 回归：2092 项通过、19 项跳过、1 项 deselect；另外排除两个依赖原生沙箱的测试文件。
- 排除文件为 `test_local_sandbox_resource_limits.py`、`test_local_workspace_sandbox_matrix.py`，单项为 `test_official_tool_provider_matrix.py::test_shell_and_todo_tools_use_v2_runtime_state`。当前外层沙箱不允许 macOS `sandbox-exec` 建立其沙箱，此前已在原始基线复现相关失败。这部分不能视为通过。

上述是本地离线运行时和前后端测试，不等于真实模型、多小时任务或原生桌面发布包的端到端验证。

## 下一步优化优先级（不需要监督学习）

1. **宿主集成**：把 Agent Management 的完整 package 配置、版本与运行状态接入 Desktop V2。当前运行时 opt-in API 已有，桌面 Agent 编辑器并不等同于完整 package 编辑器。
2. **实例回收**：管理服务目前最多缓存 32 个 application，没有空闲淘汰。需要可查询的活跃运行/引用计数后再做 LRU；不能在有 Run 或待回复交互时直接关闭实例。
3. **初始化成本**：验证完整 package 会构建其中每个 Agent；Flow 装配还可能创建不参与本次执行的模型。后续可按可达节点延迟装配，并把结构校验与宿主能力探测分开。缓存必须包含插件/模型绑定的版本，不能只按 package 内容缓存。
4. **设置一致性（已修复）**：全局设置已改为串行字段 PATCH，后端项目增删共用事务锁；Agent 读写版本与确认快照防止旧响应覆盖和错误回滚。关闭设置会提交防抖字段，保存失败保留页面。
5. **性能基准**：分别测量冷启动、热调用、并发排队、事件写入以及长会话内存占用，再确定容量默认值。这轮消除了一个已确认的串行瓶颈，尚无足够基准证明整个框架在所有负载下高效。
6. **生成插件接入**：已有标准扩展契约；自动生成源码后的构建、隔离验证和注册仍需宿主工作流。保存源码文件不等于插件已可运行。

结论：V2 已有可运行且覆盖面较广的框架基础；已保留运行时修复、初始化并发优化、前端自动保存和设置加载乱序保护。距离完整桌面自定义 Agent 工作流与经负载验证的长期运行框架，仍有以上具体工作。

## 远端核对

已执行 `git fetch origin` 与 `git pull --ff-only origin main`。远端 main 和当前 HEAD 均为 `657c5c85`（2026-09-13 09:30:58 +08:00），pull 返回 Already up to date。已获取的历史中 Studio 命名提交为 `9bf96b19`，内容是协作设计文档；尚未定位独立 Studio 前端实现所在的分支或 PR。

## 追加：设置加载与回复重试

- 设置目录请求与 Agent 选择请求使用独立的目录版本和共享的 Agent 请求版本。迟到的目录结果不会覆盖后选中的 Agent；A→B→A 的首个 A 请求也不能抢先结束最新加载状态。
- Controller 释放后，迟到请求不再更新状态或调用 notifyListeners。
- SAgents 管理回复遇到 run/suspension/interaction revision conflict 时，仅清除该次未接受的旧命令，且用命令内容条件比较避免删除并发重试的新记录。下一次相同答案重试会读取当前版本。已接受命令仍走原有幂等恢复。
- 用真实 SessionStore 在读取问题与提交回复之间推进 Run revision，验证首次拒绝后，同一个答案可成功重试并完成 Flow。

本轮 Flutter analyze、Ruff 和 git diff --check 通过；Desktop V2 后端 168 项、Flutter 202 项、V2 核心 2092 项通过。原生沙箱排除范围维持上述说明，没有将排除项计为通过。

## 追加：设置事务与失败清理

验证实例关闭失败时，管理服务保留 Application 与临时目录，后续 close 可重试。服务关闭或验证清理失败后保持 draining，拒绝新管理操作；清理失败不会恢复运行准入。新增两项故障注入回归，专项共 33 项。

Desktop V2 使用串行字段 PATCH 与单服务事务锁保护设置，关闭前提交工作区、预览与沙箱输入；Agent 失败回滚使用已确认快照。sidecar revision 为 6。后端 168 项、Flutter 202 项、核心 2092 项通过；原生沙箱排除范围不变。实现和剩余边界见 [整体审查](V2_COMPREHENSIVE_REVIEW.md)。

## 追加：运行时资源管理

已新增可选资源发现及严格准入、共享模型调用额度、显式空闲实例回收、Flow 可达成员装配。Desktop V2 的运行模型已共享额度。接入方式、测试与尚未覆盖的预算和产品流程详见 [运行时资源管理](SAGENTS_V2_RESOURCE_MANAGEMENT.md)。此前“没有回收”“全局模型额度待实现”等描述的当前状态以此文档为准；自动回收和全部资源的统一预算仍未实现。
