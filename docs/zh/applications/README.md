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
| RSI 离线演示 | Python 3.12+ 与仓库依赖；无需模型密钥，评分为脚本预设 | [首次 RSI 运行](FIRST_RSI_RUN.md) |
| Desktop 安装包 | 对应系统的安装包，自带 Python 与后端；Linux 另需 GTK 和 bubblewrap | [桌面端](DESKTOP.md) |
| Desktop 源码 | Python 3.12+、Flutter、原生桌面构建工具链 | [源码启动](https://github.com/ZHangZHengEric/Sage/blob/main/app/v2/desktop/README.md) |
| Server 源码 | Python 3.12+、MySQL、Node.js 22.12+ | [服务端](WEB.md) |
| 嵌入式运行时 | Python 3.12+ 和模型服务 | [Python 快速开始](GETTING_STARTED.md) |

## 运行与改进

Desktop 用于交互使用、后台 RSI 和版本选择；Python API 用于自定义宿主与评测绑定。RSI 的输入、授权范围和版本采用方式见 [RSI 流程](RSI.md)。

Desktop 与 Server 共用 SAgents，但分别管理身份、凭据、设置和会话索引。Desktop 不导入 v1 数据，旧版启动脚本不适用于当前 Server。
