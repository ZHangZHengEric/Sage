---
layout: default
title: 宿主控制接口
parent: 架构
nav_order: 20
lang: zh
ref: v2-detail-sagents-v2-host-controls
---

{% include lang_switcher.html %}

# Desktop 与 Server 标准控制接口核对

2026-10-19 对 Sage v2 的实际宿主入口和 SDK 调用链进行核对。

| 操作 | Desktop | Server | Sage 标准契约 |
| --- | --- | --- | --- |
| 启动任务 | `/api/v2/runs/stream` | `/api/agent`、包运行、外部 Run、A2A | `load_agent` 后通过 `entrypoint().run_stream` 或公开 `run_interface` 协议适配器进入同一标准执行链 |
| 审批、问答回复 | `/api/v2/runs/{run_id}/interactions/reply` | `/api/threads/{thread_id}/resume`、`/api/approvals/{run_id}/decisions`、外部 Run 的 `/reply` | `runtime.reply_interaction(ReplyInteraction, context)`；审批取消使用标准 `CancelRun` |
| 取消 | `/api/v2/runs/{run_id}/cancel` | `/api/threads/{thread_id}/cancel`、外部 Run 的 `/cancel`、A2A 取消 | `runtime.cancel_run(CancelRun, context)` |
| 主动暂停 | `/api/v2/runs/{run_id}/pause` | 当前没有独立手动暂停 HTTP 接口 | SDK 的 `runtime.pause_run(PauseRun, context)`，在安全点持久化暂停 |
| 继续暂停任务 | `/api/v2/runs/{run_id}/resume` | 线程 `/resume` 根据 suspension 区分普通暂停和交互 | 普通暂停先 `runtime.resume_run(ResumeRun, context)`；交互先回复；再 `agent_for_run` 和 `entrypoint().continue_run` |
| 进程重启恢复 | 标准 App、持久化版本和调度器 | 同左 | 恢复原 Run、Agent 图、配置快照和资源租约；无宿主恢复 Driver |
| 发布候选会话结果 | Run 的 `/commit-proposals`，提案的 `/publish`、`/reject` | 当前没有对应 HTTP 接口 | `entrypoint().propose_session_commit`、`publish_session_commit`、`reject_session_commit` |
| Goal/Plan 提交 | 声明对应标准工具后执行 | 同左 | 官方 Goal/Plan 工具及标准 continuation policy；区别于候选会话发布 |

表中 Desktop 路径均带 `/api/v2`。Server 外部 Run 路径前缀为 `/api/agents/{agent_id}/runs/{thread_id}/{run_id}`。Server 线程恢复请求的 `runId` 是新一段 AG-UI 观察流的标识，不是新建替代 Sage Run；Sage 的原生 Run 身份保持不变。

所有状态命令都需要经过认证的 `RequestContext`，以及契约规定的 revision 和幂等键。暂停并非立刻终止任意外部操作；取消请求、执行退出和资源释放也不是同一时刻。断开观察流使用 detach，不等于取消。多层共享沙箱的直接子 Run 恢复见[任务树恢复](sagents-v2-run-tree-recovery.md)。

`continue_run` 在已接受恢复时调度原 Run；如果相同 Run 已在执行，则只观察本轮后续事件；已终结的 Run 返回现有结果。重复继续不得创建新 Run 或重放已完成工具。仍在等待交互或普通暂停的 Run 必须先完成对应状态命令。

候选会话发布通过原 Run 的 Agent 版本执行。发布成功后才触发该版本启用的长期记忆写入；拒绝不会写入候选结果。原始 `runtime.publish_session_commit` 是底层状态协议，产品宿主使用标准 entrypoint 保留这些后续处理。

本次清除了 Desktop 预检失败创建占位 Run 的路径：受理前失败返回结构化 HTTP 错误，不伪造 Agent hash；已经受理的执行失败由标准 SDK 记录。保留原始错误分类、配额数据及本地化诊断。

Server 删除了旧模型身份绑定空实现、未使用的手动沙箱创建/释放链路；私有并发工具导入迁到公开 `sagents.v2.concurrency`。该模块只限制辅助 I/O/计算并发，不控制 Agent 执行。原 Server 前端命令与环境变量白名单迁为标准绑定的进程策略参数，用户显式字段覆盖产品默认值。前端镜像验收脚本也使用标准注册与执行流程。

宿主仍负责认证、目录与设置、协议和事件展示、产品完成回调，以及独立文件管理服务。这些通过公开能力协议和存储接口工作，不重建 Agent loop、官方工具运行时或 Team 执行器。受信任的原始 SessionStore 端口不替代面向调用方的 `session.access` 授权查询。

自动化验证包括 SDK 标准注册运行的提案发布/拒绝、记忆写入、原版本选择、重复恢复、暂停及权限隔离；Desktop HTTP 预检无占位 Run；两个宿主现有控制与重启回归。新增源码边界检查阻止宿主私有 SDK 导入、执行器装配、组件替换及直接 `provision()` 回流。

本机回归不等于真实连续数天运行或 Linux 镜像浏览器验收。前端镜像的 Chromium 既有失败记录仍保留，标准流程改写后需在候选 Linux 镜像重跑，不能用旧结果声明通过。

## 本轮验证记录

macOS、Python 3.13，原生沙箱测试在允许进程资源监控的环境执行。

| 范围 | 结果 |
| --- | --- |
| 首轮 SDK + Desktop + Server 联合回归 | 4186 passed、56 skipped；1 个原生 PATH 测试命中其 3 秒时限 |
| 最终 Desktop + Server、标准控制与上述 PATH 原样复核 | 900 passed、1 skipped |
| 最后 SDK 标准控制、Facade、dispatcher 生命周期专项 | 38 passed |
| Ruff、Python 编译检查、`git diff --check` | 通过 |

最终宿主回归命令包含 `tests/app/v2/desktop`、`tests/app/v2/server`、`test_standard_host_controls.py` 及 PATH 单项，结果存在重叠，不相加。首次时限失败在复核中通过，未放宽生产限制或测试时限。跳过项包含可选服务、平台及显式启用验收；最终宿主回归的 1 项为外部 MySQL 验证。

镜像验收脚本的本机测试实际走标准 Run、原生文件与 Shell，验证工具结果采集和越界拒绝；其 Linux 网络及浏览器命令替换为本机离线探针，只验证脚本链路。该测试不代表 Linux Chromium 已通过。
