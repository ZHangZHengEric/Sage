---
layout: default
title: 任务树恢复
parent: 架构
nav_order: 21
lang: zh
ref: v2-detail-sagents-v2-run-tree-recovery
---

{% include lang_switcher.html %}

# Sage v2 多层子 Run 的标准恢复

标准流程允许直接继续一个已暂停的子 Run，祖先可以保持暂停。宿主不需要先驱动根 Agent，也不创建替代任务或手工 provision 沙箱。

## 公开调用

下面适用于显式暂停的 Run；审批或其他交互使用相应的标准 Interaction 回复接口。

```python
from sagents.v2.contracts.commands import ResumeRun

access = app.service("session.access")
run = await access.get_run(run_id, context)
suspension = await access.get_suspension(run.suspension_id, context)
agent = await app.agent_for_run(run_id, context)
receipt = await app.runtime.resume_run(ResumeRun(
    run_id=run_id,
    expected_revision=run.revision,
    suspension_id=suspension.suspension_id,
    expected_suspension_revision=suspension.expected_revision,
    idempotency_key=resume_request_id,
), context)
if receipt.decision.value == "accepted":
    future = await app.entrypoint().continue_run(run_id, context, agent=agent)
    result = await future
```

重建 App 后使用相同的注册实现和持久化状态目录，再调用相同流程。不需要先加载最新 Agent 来代替原版本。`agent_for_run` 找回原执行图的归档版本；标准 Driver 根据原 StartRun 的实际 Agent 身份选择图中的子定义，而非默认根入口。

## 资源依赖与租约

标准执行入口在装配 loop 之前，沿已授权的持久化父 Run 命令查找资源依赖，从最外层依赖到子 Run 获取租约。每层均使用各自受理时冻结的执行快照，不重新受理、不套用当前设置，也不执行祖先的模型或工具。遇到 `private_child` 后停止继续追溯更上层的工作区依赖；它的子成员恢复到这个私有工作区，不退回默认根目录。只读和较窄策略仍按原快照限制。

同一 Run 已有活动租约时，本地绑定提供者返回独立可关闭的附加 handle。需要恢复已释放子成员时，仅显式资源恢复路径可重建其成员租约；普通重复共享仍会拒绝。旧 handle 保持关闭，旧进程不重放。

恢复子 Run 持有必要祖先资源的引用，直到子绑定关闭。结束、取消或装配失败均先释放自身，再释放所持依赖；祖先仍有活动 handle 时不会被销毁。全部引用释放后结束物理环境，磁盘工作区保留供后续恢复。资源重建可产生新的 sandbox_id，原 Run、Session、执行配置身份和工作区边界保持不变。

这也适用于并发恢复：附加 handle 不共享取消所有权。插件实现 `ExecutionBindingProvider.acquire()` 时应遵守独立 handle、引用计数和 Run 归属契约，不应把同一个可关闭对象交给多个资源所有者。

## 错误与诊断

- `execution.parent_binding_not_ready`：资源依赖尚未获取，`retryable=true`、`safe_to_resume=true`。标准协调器自动获取所需依赖；直接绕过协调器调用本地 provider 时才可能遇到缺少父租约的情况。
- `execution.configuration_incompatible`：原快照、工作区、可信解释器或所需能力无法恢复。保持明确失败，不使用当前配置静默替代。

`app.execution_configuration(run_id, context)` 返回原快照；`execution_diagnostics()` 返回最近获取的 sandbox、解释器、能力及 `resource_dependencies`。依赖项包含原 Run ID、配置身份和实际沙箱租约。祖先仅重建资源时也更新诊断。诊断记录的是最近获取事实，不等于当前资源仍然活动。

恢复过程不派发已完成的子任务，不重放已完成的工具操作。未完成外部副作用继续遵守原工具的核对与恢复契约；资源重建本身不会重试它们。

## 自动化验证

`tests/sagents/v2/test_direct_child_recovery.py` 使用完整标准注册、加载和执行流程，覆盖三层全部暂停后从叶子开始恢复，以及关闭重建 App 后同样恢复。测试验证原 Run/Session/配置身份、实际角色指令与 Skill、祖先仍暂停、逐层资源依赖归属、原工具派发次数与最终释放。

`test_shared_sandbox_leases.py` 另覆盖恢复一个已释放子成员时仍活动的父成员继续读写；普通重复共享不放宽。

## 本轮验证记录

2026-10-19，macOS / Python 3.13：SDK 全量 3268 passed、55 skipped；Desktop 与 Server 联合 870 passed、1 skipped（外部 MySQL 未配置）；开发与冻结标准参考宿主媒体验收 4 passed。Ruff 和差异检查通过。租约故障注入另验证子快照损坏时回滚已获取祖先依赖，以及旧释放回执和旧 handle 不影响恢复后的租约。