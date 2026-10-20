---
layout: default
title: 待实现与待验收
parent: 架构
nav_order: 22
lang: zh
ref: v2-detail-pending-work
---

{% include lang_switcher.html %}

# 待实现与待验收

## 待实现

| 范围 | 剩余内容 | 设计与当前边界 |
| --- | --- | --- |
| Desktop Agent 定制 | 完整 package、Flow、版本及运行管理界面；已有 Agent 设置页不等同于完整包管理 | [Agent 包管理](SAGENTS_V2_AGENT_MANAGEMENT.md) |
| Studio 协作 | Agent 间 request/result 自动派发、持久收件箱、依赖等待与恢复；群共享文件、版本化产物、Project 绑定及跨会话项目写协调 | [Studio 协作提案](https://github.com/ZHangZHengEric/Sage/blob/main/docs/archive/zh/architecture/DESKTOP_V2_STUDIO_DESIGN.md) |
| 宿主总预算 | 全进程内存限制、公平调度及插件自建线程/子进程的统一约束；共享模型额度、JobRuntime 和安全空闲回收已有实现 | [资源管理](SAGENTS_V2_RESOURCE_MANAGEMENT.md) |
| 分布式执行 | 适用于多进程、多主机的准入、调度、租约、订阅与持久 JobRuntime；增加 Server worker 数不能替代这些机制 | [单机并发边界](sagents-v2-single-host-concurrency.md) |
| 第三方存储冷读取 | 任意第三方 SessionStore 的通用离线终态读取；内置文件存储及终态归档已有实现 | [终态归档与读取](SAGENTS_V2_RESOURCE_MANAGEMENT.md) |
| 源码插件 | 自动依赖安装、隔离构建及非可信代码沙箱；当前仅允许宿主明确授权的进程内加载 | [插件与 Flow](SAGENTS_V2_AGENT_MANAGEMENT.md) |
| Server 控制接口 | 独立手动暂停及候选会话提案发布/拒绝的 HTTP 接口；SDK 已提供相应契约 | [宿主控制接口](sagents-v2-host-controls.md) |
| 远程技能导入 | 技能市场、私有仓库、独立 Git 地址入口、来源更新检查和团队 HTTP 目录；在线 ZIP 与 Skills CLI 已实现 | [远程导入方案](skill-import-proposal.md) |
| 只读 Skill 挂载 | 内置 local、ephemeral、Cube 沙箱的只读挂载端口；公开契约和选择策略已有实现 | [Skill 工作区边界](sagents-skill-management-and-usage.md) |

Studio 提案保留完整协作目标，其中前端首版和早期验证记录属于历史背景。当前已实现的宿主结果发布与补齐以源码为准，不再作为待办。

## 待验收与待复核

- 在真实模型、目标数据库、多租户和长会话下进行持续负载与故障注入，观测完成率、遗漏要求、尾延迟、内存、队列及取消后的资源释放。现有离线回归与小样本模型实验不能代替长期容量验收。
- Linux 冻结发行版、候选镜像中的 Chromium，以及 Windows/Linux 原生宿主仍需目标环境验收。文件存储已有 Windows 锁适配，不保留旧的“缺少 Windows 锁”待办。
- 旧重构验证中记录的 Flutter Studio 周期 Timer、日志队列同步等待超时，以及 Server `/studio` 测试受本地 Web dist 影响的问题需要复核。旧失败数量不代表当前结果，应以隔离环境重新执行的测试为准。

其他尚未落地的产品方向继续保留在原提案中：[AgentFlow 产品化](https://github.com/ZHangZHengEric/Sage/blob/main/docs/archive/zh/architecture/DESIGN_AGENT_FLOW_PRODUCTIZATION.md)、[权限与确认](https://github.com/ZHangZHengEric/Sage/blob/main/docs/archive/zh/architecture/DESIGN_PERMISSIONS_AND_CONFIRMATION.md)、[持续学习与 RSI](https://github.com/ZHangZHengEric/Sage/blob/main/docs/archive/zh/architecture/DESIGN_SAGE_RSI.md)。这些提案不作为当前接口参考，实现范围见对应产品文档。
