# SAgents V2 与 Desktop V2 整体审查

日期：2026-09-13。范围：当前工作区代码，包括尚未提交的修复与 Agent Management 实现。旧 Desktop 不在修改建议范围内，不涉及监督学习闭环。

## 当前交付状态

已完成此前复现的设置一致性、失败清理、资源发现、模型限流、实例使用计数与容量回收、Flow 可达成员装配。本轮集中补齐：

- 跨 managed Application 注入共享 JobRuntime，复用已有并发、准入与输出限制，保持宿主资源所有权。
- 内置文件存储未归档终态的冷读取：不初始化模型，不修改源存储，仍验证完整性与读取权限。
- 宿主显式授权的源码插件：统一 ExtensionRegistration 契约，完成编译、校验、注册、流程执行和生命周期清理。
- Desktop V2 创建时可提交完整现有 AgentSettingsPatch；复制保留配置并创建独立身份，界面复制前等待待保存编辑。
- Agent 创建、修改、删除共享服务事务锁，避免并发字段丢失；有效 max_loop_count 不再被运行时静默截到 200，统一支持至 10000。sidecar revision 为 7。

这些改动提供 Agent 定制与单进程并发的工程基础，不代表模型权重进化。完整 package/Flow Studio、非可信源码隔离与自动依赖安装、全进程 RSS 限额、公平调度、第三方历史适配和真实模型长时压测仍未完成。Windows 原生后端仍需单独验证。旧 Desktop 未修改，也没有加入监督学习闭环。

以下保留问题复现与设计依据；实现状态以本节及文末最终验收为准。

## 一、已修复的问题（保留原复现与建议）

P1 表示优先修复，涉及持久配置丢失或运行时生命周期失效；P2 表示需要修复的状态一致性问题。

| 优先级 | 问题与复现结果 | 源码位置 | 建议 |
| --- | --- | --- | --- |
| P1 | **全局设置旧写覆盖新写**：先保存 dark，再保存 light，让后发请求先完成，最终 UI 和模拟持久状态均回到 dark | [saveSettings](../../../app/desktop_v2/lib/src/state/workspace_controller.dart:779)、[_saveDesktopSettings](../../../app/desktop_v2/lib/src/ui/settings_screen.dart:119) | 后端使用 revision/CAS 或原子字段 PATCH；前端串行提交并使用本地编辑版本保护 draft。仅保护读取响应不能解决写入覆盖 |
| P1 | **项目增删存在读改写竞争**：并发新增 A、B，两个调用均成功，最终只保存一个项目 | [add_project / remove_project](../../../app/desktop_v2/backend/workspace_service.py:143)、[save_settings](../../../app/desktop_v2/backend/workspace_service.py:118) | 读取、变更、写入必须处于同一事务或条件更新中。现有锁只保护最后写文件，不能防止不同调用基于同一旧快照计算结果 |
| P2 | **旧读取覆盖已经成功的 Agent 修改**：开始读取 A 的设置，随后成功 PATCH 新名称，最后旧读取返回，UI 恢复旧名称 | [loadSettingsCatalog](../../../app/desktop_v2/lib/src/state/workspace_controller.dart:819)、[patchAgentConfiguration](../../../app/desktop_v2/lib/src/state/workspace_controller.dart:932) | 读取与写入使用一致的版本规则；目前读取请求版本与 `_agentPatchRevision` 相互独立 |
| P2 | **失败回滚使用了未确认的乐观状态**：连续提交名称、描述修改，两次均失败，界面仍保留第一次从未保存成功的名称 | [_sendAgentPatch](../../../app/desktop_v2/lib/src/state/workspace_controller.dart:952) | 分离服务端已确认快照与待提交 patch；失败后从确认快照重算界面，不能把前一次乐观对象当作回滚基线 |
| P1 | **验证实例关闭失败后失去清理入口**：注入 close 抛错的验证 Application，validate 抛错后，service.close 成功，但只尝试过一次 close，没有保留待清理实例 | [_validate_agent](../../../sagents/v2/agent/management/service.py:147) | 验证资源也要加入宿主持有的清理队列；关闭失败时保留对象与目录，后续可重试并提供诊断。临时目录生命周期需与资源释放绑定 |
| P1 | **关闭失败后服务重新接受不可用实例**：给真实 Application 注入一次性关闭失败；service.close 失败后清除自身 closing 标记，仍返回同一个 Application，但 entrypoint 报 `SAgentApplication is closing` | [管理服务 close](../../../sagents/v2/agent/management/service.py:494)、[Application close](../../../sagents/v2/application.py:259)、[_application](../../../sagents/v2/agent/management/service.py:249) | 采用明确的 draining / cleanup_failed / closed 状态；不可把已经部分关闭的实例放回可运行缓存。清理重试与任务准入分开 |

复现方式：Desktop 使用可控响应顺序的 Flutter fake API；项目竞争使用真实 WorkspaceServiceMixin 方法和初始化屏障；运行时使用真实管理服务并注入关闭故障。它们验证的是具体代码路径，不是线上发生频率。

## 二、静态确认的遗漏

### 1. 关闭设置丢失部分防抖输入（已修复）

关闭设置现在会取消防抖计时器、等待在途请求，并提交仍未保存的工作区、预览限制与沙箱路径。验证或保存失败时保留设置页并显示错误。三个 Widget 回归分别验证立即关闭后的持久值。

### 2. Windows 默认文件存储需要明确支持边界

[FilesystemSessionStore 的 writer lock](../../../sagents/v2/runtime/session/plugins/filesystem.py:647)在 `fcntl` 不可用时直接报 `session_store.lock_unsupported`。
如果 Windows 使用该插件，就需要 Windows advisory-lock adapter 或选择实际可用的存储实现；存在 Windows Flutter runner 并不能证明后端运行链路已可用。本轮未运行 Windows，属于条件性的兼容性缺口。

## 三、Agent 定制还缺哪些基础能力

| 优先级 | 缺口 | 证据与建议 |
| --- | --- | --- |
| P1 | **资源就绪性（资源发现层已实现）** | 已复现：包声明不存在的 Tool 和 Skill，普通宿主工厂仍得到 `valid: true`。现有返回文案确实只承诺结构、组合和 provider 初始化，因此这是就绪性缺口，而不是证明它绕过了权限。现已提供 validate(readiness=True) 和宿主 require_readiness=True；返回缺失 Tool、Skill 或无法验证的绑定。真实模型调用、凭据有效性和 Skill 实际物化仍不在检查范围内 |
| P1 | **宿主总预算（模型调用额度已实现）** | [Dispatcher](../../../sagents/v2/runtime/execution/dispatcher.py:64)限制的是单个实例；管理服务的 build semaphore 仅约束初始化。现可注入跨 Application 共享的 ModelConcurrencyBudget；Desktop V2 的主模型和辅助模型共用额度。已可注入共享 JobRuntime 复用任务并发、准入和输出限制；全进程内存与租户公平调度仍待统一 |
| P2 | **空闲 Application 回收（显式与容量触发均已实现）** | [_application](../../../sagents/v2/agent/management/service.py:249)达到 max_applications 就拒绝；历史版本持续占位。现有 host-only release_idle 按最久未使用优先回收，阻止并发管理准入，并检查持久化中全部非终态 Run。暂停、子 Run、未知或损坏状态不作为空闲；现已默认在容量不足时回收超过 300 秒未使用的安全实例，可配置或关闭；没有定时扫描 |
| P2 | **历史结果读取（终态归档路径已实现）** | [status](../../../sagents/v2/agent/management/service.py:335)会获取 Application。重启后即使仅查看已完成结果，也可能初始化模型、工具并占用缓存；插件不可用会影响历史读取。现已在终态查询、回收前和正常关闭前归档结果；归档命中时只查库存并重新授权。内置文件存储未归档终态现已支持冷读取；第三方通用接口仍待实现 |
| P2 | **定制能力尚未产品接入** | 当前 Desktop V2 backend 未找到 AgentManagementService / with_agent_management 接入。已有 Agent 设置页不等于完整 package、版本、运行和管理工具界面。需要一条复用现有服务的端到端集成路径，并显示宿主支持能力 |
| P2 | **源码插件已有可信宿主加载路径** | 已实现显式授权源码的编译、标准注册与实际 Flow 执行；自动依赖安装和非可信代码隔离仍未实现 |

## 四、效率优化应基于什么数据

1. **Flow 按可达图装配（已实现）**：[composition_members](../../../sagents/v2/builder.py:670)此前在 Flow 模式下遍历包内其他全部 Agent，为不参与本次运行的成员初始化模型。现已按边、并行 branches、subflow 和成员 subagents 求保守可达集合；回归验证只初始化入口与可达模型。完整包 validate 仍逐个验证所有 Agent。
2. **冷启动与验证成本分开测量**：重复保存已去重，但新版本、显式验证、运行装配仍各有成本；按插件种类记录耗时和常驻资源，而不是只测 mock 模型吞吐。
3. **存储规模基准**：覆盖长 Session、多版本、多文件、事件积累后的查询和关闭时延；本轮没有证据支持把整个存储层描述为高效或低效。
4. **长时间故障注入**：慢/失败插件、写满磁盘、强制退出、取消风暴、模型断流、持续多小时运行；测量峰值内存、队列长度、资源回收与 P95/P99。
5. **运行中可观测性**：区分 validation queued、building、ready、run queued、suspended、cleanup failed；暴露容量、等待原因与清理失败对象，避免模型只看到一个泛化异常。

原生沙箱测试仍受当前外层环境限制；必须在真实目标环境补齐，不能用被排除的用例推断沙箱能力合格。

## 五、建议实施顺序

1. **设置事务与状态管理**：一次解决全局设置覆盖、项目增删竞争、读写版本、回滚和关闭前 flush；补真实后端并发与 Flutter 交错测试。
2. **生命周期修复**：验证资源清理队列、部分关闭状态、失败后的准入规则；再建立实例引用计数。
3. **就绪性与统一预算**：明确合法、已保存、可执行的差别；把所有 managed Application 纳入宿主资源控制。
4. **回收与按需装配**：在生命周期可靠后实现 idle release / LRU、只读历史与 Flow 可达图装配。
5. **Desktop 完整接入与插件工作流**：用已稳定的服务完成创建、版本、能力检查、运行和恢复；之后再扩大能力范围。

这个顺序优先消除数据丢失和资源状态错误，再提高性能和产品完整性。

## 复现材料

本轮复现脚本和结果保存在临时目录，未将其加入产品测试套件：

- `/private/tmp/sage-review-probes.py`：验证清理、关闭失败复用、缺失资源验证。
- `/private/tmp/sage-project-probe.py`：并发新增项目丢失。
- `/private/tmp/sage-desktop-review-probe-source.dart`：三项前端交错复现源码。
- `/private/tmp/sage-desktop-review-probes.log`：前端复现输出。

这些临时文件不应作为长期回归资产；实施修复时应把对应“期望正确行为”的断言纳入正式测试，而非保留断言当前错误行为的审查探针。

## 最终验收

本次最终工作区回归：

| 检查 | 结果 |
| --- | --- |
| SAgents V2 | 2137 passed、19 skipped、1 deselected |
| Desktop V2 Python | 172 passed |
| Desktop V2 Flutter | 204 passed |
| Flutter analyze | 无问题 |
| Python Ruff / git diff --check | 通过 |
| 授权源码插件离线示例 | Flow 返回 meters=2000 |
| 旧 app/desktop 差异 | 无 |

核心回归另排除 `test_local_sandbox_resource_limits.py`、`test_local_workspace_sandbox_matrix.py` 两个文件，并 deselect `test_official_tool_provider_matrix.py::test_shell_and_todo_tools_use_v2_runtime_state`。当前外层环境限制原生沙箱执行，排除项不计为通过。未进行真实模型、多小时压力测试或 Windows 实机验证。

新增回归覆盖未归档冷读取不启动模型且不写源文件、跨应用共享任务准入与资源所有权、源码插件实际运行与模块清理、授权拒绝，以及语法/导出/身份/版本/built-in 声明错误后的无残留清理。桌面测试覆盖完整配置创建与复制、非法创建无孤立记录、并发更新、实际循环预算以及复制前保存编辑。

正式回归资产包括 Agent Management matrix、模型并发预算、Desktop 设置事务与 Agent 定制测试，以及 Flutter API/Widget 回归。
