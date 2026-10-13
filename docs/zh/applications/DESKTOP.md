---
layout: default
title: Desktop v2
nav_order: 2
lang: zh
ref: v2-applications-DESKTOP
parent: 应用入口
---

{% include lang_switcher.html %}

# Desktop v2

## 从源码启动

先完成 [Python 环境安装](GETTING_STARTED.md)，再安装 Dart 满足 `^3.12.2` 的 Flutter 和目标平台的桌面工具链：

```bash
cd app/v2/desktop
flutter pub get
flutter run -d macos
```

Windows 或 Linux 使用 `-d windows`、`-d linux`。应用自动启动托管 Python sidecar，通过本机回环地址、临时端口和 bearer capability token 连接。集成 PTY 终端目前支持 macOS 和 Linux。

## 第一个任务

1. 在设置中添加模型路由，填写协议、地址、模型 ID 和 API Key。
2. 为 Agent 选择模型，配置工具与 Skills。
3. 在 Agent Workspace 中开始对话，或注册项目目录。
4. 查看文件与工具进度，按需处理输入和审批请求。

模型路由支持 OpenAI Chat Completions、OpenAI Responses、Anthropic Messages 和 Gemini GenerateContent。配置并启用 MCP 连接后会发现对应工具。Studio 支持共享对话和定向成员消息。

接入 Gemini 原生接口时，选择 **Gemini GenerateContent**，将地址设为
`https://generativelanguage.googleapis.com/v1beta`，填写模型 ID 和 Google API Key，
检测能力后保存。插件支持文本和思考摘要流、Sage 工具调用，以及工具往返和 Session
重启后的推理签名回传。当前没有接入 Google 托管的搜索、代码执行工具。
推理等级、JSON 输出和媒体输入是否可用，以所选模型的能力检测结果为准。

## 数据与设置

| 路径 | 用途 |
| --- | --- |
| `~/sage/runtime` | 设置、catalog、会话索引与 Session 状态 |
| `~/sage/skills` | 导入的 Skills |
| `~/sage/agent_workspace` | 默认共享 Agent Workspace |

设置自动保存，模型和 Agent 配置不接受环境变量覆盖。源码调试时可给后端传 `--data-root /absolute/path`。注册项目仍使用各自的文件根目录。

Desktop v2 不导入 v1 数据。[Sage 2.0.0](https://github.com/ZHangZHengEric/Sage/releases/tag/v2.0.0) 安装包由 GitHub Actions 从 Flutter v2 客户端构建，包含 Python 与 v2 后端。旧 Tauri 发布仍属于 v1。macOS 包使用 ad-hoc 签名、未公证；Windows 包未做代码签名。

[组件参考](https://github.com/ZHangZHengEric/Sage/blob/main/app/v2/desktop/README.md) · [故障排查](../TROUBLESHOOTING.md)

## RSI 与 Agent 版本

参见 [RSI 流程、优化范围、独立审查与版本确认](RSI.md)。

## 交互式 UI 与演示文稿

源码运行还需安装 Node.js 22+，用于官方流式解析器；发布打包流程会将 Node 一起打包。

直接自然提问，例如“比较这三个方案”“做一个复利计算器”“制作四页产品介绍”。不需要提 OpenUI，也不需要编写协议。

- 单个普通聊天：打开输入框 **加号** 菜单，开启 **优先交互 UI**。
- 新聊天默认开启：在 **设置 → 通用 → 默认开启交互式 UI** 中启用。自动保存，初始关闭；已有聊天保留各自选择，分支聊天继承原聊天的选择。
- 开启后，宿主在模型首次响应前预加载完整 `sage-openui` Skill，无需调用加载工具。关闭时自动选择 UI 或文字；明确要求文字时按要求处理。

Sage 使用 [OpenUI](https://github.com/thesysdev/openui) 官方流式解析器和自己的 Flutter 原生 Glass 渲染器，支持深浅色和 31 类注册组件。每个收到的文本片段都会更新界面，实际逐 token 的粒度取决于模型服务。输入组件在验证与生成完成后可用；计算器和数字图表绑定在本地即时更新，纯本地交互无需提交按钮；只有需要交给助手继续处理的表单才提供按钮，将当前值作为下一轮消息发送。计算结果可继续用于其他计算和图表，依赖关系必须无循环。若最终校验失败，保留已生成的只读预览并标明未完成，禁止提交。

演示文稿支持原生 16:9 流式预览、翻页、缩略图和全屏演示。验证完成后从同一份数据导出可编辑 PPTX，可用 PowerPoint 或 Keynote 打开。幻灯片支持文字、指标、表格和静态数据图表，暂不支持旧 PPTX 导入、自由拖拽编辑或动画。这是 Sage 的原生接入，并非上游完整渲染器或 OpenUI Cloud Reports API；此前发布的安装包不含这些源码新增功能。

本地完成进度支持：`Computed` 的 `count` 对勾选项显式计数，`ratioPercent` 计算完成数 ÷ 总数 × 100；`Progress` 可绑定数值字段或计算结果。进度、指标和图表在输入变化时本地更新，无需提交。`sum` 不会隐式转换勾选数组，既有 `percent` 仍表示基数 × 百分比 ÷ 100。
