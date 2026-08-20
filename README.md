<div align="center">

# 🌟 **Experience Sage's Power**

![cover](assets/cover.png)

[![English](https://img.shields.io/badge/Language-English-blue.svg)](README.md)
[![简体中文](https://img.shields.io/badge/语言-简体中文-red.svg)](README_CN.md)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg?logo=opensourceinitiative)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue.svg?logo=python)](https://python.org)
[![Version](https://img.shields.io/badge/Version-1.1.0-green.svg)](https://github.com/ZHangZHengEric/Sage)
[![DeepWiki](https://img.shields.io/badge/DeepWiki-Learn%20More-purple.svg)](https://deepwiki.com/ZHangZHengEric/Sage)
[![Slack](https://img.shields.io/badge/Slack-Join%20Community-4A154B?logo=slack)](https://join.slack.com/t/sage-b021145/shared_invite/zt-3t8nabs6c-qCEDzNUYtMblPshQTKSWOA)

# 🧠 **Sage Agent Platform**

### 🎯 **From Complex Work to Reliable Delivery**

> 🌟 **A production-ready agent platform for task execution, automation, browser workflows, IM delivery, and enterprise deployment.**

</div>

---

## 📸 **Product Screenshots**

<div align="center">

<table>
  <tr>
    <td align="center" width="33%">
      <img src="assets/screenshots/workbench.png" width="100%" alt="Workbench"/>
      <br/><strong>Visual Workbench</strong>
    </td>
    <td align="center" width="33%">
      <img src="assets/screenshots/chat.png" width="100%" alt="Chat"/>
      <br/><strong>Real-time Collaboration</strong>
    </td>
    <td align="center" width="33%">
      <img src="assets/screenshots/preview.png" width="100%" alt="Preview"/>
      <br/><strong>Multi-format Support</strong>
    </td>
  </tr>
</table>

</div>

> 📖 **Detailed Documentation**: [https://wiki.sage.zavixai.com/](https://wiki.sage.zavixai.com/)

---

## ✨ **Key Features**

- 🤖 **Planning to Delivery**: Built-in planning, execution, self-check, memory recall, and tool suggestion agents for complex task completion.
- 🌐 **Multi-Entry Product Surface**: Use Sage from desktop, web, CLI, and Chrome extension depending on the workflow.
- 🔁 **Automation & Recurring Tasks**: Run scheduled jobs, questionnaire-driven collection flows, and long-running operational tasks with progress visibility.
- 💬 **Omnichannel IM Integration**: Connect WeChat Personal (iLink), WeCom, Feishu, and DingTalk with message and file delivery support.
- 🧰 **Unified Tooling System**: Combine built-in tools, Skills, MCP servers, browser automation, search, and image generation in one execution stack.
- 🛡️ **Sandboxed Execution**: Local, passthrough, and remote sandbox options for safer agent runtime isolation.
- 🛠️ **Visual Workbench**: Inspect files, tool outputs, code, charts, Mermaid, Draw.io, audio, video, and remote previews in one workspace.
- 🏢 **Enterprise-Ready Foundation**: OAuth2, configurable auth and CORS, shared service architecture, CI coverage, and deployable multi-platform packaging.

---

## 🚀 **Quick Start**

**Prerequisites (web from source):** Python 3.10+, Node.js 18+.

### Web (clone and run)

```bash
git clone https://github.com/ZHangZHengEric/Sage.git
cd Sage
export SAGE_DEFAULT_LLM_API_KEY="your-api-key"
export SAGE_DEFAULT_LLM_API_BASE_URL="https://api.deepseek.com/v1"
export SAGE_DEFAULT_LLM_MODEL_NAME="deepseek-chat"
./scripts/dev-up.sh
```

Open [http://localhost:5173](http://localhost:5173). The first run may ask for **Minimal** (SQLite) vs **Full** stacks — Minimal is the quickest. Optional: `PYTHON_BIN=...` or `USE_UV=1 ./scripts/dev-up.sh` if you use a custom Python or [uv](https://github.com/astral-sh/uv).

**Detailed documentation:** [Web Application](docs/en/applications/WEB.md) — manual backend + Vite, Docker Compose, and port notes.

### Desktop (installers)

Download the latest `.dmg` (macOS), `.exe` NSIS installer (Windows), or `.deb` (Linux) from [GitHub Releases](https://github.com/ZHangZHengEric/Sage/releases), then install as below.

**macOS**

1. Open the `.dmg` for your CPU (Intel or Apple Silicon), drag **Sage.app** into **Applications**.
2. The build is **not** currently Apple-notarized. If macOS says the developer cannot be verified or the app cannot be checked for malware: in **Finder → Applications**, **right‑click** `Sage.app` → **Open**, then confirm **Open** in the dialog (this adds a one-time exception for Gatekeeper).
3. If it is still blocked: **System Settings → Privacy & Security**, scroll to the message about Sage, click **Open Anyway**, then try opening the app again.
4. If macOS reports the app is **damaged** or will not open, clear the quarantine flag and retry:

```bash
xattr -dr com.apple.quarantine /Applications/Sage.app
```

**Windows**

1. Run the `.exe` installer and complete the wizard.
2. If **Windows SmartScreen** warns about an unknown publisher, click **More info** → **Run anyway** (wording may vary by Windows version).

**Linux (Debian / Ubuntu)**

1. Download the `.deb` for your architecture from Releases.
2. Install from a terminal (adjust the filename):

```bash
sudo apt install ./Sage-<version>-<arch>.deb
```

You can also double-click the `.deb` in many desktop environments.

**Detailed documentation:** [Desktop Application](docs/en/applications/DESKTOP.md) — build from source, env, and platform notes.

### CLI

```bash
pip install -e .
export SAGE_DEFAULT_LLM_API_KEY="your-api-key"
export SAGE_DEFAULT_LLM_API_BASE_URL="https://api.deepseek.com/v1"
export SAGE_DEFAULT_LLM_MODEL_NAME="deepseek-chat"
export SAGE_DB_TYPE="file"
sage doctor
sage run "Say hello briefly."
# or: sage chat
```

**Detailed documentation:** [CLI Guide](docs/en/applications/CLI.md)

### TUI

After `pip install -e .` and the same `SAGE_DEFAULT_*` + `SAGE_DB_TYPE=file` as above, use `sage-terminal` (or run from `app/terminal/` with `cargo` — see the guide).

**Detailed documentation:** [TUI Guide](docs/en/applications/TUI.md)

### Chrome extension

Load the unpacked extension from `app/chrome-extension/` in `chrome://extensions/` (Developer mode). Point the extension at your local Sage backend if the port differs from defaults.

**Detailed documentation:** [Chrome extension](docs/en/applications/CHROME_EXTENSION.md)

---

## 🏗️ **System Architecture**

```mermaid
graph TD
    User[User] --> Desktop[💻 Desktop App]
    User --> Web[🌐 Web App]
    User --> CLI[⌨️ CLI]
    User --> Ext[🧩 Chrome Extension]
    User --> IM[💬 IM Channels]

    Desktop --> AppLayer[🧭 App Service Layer]
    Web --> AppLayer
    CLI --> AppLayer
    Ext --> AppLayer
    IM --> AppLayer

    subgraph App[Product Layer]
        AppLayer --> Chat[💬 Chat & Sessions]
        AppLayer --> AgentsUI[🤖 Agent Management]
        AppLayer --> Tasks[⏰ Tasks & Automations]
        AppLayer --> Browser[🌐 Browser Bridge]
        AppLayer --> Workbench[🛠️ Visual Workbench]
    end

    subgraph Core[SAgents Core]
        AppLayer --> Runtime[🧠 Session Runtime]
        Runtime --> Flow[📋 AgentFlow]
        Flow --> Agents["🤖 Agents<br/>Plan / Simple / Fibre / Self-Check"]
        Agents --> Memory[🧠 Memory Recall]
        Agents --> Skills[🧩 Skills]
        Agents --> ToolMgr[🛠️ Tool Manager]
    end

    subgraph Tools[Execution & Integration]
        ToolMgr --> MCP[🔌 MCP Servers]
        ToolMgr --> BrowserTools[🌍 Browser Automation]
        ToolMgr --> Search[🔎 Unified Search]
        ToolMgr --> ImageGen[🎨 Image Generation]
        ToolMgr --> Questionnaire[📝 Questionnaire]
        ToolMgr --> IMTools[📨 IM Delivery]
    end

    subgraph RuntimeEnv[Runtime & Infrastructure]
        Agents --> Sandbox[📦 Sandbox Runtime]
        Sandbox --> Local[Local]
        Sandbox --> Pass[Passthrough]
        Sandbox --> Remote[Remote]
        AppLayer <--> Common[🧱 Shared Common Services]
        Common <--> DB[(SQL Database)]
        Memory <--> ES[(Elasticsearch)]
        Workbench <--> FS[(RustFS / Local Files)]
        Runtime -.-> Obs["👁️ Observability<br/>OpenTelemetry"]
    end
```

---

## 📅 **What's New in v1.1.0**

### 🤖 **SAgents Kernel Updates**

- **Execution Chain Enhancements**: Added `PlanAgent`, `SelfCheckAgent`, `MemoryRecallAgent`, and `ToolSuggestionAgent`
- **Context Efficiency**: Improved user input optimization and conversation history compression for long-running tasks
- **Session & Messaging**: Added edit-and-rerun support, richer progress feedback, and better session inspection workflows
- **Tooling Expansion**: Added questionnaire collection workflows and improved tool-call rendering, truncation, and observability

### 💻 **Product Layer Updates**

- **New Entry Points**: Added Sage CLI, Chrome extension, and browser automation tooling
- **Workbench Upgrades**: Expanded support for audio, video, Mermaid, Draw.io, remote file preview, and richer tool cards
- **Chat Experience**: Improved progress messages, delivery flow display, reasoning content presentation, and workspace interactions
- **IM Integrations**: Expanded WeChat Personal (iLink), WeCom, Feishu, and DingTalk support with stronger file messaging flows

### 🛡️ **Platform & Infrastructure**

- **Enterprise Readiness**: Added OAuth2, email verification, and stronger auth/CORS/security controls
- **Sandbox & Runtime**: Refactored local/passthrough/remote sandbox support and improved Node runtime/sidecar packaging
- **Shared Architecture**: Extracted reusable `common/` services, models, and schemas across desktop and server
- **Documentation & CI**: Rebuilt the docs structure, added CLI guides, and expanded CI/test coverage

**[View Full Release Notes](release_notes/v1.1.0.md)**

---

## 📚 **Documentation**

- 📖 **Full Documentation**: [https://wiki.sage.zavixai.com/](https://wiki.sage.zavixai.com/)
- 📝 **Release Notes**: [release_notes/](release_notes/)
- 🏗️ **Architecture**: See `sagents/`, `common/`, and `app/` for the core runtime and product layers
- 🔧 **Configuration**: Environment variables and config files in `app/desktop/`

---

## 🛠️ **Development**

### Project Structure

```
Sage/
├── sagents/                    # SAgents core runtime, flow, context, tools, sandbox
├── common/                     # Shared models, schemas, services, core clients
├── app/
│   ├── desktop/                # Desktop app (Python backend + Vue UI + Tauri shell)
│   ├── server/                 # Server app and web frontend
│   ├── cli/                    # Sage CLI entrypoint and services
│   └── chrome-extension/       # Browser extension and sidepanel
├── mcp_servers/                # IM, search, scheduler, image generation and more
├── docs/                       # English and Chinese documentation
└── release_notes/              # Version release notes
```

### Contributing

We welcome contributions! Please see our [GitHub Issues](https://github.com/ZHangZHengEric/Sage/issues) for tasks and discussions.

---

## 💖 **Sponsors**

<div align="center">

We are grateful to our sponsors for their support in making Sage better:

<table>
  <tr>
    <td align="center" width="33%">
      <a href="#" target="_blank">
        <img src="assets/sponsors/dudubashi_logo.png" height="50" alt="Dudu Bus"/>
      </a>
      <br/>
    </td>
    <td align="center" width="33%">
      <a href="#" target="_blank">
        <img src="assets/sponsors/xunhuanzhineng_logo.svg" height="50" alt="RcrAI"/>
      </a>
    </td>
    <td align="center" width="33%">
      <a href="#" target="_blank">
        <img src="assets/sponsors/idata_logo.png" height="50" alt="Data"/>
      </a>
    </td>
  </tr>
</table>

</div>



---

## 🦌 **Join Our Community**

<div align="center">

### 💬 Connect with us

[![Slack](https://img.shields.io/badge/Slack-Join%20Community-4A154B?logo=slack&style=for-the-badge)](https://join.slack.com/t/sage-b021145/shared_invite/zt-3t8nabs6c-qCEDzNUYtMblPshQTKSWOA)

### 📱 WeChat Group

<img src="assets/WeChatGroup.jpg" width="300" alt="WeChat Group QR Code"/>

*Scan to join our WeChat community 🦌*

</div>

---

<div align="center">
Built with ❤️ by the Sage Team 🦌
</div>

---

## ❓ FAQ

### 平台概念

**Sage 是什么？**
Sage 是一个生产就绪的 AI Agent 平台，专注于复杂任务的执行、自动化、浏览器工作流、IM 消息交付和企业级部署。它内置规划、执行、自检、记忆召回和工具建议等 Agent 组件，可将复杂工作转化为可靠交付。

**Sage 与 LangGraph / CrewAI 有什么区别？**
- **LangGraph** 侧重图状态机编排，适合细粒度流程控制；Sage 提供开箱即用的完整平台（UI + 后端 + 工具系统）
- **CrewAI** 以角色驱动的 Agent 团队协作为核心；Sage 以任务交付为中心，内置多入口（Web/桌面/CLI/Chrome 扩展）和 IM 全渠道交付
- Sage 更适合需要端到端交付的生产环境，LangGraph/CrewAI 更适合需要深度自定义编排的场景

**Sage 支持哪些入口？**
- Web 应用（浏览器访问）
- 桌面应用（macOS .dmg / Windows .exe / Linux .deb）
- CLI 命令行
- Chrome 浏览器扩展

### 安装配置

**系统要求是什么？**
- Python 3.10+
- Node.js 18+
- 推荐 4 核 8GB RAM 及以上

**如何快速启动？**
```bash
git clone https://github.com/ZHangZHengEric/Sage.git
cd Sage
export SAGE_DEFAULT_LLM_API_KEY="your-api-key"
export SAGE_DEFAULT_LLM_API_BASE_URL="https://api.deepseek.com/v1"
export SAGE_DEFAULT_LLM_MODEL_NAME="deepseek-chat"
./scripts/dev-up.sh
```
首次运行可选择 Minimal（SQLite，最快）或 Full 栈。

**支持哪些 LLM 提供商？**
任何兼容 OpenAI API 格式的提供商均可使用，包括 DeepSeek、OpenAI、Claude、本地模型等。通过配置 `SAGE_DEFAULT_LLM_API_BASE_URL` 和 `SAGE_DEFAULT_LLM_MODEL_NAME` 即可切换。

### Agent 开发

**Sage 内置哪些 Agent？**
- **规划 Agent**：任务分解和策略制定
- **执行 Agent**：任务执行和工具调用
- **自检 Agent**：结果验证和质量检查
- **记忆召回 Agent**：上下文管理和历史回溯
- **工具建议 Agent**：智能推荐合适工具

**如何自定义工具？**
Sage 支持多种工具集成方式：
- 内置工具（搜索、文件操作等）
- Skills 系统（自定义技能包）
- MCP 服务器（Model Context Protocol）
- 浏览器自动化
- 图像生成工具

**支持哪些 IM 平台？**
- 微信个人号（iLink）
- 企业微信
- 飞书
- 钉钉

### 部署

**有哪些部署选项？**
- **本地开发**：`./scripts/dev-up.sh` 快速启动
- **Docker Compose**：生产级容器化部署
- **桌面应用**：macOS/Windows/Linux 安装包
- **企业部署**：支持 OAuth2、CORS 配置、共享服务架构

**如何配置沙箱执行？**
Sage 提供三种沙箱模式：
- 本地沙箱：适合开发测试
- 透传模式：直接执行，适合可信环境
- 远程沙箱：隔离执行，适合生产环境

### 故障排查

**启动失败怎么办？**
1. 确认 Python 3.10+ 和 Node.js 18+ 已安装
2. 检查 API Key 和 Base URL 配置是否正确
3. 查看日志：`./scripts/dev-up.sh` 输出会显示详细错误信息
4. 尝试 Minimal 模式：首次运行选择 Minimal 栈

**macOS 提示应用损坏无法打开？**
运行以下命令清除隔离标记：
```bash
xattr -dr com.apple.quarantine /Applications/Sage.app
```

**如何获取更多帮助？**
- 详细文档：https://wiki.sage.zavixai.com/
- Slack 社区：https://join.slack.com/t/sage-b021145/
- GitHub Issues：https://github.com/ZHangZHengEric/Sage/issues
