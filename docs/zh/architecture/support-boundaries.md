---
layout: default
title: 当前支持范围
nav_order: 22
lang: zh
ref: v2-detail-support-boundaries
parent: 架构
---

{% include lang_switcher.html %}

# 当前支持范围

## 执行与部署

Desktop 是本机单用户宿主。Server 提供多用户接口，当前支持单 worker。内置调度器、Session 存储和后台任务不构成分布式运行时；SQL 持久化不提供多宿主任务接管。

## 隔离与资源

Session 隔离和临时目录用于分离上下文与文件，不能替代操作系统沙箱。工具权限、凭据、资源绑定和运行预算由宿主及其选择的 provider 执行。不能从本机进程执行推断容器级隔离或整个进程的统一内存上限。

## RSI 与恢复

Desktop RSI 当前面向 simple 类型和原生工具。Python 调用方负责提供可执行的评测绑定、隔离与授权。候选生成、推荐与应用是不同的步骤，应用由用户或调用方明确决定；不能从持久化进度推断自动断点恢复或不确定副作用的自动重试。

## 验证与容量

离线回归和小样本实验验证各自覆盖的行为。生产数据库、多租户长会话、目标平台发行包及故障恢复，需要对应环境中的测量；保留实测版本、负载、失败与成本记录。

[单机并发](sagents-v2-single-host-concurrency.md) · [本机沙箱约束](sagents-v2-local-sandbox-security.md) · [资源管理](SAGENTS_V2_RESOURCE_MANAGEMENT.md) · [RSI 流程](../applications/RSI.md)
