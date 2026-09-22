---
layout: default
title: 应用入口
nav_order: 2
lang: zh
ref: v2-applications-README
has_children: true
---

{% include lang_switcher.html %}

# 应用入口

| 入口 | 环境要求 | 指南 |
| --- | --- | --- |
| Desktop v2 | Python 3.12+、Flutter、原生桌面构建工具链 | [桌面端](DESKTOP.md) |
| Server v2 | Python 3.12+、MySQL、Node.js 22.12+ | [服务端](WEB.md) |
| 嵌入式运行时 | Python 3.12+ 和模型服务 | [Python 快速开始](GETTING_STARTED.md) |

Desktop 与 Server 共用 SAgents v2，但分别管理身份、凭据、设置和会话索引。Desktop v2 不导入 v1 数据。旧脚本 `scripts/dev-up.sh` 不会启动 Server v2。
