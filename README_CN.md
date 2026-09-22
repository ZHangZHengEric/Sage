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

## ✨ **核心亮点**

- 🗂️ **围绕项目工作** — 在同一个桌面工作区中组织对话、文件、工具执行与终端。
- 🤖 **打造专属 Agent** — 自由组合指令、模型和工具，将专业能力复用于后续任务。
- 🤝 **多智能体协作** — 在 Studio 中通过共享对话和定向消息，让不同成员分工处理任务。
- 🧩 **Skills 与 MCP** — 加载可复用的工作流程，接入外部工具与服务。
- 🎛️ **自由选择模型** — 桌面端支持 OpenAI Chat Completions、OpenAI Responses 和 Anthropic Messages 协议。
- 👀 **看得见，也能掌控** — 跟踪执行进度，暂停或取消 Run，补充输入并处理审批。
- 🛠️ **嵌入自己的应用** — 通过 `sage.yaml` 定义 Agent 包，基于 SAgents v2 构建 Python 应用。

---

## 🚀 **快速开始**

| 选择你的入口 | 从这里开始 |
| --- | --- |
| 💻 **Desktop v2** — 本地项目工作与智能体协作 | [桌面端指南](app/desktop_v2/README.md) |
| 🌐 **Server v2** — 多用户 Web 应用与 Agent Studio | [服务端指南](app/server_v2/README.md) |
| 🧠 **SAgents v2** — 将智能体能力集成到自己的应用 | [运行时快速开始](sagents/v2/README.md#quick-start) |
| 📦 **桌面安装包** — 已发布版本 | [下载与版本说明](https://github.com/ZHangZHengEric/Sage/releases) |

### 💻 从源码启动桌面端

需要 **Python 3.12+**，以及支持桌面构建、Dart 版本满足 `^3.12.2` 的 **Flutter**。macOS 下运行：

```bash
git clone https://github.com/ZHangZHengEric/Sage.git
cd Sage
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
cd app/desktop_v2
flutter pub get
flutter run -d macos
```

**添加模型 → 配置 Agent → 开始对话或打开项目。**

应用自动启动本机后端。设置与会话数据保存在 `~/sage/runtime`，默认工作区为 `~/sage/agent_workspace`。

Windows、Linux 配置见 [桌面端指南](app/desktop_v2/README.md)。安装包以对应版本说明为准；现有发布工作流构建的是旧版 Tauri 应用。

### 🌐 从源码启动服务端

需要 **Python 3.12+**、**MySQL** 和 **Node.js 22.12+**。在仓库根目录、已激活 Python 环境的终端中执行：

```bash
python -m pip install -e '.[server-v2]'
cp app/server_v2/.env.example app/server_v2/.env
```

在 `.env` 中配置 MySQL 连接、JWT 密钥和初始管理员账号，然后运行：

```bash
cd app/server_v2/web
npm install
npm run build
cd ../../..
python -m app.server_v2
```

打开 **[localhost:8090](http://localhost:8090)**，添加模型和 Agent 后开始对话；进入 **`/studio`** 管理 Agent 包。

详细配置见 [服务端指南](app/server_v2/README.md)。Server v2 当前支持**单 worker**，MySQL 持久化不代表已支持横向扩容。

### 🧑‍💻 用 SAgents v2 运行第一个 Agent

完成上面的 Python 环境安装后，将以下两个文件放在同一目录。示例输出运行事件与最终状态。

**1. 定义 Agent — `sage.yaml`**

```yaml
# sage.yaml
schema_version: sage/v2
kind: application
metadata:
  id: com.example.assistant
  version: 1.0.0
  name: My Assistant
credentials:
  model-key:
    source: env
    key: MODEL_API_KEY
models:
  primary:
    provider: openai-responses
    base_url: https://api.openai.com/v1
    credential: model-key
    model: your-model
agents:
  main:
    name: My Assistant
    instructions:
      inline: Be helpful and concise.
    models:
      primary: primary
entrypoint:
  agent: main
```

**2. 发起任务 — `quickstart.py`**

```python
# quickstart.py
import asyncio
from uuid import uuid4

from sagents.v2 import ActorRef, RequestContext, SAgentBuilder, StartRun
from sagents.v2.contracts.commands import InputItem
from sagents.v2.contracts.items import TextBlock
from sagents.v2.contracts.principals import PrincipalType


async def main():
    app = await SAgentBuilder().with_defaults(session_root="runtime").build("sage.yaml")
    try:
        context = RequestContext(actor=ActorRef(
            principal_id="user-1", principal_type=PrincipalType.USER,
        ))
        command = StartRun(
            agent_id="main",
            input=(InputItem(role="user", content=(TextBlock(text="Say hello!"),)),),
            resolved_spec_hash=app.composition_hash,
            idempotency_key=str(uuid4()),
        )
        stream = await app.entrypoint().run_stream(command, context)
        async for event in stream.events:
            print(event.model_dump_json())
        result = await stream.wait()
        print(result.state)
    finally:
        await app.close()


asyncio.run(main())
```

**3. 将 `your-model` 替换为你可用的模型 ID，设置密钥并运行**

```bash
export MODEL_API_KEY="your-api-key"
python quickstart.py
```

此示例仅调用模型，不启用文件或 Shell 工具。[工具接入与更多配置 →](sagents/v2/使用手册.md)

### ⌨️ 更多使用方式

已有的 [Web](docs/zh/applications/WEB.md)、[CLI](docs/zh/applications/CLI.md)、[TUI](docs/zh/applications/TUI.md) 和 [Chrome 扩展](docs/zh/applications/CHROME_EXTENSION.md) 仍可使用，基于旧版应用栈，配置方式见各自指南。Desktop v2 不导入 v1 的设置和数据。

---

## 🧠 **SAgents v2 内核**

```text
     Desktop v2                 Server v2
    Flutter 工作区             Web + Agent Studio
            \                    /
                  SAgents v2
           Agent 包 · Session · Run
          模型 · 工具 · Skills · 记忆
             存储 · 沙箱 · 事件
```

| 核心概念 | 职责 |
| --- | --- |
| **Agent 包** | 定义指令、模型、工具、Skills 和运行配置。 |
| **Session** | 保存跨 Run 的持久化对话历史。 |
| **Run** | 承载一次执行，以及流式进度和交互。 |
| **扩展组件** | 按需替换模型、存储、记忆、工具和调度实现。 |

宿主应用负责界面、身份认证和凭据。内置运行配置面向单进程或单宿主；本机进程执行不提供容器级隔离。

[了解运行时 →](sagents/v2/README.md) · [阅读架构设计 →](sagents/v2/ARCHITECTURE.md)

---

## 📚 **文档导航**

| 了解 Sage | 构建与扩展 |
| --- | --- |
| [文档索引](docs/zh/README.md) | [运行时集成手册](sagents/v2/使用手册.md) |
| [Desktop v2](app/desktop_v2/README.md) | [Server Agent 平台](docs/zh/architecture/SERVER_V2_AGENT_PLATFORM.md) |
| [Server v2](app/server_v2/README.md) | [部署指南](deploy/README.md) |
| [版本说明](release_notes/) | [开发变更日志](change_log.md) |

请优先阅读所选入口对应的组件文档。

## 🛠️ **参与贡献**

运行时位于 [`sagents/v2/`](sagents/v2/)，桌面端位于 [`app/desktop_v2/`](app/desktop_v2/)，Web 平台位于 [`app/server_v2/`](app/server_v2/)。

欢迎提交 [Issue](https://github.com/ZHangZHengEric/Sage/issues) 或 Pull Request。请附上复现步骤，并运行受影响组件的检查：Python 测试位于 [`tests/`](tests/)，Desktop v2 使用 `flutter analyze` 和 `flutter test`。

## 💬 **加入社区**

[加入 Slack](https://join.slack.com/t/sage-b021145/shared_invite/zt-3t8nabs6c-qCEDzNUYtMblPshQTKSWOA) · [反馈问题与功能建议](https://github.com/ZHangZHengEric/Sage/issues)

## 💖 **赞助商**

感谢 **循环智能（RcrAI）** 和 **Data** 对 Sage 的支持。

<p align="center">
  <img src="assets/sponsors/xunhuanzhineng_logo.svg" height="50" alt="循环智能（RcrAI）" />
  &nbsp;&nbsp;&nbsp;&nbsp;
  <img src="assets/sponsors/idata_logo.png" height="50" alt="Data" />
</p>

---

<div align="center">

[MIT 许可证](LICENSE) · Built with ❤️ by the Sage Team 🦌

</div>
