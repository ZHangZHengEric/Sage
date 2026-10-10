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
