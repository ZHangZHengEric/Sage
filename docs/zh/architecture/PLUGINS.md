---
layout: default
title: 插件架构
nav_order: 1
lang: zh
ref: v2-architecture-PLUGINS
parent: 架构
---

{% include lang_switcher.html %}

# 插件架构

## 哪些能力可以替换

模型、Session 存储、记忆、工具 catalog 与 executor、Skill 加载、上下文压缩、调度、后台任务、沙箱、协议适配器和可观测性 sink 都有明确的扩展边界。

`ExtensionRegistration` 声明身份、能力/API 版本、配置 schema、依赖、作用域及创建真实实现的工厂。扩展内核负责依赖解析、配置校验、启动失败回滚，以及按依赖逆序关闭组件。

## 宿主如何组合实现

1. 用 `SAgentBuilder().with_defaults(...)` 接入标准实现。
2. 在 manifest 的 `runtime.capabilities` 中选择插件绑定。
3. 通过 `with_model_provider`、`with_session_store`、`with_tool_runtime` 等 Builder 方法注入宿主持有的实现。
4. 装配后检查 `application.resolved_plan`，宿主关闭时释放 Application。

已安装扩展可以通过 `sage.extensions` Python entry-point 发布。源码插件需要宿主显式信任与授权，属于宿主可执行代码，不是隔离机制。

## 插件不能重新定义什么

合法的生命周期转换、权威事件顺序和 Session 历史归属属于框架契约。插件只能声明自己实际提供的保证。使用数据库不自动获得跨进程订阅、分布式 claim 或持久 Job 能力。

[Manifest 配置](../CONFIGURATION.md) · [扩展契约](https://github.com/ZHangZHengEric/Sage/blob/main/sagents/v2/ARCHITECTURE.md) · [集成示例](https://github.com/ZHangZHengEric/Sage/blob/main/sagents/v2/使用手册.md)
