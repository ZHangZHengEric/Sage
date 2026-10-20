---
layout: default
title: Skill 保存管理与加载使用
parent: 架构
lang: zh
ref: v2-skill-management-and-usage
---

{% include lang_switcher.html %}

# Skill 保存管理与加载使用

对外分为保存管理和加载使用两组配置，内部保持标准 capability，不替换 Agent loop。
默认组合为 **filesystem + lazy + auto-sync**。

```yaml
skills:
  management:
    plugin: sage.skill.filesystem
    scope: process
    config:
      roots: [/srv/sage/managed-skills]
  usage:
    workspace:
      plugin: sage.skill.workspace.auto-sync
      scope: run
    loading:
      plugin: sage.skill.loading.lazy
      config:
        max_active_characters: 24000
```

这是 RuntimeConfig 输入；包内放在 `runtime` 下。分组在解析时展开为标准
`skill.management`、`skill.catalog`、`skill.workspace`、`skill.loading` 选择，
管理插件同时提供 `skill.source`。序列化只保存展开后的配置；分组和显式
capabilities 为同一能力选择不同插件时拒绝配置。

## 保存管理

| 插件 | 特点 |
| --- | --- |
| `sage.skill.filesystem`（默认） | 从 `roots/<名称>/` 读取，原件由目录或 Git 管理；Sage 发布接口只读，不保存历史版本 |
| `sage.skill.repository.sqlite` | SQLite 保存元信息、文件 BLOB、不可变版本和 Run 目录快照；事务发布，支持 `expected_version` 冲突检查 |
| `sage.skill.repository.memory` | 与 SQLite 相同的版本管理语义，全部在内存中，进程退出后丢失 |

`default_runtime(root)` 的 filesystem 来源为 `root/skills`。宿主已有的显式来源继续
使用，不自动迁移 Server 或 Desktop 的数据。SQLite 必填 `path`，两个版本仓库支持
`max_files`（默认 2000）和 `max_total_bytes`（默认 67108864）。

选择版本仓库的可信宿主可用 `app.service("skill.management")` 获取服务，调用
`publish(bundle, expected_version=...)` 和 `list_versions(name)`。发布不会自动作为
Agent 工具开放。多租户使用独立仓库路径或带授权的管理插件。

版本仓库在 Run 第一次查询目录时固定目录快照；SQLite 的记录可跨重启恢复。
需要接受时就固定版本的宿主继续使用接受快照，例如 Server frozen composition。
filesystem 不承诺历史版本恢复。管理器的历史保留策略与 Agent workspace 分开。

## 三种工作区策略

三种策略的实际路径都是 `skills/<名称>/`。例如 reference 的地址始终是
`/workspace/skills/demo/references/guide.md`，加载结果和模型上下文都提供这个根目录。
不向 Agent 提供按哈希排列的多份 Skill。

| 插件 | 行为 |
| --- | --- |
| `sage.skill.workspace.readonly-mount` | 由沙箱提供真正只读的挂载；文件 API 和进程都不能修改来源。不支持的沙箱明确报错，不退化为软链接或可写副本 |
| `sage.skill.workspace.auto-sync`（默认） | 检查本地修改，归档 Agent 侧内容，然后让当前目录完整匹配管理器下发版本 |
| `sage.skill.workspace.fixed-copy` | 第一次使用复制一份，之后保持本地副本；管理器更新不替换当前文件，Agent 的修改也保留 |

三个插件均为 Run scope，依赖 `execution.environment`，使用真实 sandbox 和签名授权。
无显式工作区选择时，SDK 在已有 Run 沙箱中装配 auto-sync；没有 Skill 的纯模型任务
不必额外获得沙箱。加载算法仍为 `sage.skill.loading.lazy`：发现目录不复制文件，
实际 load、预加载和用户选择才物化，活跃正文受字符预算约束。

## 自动同步的目录和更新规则

auto-sync 对支持 `CurrentSkillSource` 的来源调用 `fetch_latest`，每次显式加载都取得
已准入名称的当前管理器版本；filesystem、两个版本仓库和 Server catalog 均支持。
旧 Run 的允许名称边界不扩大。自定义来源如只实现 `fetch`，仍由该来源决定返回版本。

```text
workspace/skills/
  demo/
    SKILL.md
    references/guide.md
  .catalog/demo/
    state.json
    agent-edits/<content-hash>/
      files/...
      record.json
```

`state.json` 只保留当前来源信息、文件哈希和必要的同步中状态，不保存管理器旧版文件。
自动同步比较工作区文件与管理器上次下发的哈希：

- 工作区未修改，只有管理器版本变化：完整更新，删除来源中已移除的文件和空目录，
  不归档管理器旧副本。
- 工作区相对上次下发内容发生差异：视为 Agent 侧修改。先把新增、修改的文件及
  删除记录写入隐藏的 `agent-edits`，不复制未改动的管理器文件；
  归档成功后再同步管理器版本。
- 来源未变化，但 Agent 改过文件：下次显式加载也归档并恢复来源版本。
- 已有文件没有来源记录：无法证明是谁写的，按未跟踪本地内容保守归档再同步。
- 归档失败：保留当前文件，停止同步。
- 同步被中断：利用持久化的待同步文件哈希识别管理器的新旧混合状态；重试补齐，
  不把已完成的部分管理器更新误归档成 Agent 修改。

“管理器修改”和“Agent 修改”以独立来源和上次下发哈希区分，不是操作系统写入者审计。
管理器来源和当前工作目录必须分开；同一物理目录会被 auto-sync 拒绝，因为无法在
Agent 改写唯一原件后恢复管理器内容。

直接在 `skills/demo` 编辑不需要额外克隆。声明 `edit_skill` 工具并授予 `skill.load`
及 `skill.edit` scope 的宿主，可让 Agent 显式准备编辑目录。auto-sync 下次加载会归档
编辑并恢复管理器内容；fixed-copy 保留修改。归档不会自动成为 Skill 来源或发布版本。

## 并行、恢复和挂载边界

同一进程内，沙箱公开稳定的 `workspace_identity` 标识实际共享文件，Skill 插件以此
协调读者。相同版本可共同使用；其他 Run 还持有该 Skill 时，拒绝原地替换或同步，
待释放后重试。不同物理工作区不会互相阻塞。跨进程共享工作区需要宿主提供额外协调
或使用独立工作区；本实现不宣称分布式目录锁。

同步有待完成记录，但不宣称多文件事务或原子目录替换。Skill 路径只在同步完成后返回。
检查点恢复会验证已接受正文和内容，拒绝将已向前更新的共享目录降回旧版；需要同时
使用不同版本时，由执行层提供独立工作区。

只读挂载插件通过可选 `sandbox.skill_mounts` 的公开 `SkillReadonlyMountProvider`
契约调用后端，签名请求绑定目标、Run 和内容哈希。后端必须验证签名并对文件和进程
强制只读。当前内置 local、ephemeral、Cube 沙箱尚未实现此挂载端口，选择该策略会报
`skill.readonly_mount_unsupported`；支持挂载的宿主可按公开协议接入。

插件均通过 `builder.register(ExtensionRegistration(...))` 注册和配置选择。标准运行
入口保持 `build → load_agent → entrypoint().run_stream`。
