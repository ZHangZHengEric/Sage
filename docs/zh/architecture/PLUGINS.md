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

1. 使用 `builder.register(registration)` 注册实现，再用 `build(runtime=..., models=...)` 选择能力和参数。
2. 在 manifest 的 `runtime.capabilities` 中选择插件绑定。
3. 已有对象通过注册工厂返回，并明确所有权；runtime 负责选择，不另设对象注入入口。
4. 装配后检查 `application.resolved_plan`，宿主关闭时释放 Application。

已安装扩展可以通过 `sage.extensions` Python entry-point 发布。源码插件需要宿主显式信任与授权，属于宿主可执行代码，不是隔离机制。

## 插件不能重新定义什么

合法的生命周期转换、权威事件顺序和 Session 历史归属属于框架契约。插件只能声明自己实际提供的保证。使用数据库不自动获得跨进程订阅、分布式 claim 或持久 Job 能力。

[Manifest 配置](../CONFIGURATION.md) · [扩展契约](https://github.com/ZHangZHengEric/Sage/blob/main/sagents/v2/ARCHITECTURE.md) · [集成示例](https://github.com/ZHangZHengEric/Sage/blob/main/sagents/v2/使用手册.md)

## 实现与验证契约

SDK 标准能力和可选功能使用小写点分名，段内用连字符。例如 Skill 模块的读取接口注册为 `skill.provider`，搜索功能在该接口的 `CapabilityOffer.features` 中声明为 `skill.search`。Python 协议名 `SkillSearchProvider` 对应实现时的类型和方法签名。旧宿主的自定义能力 ID 仍可解析。

一个插件可以提供多个能力。每个已声明的标准能力都要满足对应 API 主版本的必需接口。注册时 SDK 校验标准功能名，装配时 `ExtensionHost.open_scope()` 和 `open_scope_sync()` 校验导出和成员，并在失败时回滚。可选功能只在声明或对应功能启用时检查。Server 和 Desktop 的模块问号读取同一份契约和插件声明。

Skill 插件至少实现 `list_skills`、`get_skill` 和 `fetch`。启用 `search_skills` 的 Package 还要求 `search_skills(query, *, run_id, allowed_names, limit)`，搜索实现先应用授权再取 Top K。需要发布时使用 `skill.management`，并检查实现是否支持 `skill.publish`。文件系统继续提供旧的管理接口绑定，发布标记为不支持。

第三方可从 `sagents.v2.runtime.extensions` 调用 `capability_contract_inventory()` 读取契约，从 `sagents.v2.testing` 调用 `check_provider_contract()` 检查结构。Skill、Tool、Model、Scheduler 和 Session Store 另有可复用的行为检查。测试使用隔离的存储或测试账户，调用方提供测试数据。插件登记的可选功能和持久化保证仍需要在对应部署环境验证。
