---
layout: default
title: 权限与确认设计方案
parent: 架构
nav_order: 98
description: "面向工具、沙箱与多入口的权限分级、确认流与策略模型；设计草案，尚未在代码中落地"
lang: zh
ref: design-permissions-confirmation
---

{% include lang_switcher.html %}

# 权限与确认设计方案

> **状态**：设计草案，用于后续实现时对齐范围与验收标准；当前仓库**未**按本文全面落地。

本文对标业界 Coding Agent（如 IDE 内 Codex、终端向 Claude Code 等）中常见的 **分级权限** 与 **危险操作确认**，结合 Sage 分层架构（`sagents` 工具层、沙箱、Web/桌面/CLI 多入口）整理为可执行的方案蓝本。

---

## 1. 目标与原则

| 原则 | 说明 |
|------|------|
| **默认保守** | 未在策略中显式允许的敏感能力，默认 **拒绝** 或 **必须经用户确认**，而非静默放行。 |
| **最小权限** | 按 **资源域**（工作区读写、执行、网络、密钥等）拆分，避免「一个总开关」覆盖所有工具。 |
| **可解释** | 对用户展示 **自然语言归因**（例如将执行何命令、写何路径、是否出网），而非仅暴露内部工具名。 |
| **可审计** | 记录批准/拒绝、策略版本、与 `session` / `tool_call` 的关联，便于企业与自托管部署复盘。 |
| **可策略化** | 支持个人、仓库、组织多级策略；组织策略可覆盖个人配置。 |

---

## 2. 权限维度（建议）

以下类别用于 **策略匹配** 与 **UI 打标**；实现时可映射为枚举或字符串常量。

| 类别 | 含义 | 典型动作 |
|------|------|----------|
| **READ_WORKSPACE** | 读工作区 | 搜索、读文件、`git diff` |
| **WRITE_WORKSPACE** | 写工作区 | 写文件、应用 patch、`git commit`（可选再细分为子权限） |
| **EXECUTE** | 执行命令/脚本 | Shell、构建脚本；可再分子类：同步 / 后台 / 长运行 |
| **NETWORK** | 出站网络 | HTTP 客户端、MCP 外联、下载依赖 |
| **SECRETS** | 密钥与身份 | 读环境变量、`.env`、钥匙串、云元数据接口 |
| **ADMIN / DESTRUCTIVE**（可选） | 极高风险 | 大范围删除、`git push --force`、改全局 `git config`、系统级设置 |

**说明**：`EXECUTE` 与 `NETWORK` 通常是确认流中最频繁的两类；`SECRETS` 单独拆出，避免「读代码」路径意外携带 token。

---

## 3. 确认粒度

策略将动作映射到下列 **档位** 之一：

1. **静默允许**：仅限低风险（如已策略白名单的 `READ_WORKSPACE`，或明确前缀的只读诊断命令）。
2. **会话级一次性授权（session grant）**：用户声明「本会话内允许某类资源」，在会话结束或超时前对同类动作不再打断。
3. **按次确认（per invocation）**：每次越界调用前请求确认；支持 **短时间窗口内批量合并**（例如「将应用 3 处编辑，一次确认」）。
4. **拒绝 / 仅管理员**：企业策略锁死；UI 仅展示原因，不提供个人放行。

**批量合并**：同一轮对话中多个同类 `WRITE_WORKSPACE` 应可合并为单次确认，减少打断，同时保持可追溯的变更清单。

---

## 4. 策略模型（概念）

建议支持项目级文件（例如 `.sage/policy.yaml`）与远端/组织下发策略；以下为 **示意结构**，非最终实现。

```yaml
version: 1
defaults:
  read_workspace: allow
  write_workspace: ask
  execute: ask
  network: ask
  secrets: deny
rules:
  - when: { command_prefix: ["git ", "npm ", "pnpm "] }
    execute: allow_in_sandbox_only
  - when: { path_glob: ".env*" }
    read: deny
# overrides: 组织 OIDC / 管理台注入，优先级更高
```

**优先级建议**：`ORG > REPO > USER > 产品内置默认`。

**与沙箱联动**：若规则为 `allow_in_sandbox_only`，则执行路径 **必须** 使用强隔离沙箱（容器 / `bwrap` / Seatbelt 等）；若当前运行模式无法实现（例如误配为 passthrough），应 **拒绝执行** 而非静默降级。

---

## 5. 产品体验（多入口一致）

| 环节 | 建议行为 |
|------|----------|
| **首次进入会话** | 引导用户确认 **信任范围**（当前仓库根路径、是否允许网络、是否允许执行命令），并写入 session grant。 |
| **待执行卡片** | 展示权限 **分类标签**、**风险摘要**、可展开的 **完整命令/路径/是否出网**。 |
| **操作按钮** | 「仅本次允许」「本会话内允许同类」「拒绝」；高危项 **禁止** 「永久不再询问」。 |
| **CLI** | TTY 交互确认，或显式 `--yes` / `--policy-file`；CI/自动化必须 **显式** 传参，禁止隐式全开。 |
| **审计（企业）** | 记录 `user_id`、`session_id`、`tool_call_id`、策略版本、`decision`（allow/deny）。 |

**一致性要求**：Web、桌面、CLI 应共享 **同一套决策协议**（例如 pending → 用户决策 → 恢复工具调用），避免同一策略在不同入口行为分叉。

---

## 6. 技术落点（与 Sage 代码库的对应关系）

便于后续拆任务时快速定位；路径以仓库现状为准。

| 层次 | 落点思路 |
|------|----------|
| **工具统一门禁** | 在 `sagents/tool/` 内增加或前置 **PolicyGate**：输入归一化后的意图（路径列表、命令字符串、URL、是否触及 secrets），输出 `ALLOW` / `ASK_USER` / `DENY` 与 `reason_code`。 |
| **命令类工具** | `execute_command_tool` 等：在现有 `SecurityManager`（黑名单）之上叠加 PolicyGate；**黑名单作为硬底线，策略作为业务层**。 |
| **沙箱** | `sagents/utils/sandbox/`：沙箱类型选择与策略绑定；禁止在高风险策略下无声切换为弱隔离模式。 |
| **服务端** | 对匿名或弱鉴权 API，执行类工具默认 **拒绝** 或强制 API Key + 配额（需与网关/部署文档一致）。 |
| **前端** | `app/server/web/`、`app/desktop/ui/`：以协议形式接收「待确认」事件，用户操作后回传再继续流式任务。 |
| **MCP** | 各 MCP server 声明 **所需权限集合**；加载时与 session 策略求交，不足则禁用或触发询问。 |

---

## 7. 落地阶段（建议排期）

| 阶段 | 范围 |
|------|------|
| **P0** | 定义权限枚举、`reason_code`、PolicyGate 接口；先接入 **写文件**、**命令执行**、**出站请求** 三大类工具。 |
| **P1** | Session grant + 各端确认 UI/CLI；结构化日志或持久化审计。 |
| **P2** | `.sage/policy.yaml`（或等价）解析；组织策略下发；MCP 权限声明与校验。 |
| **P3** | 批量合并确认、摘要优化；与 SSO/企业审计系统集成。 |

---

## 8. 验收标准（自测清单）

- 任何 **写仓库 / 非沙箱执行 / 外联** 在无明示授权时均为 **询问** 或 **拒绝**，不得静默执行。
- 验证组织策略覆盖个人策略；沙箱能力与策略声明不一致时 **拒绝** 而非降级。
- 会话内 **同类低危** 可合并确认；**DESTRUCTIVE** 类不可配置为「永久记住允许」。
- 策略拒绝时向模型返回 **结构化信号**（例如 `POLICY_DENY`），减少无效重试。

---

## 9. 相关文档

- [工具与技能系统](ARCHITECTURE_SAGENTS_TOOL_SKILL.md)
- [沙箱、LLM 适配与可观测性](ARCHITECTURE_SAGENTS_SANDBOX_OBS.md)
- [服务端与 Web 应用架构](ARCHITECTURE_APP_SERVER.md)（鉴权与 HTTP 边界）
- 英文镜像：[Permissions & Confirmation Design](../../en/architecture/DESIGN_PERMISSIONS_AND_CONFIRMATION.md)

---

## 10. 修订记录

| 日期 | 说明 |
|------|------|
| 2026-05-11 | 初稿：权限维度、确认档位、策略示意、落点与阶段划分 |
