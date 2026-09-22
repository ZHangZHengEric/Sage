<div align="center">

# 🌟 **体验 Sage 的强大能力**

![cover](assets/cover.png)

[![English](https://img.shields.io/badge/Language-English-blue.svg)](README.md)
[![简体中文](https://img.shields.io/badge/语言-简体中文-red.svg)](README_CN.md)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg?logo=opensourceinitiative)](LICENSE)
[![Python 3.12+ (v2)](https://img.shields.io/badge/Python-3.12%2B%20(v2)-blue.svg?logo=python)](https://python.org)
[![Version](https://img.shields.io/badge/Version-1.1.0-green.svg)](https://github.com/ZHangZHengEric/Sage)
[![DeepWiki](https://img.shields.io/badge/DeepWiki-查看文档-purple.svg)](https://deepwiki.com/ZHangZHengEric/Sage)
[![Slack](https://img.shields.io/badge/Slack-加入社区-4A154B?logo=slack)](https://join.slack.com/t/sage-b021145/shared_invite/zt-3t8nabs6c-qCEDzNUYtMblPshQTKSWOA)

# 🧠 **Sage 智能体平台**

### 🎯 **让复杂工作走向可靠交付**

> 🌟 **面向项目工作、工具执行与多智能体协作的开源平台，支持桌面端、Web 与自建应用。**

</div>

---

Sage 让 AI 智能体进入实际工作的现场。连接项目，配置模型与工具，从提出任务到文件修改、工具执行和结果检查，在同一个工作区中与智能体协作。

你可以通过桌面端处理本地工作，通过 Web 应用提供多用户访问，也可以将 Python 运行时嵌入自己的产品。Sage 基于 MIT 许可证开源。

## 从对话走向实际工作

**让智能体围绕项目工作。** 在一个桌面工作区中组织对话、项目文件、执行进度和终端。从共享 Agent Workspace 开始，或连接已有项目目录，在智能体执行过程中查看文件与产出。

**把专业能力沉淀为可复用的 Agent。** 选择模型，定义指令，组合内置工具、Skills 和 MCP 连接，让同一套配置服务于后续任务。也可以通过 `sage.yaml` 定义 Agent 包，集成到自己的应用中。

**在协作中保留可见性与控制权。** 实时查看模型输出和工具活动，按需暂停 Run、补充输入、处理审批或取消执行。Desktop Studio 让多个 Agent 在共享对话中通过定向消息协作；Server Studio 进一步提供 Agent 包编辑、不可变版本、执行历史和结果查看。

**按自己的需求扩展底层能力。** SAgents v2 将智能体运行时与宿主应用分离，为模型、存储、记忆、工具和调度提供明确的扩展接口。你可以沿用现有应用，也可以构建自己的界面与业务流程。

## 用 Sage 开展工作

| 工作场景 | Sage 如何支持 |
| --- | --- |
| 代码与项目任务 | 连接项目，让 Agent 通过配置的工具读取和修改文件，同时查看执行过程与结果。 |
| 可重复的专业任务 | 将指令、模型、Skills 和工具组织成 Agent，在后续任务中复用。 |
| 多智能体协作 | 为 Studio 成员分配不同职责，通过定向消息将任务交给相应成员。 |
| 自建智能体产品 | 嵌入 SAgents v2，自行提供界面、身份认证、凭据和工作区策略。 |

Desktop v2 的模型路由支持 **OpenAI Chat Completions**、**OpenAI Responses** 和 **Anthropic Messages** 协议。Skills 提供可复用的工作流程，MCP 连接将外部工具接入智能体的可用能力。

## 选择使用入口

| 入口 | 适用场景 | 代码与指南 |
| --- | --- | --- |
| Desktop v2 | 在本地工作区中处理对话、项目、文件和智能体任务 | [Flutter 桌面端](app/desktop_v2/README.md) |
| Server v2 | 通过多用户 Web 应用管理模型、Agent、Skill 和 MCP | [服务端与 Web 客户端](app/server_v2/README.md) |
| SAgents v2 | 将智能体运行时嵌入自己的应用 | [运行时指南](sagents/v2/README.md) |
| 旧版应用 | 使用已有 Desktop、Web、CLI、TUI 和 Chrome 扩展 | [应用指南](docs/zh/applications/README.md) |

仓库同时保留两代实现。SAgents v2、Desktop v2 和 Server v2 需要 **Python 3.12+**；旧版应用的 Python 基线为 3.10+。Desktop v2 使用独立的设置和数据布局，不导入 Desktop v1 数据。不同入口的能力和配置方式以各自文档为准。

## 快速开始

### 准备源码环境

以下命令适用于 macOS 或 Linux 的 POSIX shell：

```bash
git clone https://github.com/ZHangZHengEric/Sage.git
cd Sage
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

Windows 下使用 `py -3.12 -m venv .venv` 创建环境，并在 PowerShell 中运行 `.venv\Scripts\Activate.ps1` 激活。

### Desktop v2

安装支持目标桌面平台的 Flutter，其内置 Dart SDK 需要满足 [pubspec.yaml](app/desktop_v2/pubspec.yaml) 的约束（`^3.12.2`）。完成上面的 Python 环境准备后，运行：

```bash
cd app/desktop_v2
flutter pub get
flutter run -d macos
```

Windows 或 Linux 使用对应的 `-d windows` 或 `-d linux`，并安装该平台所需的原生构建工具。集成 PTY 终端目前支持 macOS 和 Linux。

应用会自动启动本机 Python sidecar。在设置中添加模型路由，填写协议、服务地址、模型名称和 API Key，再为 Agent 选择该模型。随后可以在共享 Agent Workspace 中开始对话，或注册项目目录，围绕项目文件开展工作。Skills 和 MCP 连接按需添加。

Desktop v2 将运行数据和设置保存在 `~/sage/runtime`，导入的 Skills 保存在 `~/sage/skills`，默认共享工作区为 `~/sage/agent_workspace`。Agent 和模型配置在应用内管理，不通过环境变量覆盖。

工作区行为、配置和开发检查见 [Desktop v2 指南](app/desktop_v2/README.md)。如需安装包，请查看 [Releases](https://github.com/ZHangZHengEric/Sage/releases) 中对应版本的说明；仓库现有桌面发布工作流面向旧版 Tauri 应用。

### Server v2

Server v2 需要 MySQL，以及兼容 Vite 7 的 Node.js（可使用 Node.js 22.12+）。在仓库根目录、已激活 Python 环境的终端中运行：

```bash
python -m pip install -e '.[server-v2]'
cp app/server_v2/.env.example app/server_v2/.env
```

启动前编辑 `app/server_v2/.env`：

- 将 `SAGE_SERVER_MYSQL_URL` 设置为实际 MySQL 连接地址。
- 将 `SAGE_SERVER_JWT_SECRET` 设置为自己的密钥，至少 32 字节。
- 通过 `SAGE_SERVER_ADMIN_USERNAME` 和 `SAGE_SERVER_ADMIN_PASSWORD` 设置初始管理员账号。

构建 Web 客户端并启动服务：

```bash
cd app/server_v2/web
npm install
npm run build
cd ../../..
python -m app.server_v2
```

打开 [http://127.0.0.1:8090](http://127.0.0.1:8090)，使用配置的管理员账号登录，添加模型和 Agent。API 文档位于 `/docs`，Agent 包管理入口位于 `/studio`。

Server v2 当前使用**单 worker** 运行。事件回放直接读取 Sage Session 的权威 RuntimeEvent；MySQL 持久化不代表运行时已支持横向扩容。配置和部署边界见 [Server v2 指南](app/server_v2/README.md)。

### 嵌入 SAgents v2

使用 `SAgentBuilder` 加载 Agent 包并创建 `SAgentApplication`。宿主负责提供模型凭据、用户身份、工作区访问权限和工具执行环境。

```python
from sagents.v2 import SAgentApplication, SAgentBuilder
```

[运行时快速开始](sagents/v2/README.md#quick-start) 提供完整的 `sage.yaml` 和可运行的 Python 示例；[集成使用手册](sagents/v2/使用手册.md) 详细介绍能力选择和配置方式。

### 已有应用

旧版入口仍可使用，具体安装和配置见各自指南：

| 应用 | 使用方式 |
| --- | --- |
| Web | 在仓库根目录运行 `./scripts/dev-up.sh`，见 [Web 指南](docs/zh/applications/WEB.md)。该脚本启动旧版应用栈。 |
| Desktop | 查看 [发布包](https://github.com/ZHangZHengEric/Sage/releases) 和 [桌面端指南](docs/zh/applications/DESKTOP.md)。 |
| CLI | 配置模型后使用 `sage doctor`、`sage run` 或 `sage chat`，见 [CLI 指南](docs/zh/applications/CLI.md)。 |
| TUI | 安装和启动命令见 [终端指南](docs/zh/applications/TUI.md)。 |
| Chrome 扩展 | 将 `app/chrome-extension/` 作为已解压扩展加载，并连接后端，见 [扩展指南](docs/zh/applications/CHROME_EXTENSION.md)。 |

## 系统组成

```text
Desktop v2（Flutter + 本地 FastAPI）    Server v2（Web + 多用户 API）
                   \                    /
                      SAgents v2
              Agent 包 · Session · Run
          模型 · 工具 · Skills · 上下文 · 记忆
              存储 · 后台任务 · 沙箱 · 事件
```

**Session** 保存持久化的对话历史；**Run** 表示 Session 中的一次执行；**Agent 包** 选择指令、模型、工具、Skills 和运行组件。宿主应用负责界面、身份认证、凭据和会话索引。

应用通过运行时事件展示模型输出、工具活动、审批和完成状态。断开观察连接不会取消底层 Run。存储与调度保证取决于所选实现：内置配置面向单进程或单宿主，本机进程执行不提供容器级隔离。

扩展契约见 [运行时架构](sagents/v2/ARCHITECTURE.md)，当前并发边界见 [单机并发说明](docs/zh/architecture/sagents-v2-single-host-concurrency.md)。

## 文档导航

| 主题 | 文档 |
| --- | --- |
| 文档索引 | [简体中文](docs/zh/README.md) · [English](docs/en/README.md) |
| Desktop v2 | [启动、工作区、模型与运行行为](app/desktop_v2/README.md) |
| Server v2 | [配置、存储与 Agent 包](app/server_v2/README.md) |
| SAgents v2 | [概览与示例](sagents/v2/README.md) · [集成使用手册](sagents/v2/使用手册.md) |
| Server Agent 平台 | [Agent 包、Studio、API 与验证边界](docs/zh/architecture/SERVER_V2_AGENT_PLATFORM.md) |
| 部署 | [环境布局与 Docker Compose](deploy/README.md) |
| 变更记录 | [版本说明](release_notes/) · [开发变更日志](change_log.md) |

请优先阅读所选入口对应的组件文档；较早的应用指南介绍的是旧版应用栈。

## 开发与贡献

```text
Sage/
├── sagents/v2/          # 可嵌入的 v2 智能体运行时
├── sagents/             # 旧版运行时与共用智能体模块
├── app/desktop_v2/      # Flutter 桌面端与本机 Python sidecar
├── app/server_v2/       # 多用户服务端与 Web 客户端
├── app/desktop/         # 旧版 Tauri 桌面端
├── app/server/          # 旧版服务端与 Web 客户端
├── app/cli/             # 命令行入口
├── app/terminal/        # 终端 UI
├── app/chrome-extension/
├── app/skills/          # 内置 Skills
├── common/              # 共用应用基础设施
├── mcp_servers/         # MCP 集成
├── tests/               # 运行时与应用测试
├── examples/            # 集成示例
├── deploy/              # 部署与监控配置
└── docs/                # 中英文文档
```

修改 Python 代码时，安装 `pytest` 并运行受影响组件的测试。例如，在仓库根目录执行：

```bash
python -m pip install pytest pytest-asyncio pytest-timeout
python -m pytest tests/sagents/v2 tests/app/desktop_v2 tests/app/server_v2 -q
```

修改 Desktop v2 时执行：

```bash
cd app/desktop_v2
flutter analyze
flutter test
```

欢迎通过 [Issues](https://github.com/ZHangZHengEric/Sage/issues) 和 Pull Request 参与贡献。请说明涉及的应用入口、复现步骤和相关验证结果。

## 社区

问题反馈和功能建议请提交到 [GitHub Issues](https://github.com/ZHangZHengEric/Sage/issues)，也可以加入 [Slack 社区](https://join.slack.com/t/sage-b021145/shared_invite/zt-3t8nabs6c-qCEDzNUYtMblPshQTKSWOA) 交流。

## 赞助商

感谢 **循环智能（RcrAI）** 和 **Data** 对 Sage 的支持。

<p align="center">
  <img src="assets/sponsors/xunhuanzhineng_logo.svg" height="50" alt="循环智能（RcrAI）" />
  &nbsp;&nbsp;&nbsp;&nbsp;
  <img src="assets/sponsors/idata_logo.png" height="50" alt="Data" />
</p>

## 许可证

Sage 使用 [MIT 许可证](LICENSE) 开源。
