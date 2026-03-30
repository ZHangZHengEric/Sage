<div align="center">

# Sage

![cover](assets/cover.png)

[![English](https://img.shields.io/badge/Language-English-blue.svg)](README.md)
[![简体中文](https://img.shields.io/badge/语言-简体中文-red.svg)](README_CN.md)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg?logo=opensourceinitiative)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-blue.svg?logo=python)](https://python.org)
[![Version](https://img.shields.io/badge/Version-1.0.0-green.svg)](https://github.com/ZHangZHengEric/Sage)
[![DeepWiki](https://img.shields.io/badge/DeepWiki-查看文档-purple.svg)](https://deepwiki.com/ZHangZHengEric/Sage)
[![Slack](https://img.shields.io/badge/Slack-加入社区-4A154B?logo=slack)](https://join.slack.com/t/sage-b021145/shared_invite/zt-3t8nabs6c-qCEDzNUYtMblPshQTKSWOA)

面向生产场景的多智能体运行时与应用栈，支持在 CLI、Web 和桌面端构建、运行和扩展 Sage 智能体。

</div>

## 为什么是 Sage

Sage 不是又一个套在 LLM 外面的聊天壳。它面向的是那些真正要把智能体做成产品的团队：可运行、可扩展、可观测，并且能够落到真实的用户界面与交付场景中。

你不需要为每一种使用场景重复搭一遍栈。Sage 提供了一套共享基础，统一承载智能体工作流、Tools、Skills、MCP 集成，以及 CLI、Web、桌面端等面向用户的产品形态。

## 核心亮点

- 支持串行、并行和声明式工作流模式的多智能体编排
- 通过框架级优化提升复杂智能体任务的稳定执行能力
- 内置可复用 Skills，帮助团队从可工作的能力模块快速起步
- 内置沙箱机制，提升智能体执行过程的安全性
- 基于 OpenTelemetry 提供全链路可观测性与执行追踪能力
- 围绕 Skills、Tools 和 MCP Servers 构建模块化扩展体系
- 提供 Context Budget 控制能力，优化上下文与 Token 管理
- 在统一运行时基础之上支持 CLI、Web 与桌面端产品形态
- 提供面向文件预览、工具结果和执行反馈的可视化工作区能力
- 支持 MCP 协议，便于实现标准化工具集成

## Sage 是什么

Sage 采用分层代码结构：

- `sagents/`：核心运行时、编排、工具、技能、沙箱与可观测性
- `app/server/`：主 FastAPI 应用与 Vue Web 客户端
- `app/desktop/`：桌面端本地后端与桌面 UI
- `examples/`：轻量可运行示例
- `mcp_servers/`：内置 MCP Server 实现

这个仓库同时包含产品层应用和它们依赖的底层运行时。

## 产品形态

### 主服务与 Web UI

当你需要完整的多用户产品体验时，使用这一套。

- 后端入口：`app/server/main.py`
- 前端源码：`app/server/web/`

### 桌面应用

当你需要面向终端用户或内部团队分发的本地桌面体验时，使用这一套。

- 启动入口：`app/desktop/entry.py`
- 桌面后端：`app/desktop/core/main.py`

### 轻量示例

当你想用最短路径验证想法、提示词或运行时行为时，使用这些入口。

- `examples/sage_cli.py`
- `examples/sage_demo.py`
- `examples/sage_server.py`

## 截图

<div align="center">

<table>
  <tr>
    <td align="center" width="33%">
      <img src="assets/screenshots/workbench.png" width="100%" alt="工作台"/>
      <br/><strong>可视化工作台</strong>
    </td>
    <td align="center" width="33%">
      <img src="assets/screenshots/chat.png" width="100%" alt="对话"/>
      <br/><strong>流式对话</strong>
    </td>
    <td align="center" width="33%">
      <img src="assets/screenshots/preview.png" width="100%" alt="预览"/>
      <br/><strong>文件预览</strong>
    </td>
  </tr>
</table>

</div>

## 快速开始

### 1. 安装依赖

```bash
git clone https://github.com/ZHangZHengEric/Sage.git
cd Sage
pip install -r requirements.txt
```

### 2. 设置最小环境变量

```bash
export SAGE_DEFAULT_LLM_API_KEY="your-api-key"
export SAGE_DEFAULT_LLM_API_BASE_URL="https://api.deepseek.com/v1"
export SAGE_DEFAULT_LLM_MODEL_NAME="deepseek-chat"
```

### 3. 选择一个入口运行

CLI 示例：

```bash
python examples/sage_cli.py \
  --default_llm_api_key "$SAGE_DEFAULT_LLM_API_KEY" \
  --default_llm_api_base_url "$SAGE_DEFAULT_LLM_API_BASE_URL" \
  --default_llm_model_name "$SAGE_DEFAULT_LLM_MODEL_NAME"
```

主服务：

```bash
python -m app.server.main
```

健康检查：

```bash
curl http://127.0.0.1:8080/api/health
```

Web UI：

```bash
cd app/server/web
npm install
npm run dev
```

Streamlit 示例：

```bash
streamlit run examples/sage_demo.py -- \
  --default_llm_api_key "$SAGE_DEFAULT_LLM_API_KEY" \
  --default_llm_api_base_url "$SAGE_DEFAULT_LLM_API_BASE_URL" \
  --default_llm_model_name "$SAGE_DEFAULT_LLM_MODEL_NAME"
```

## 延伸阅读

- 技术文档：[`docs/README.md`](docs/README.md)
- 快速上手：[`docs/GETTING_STARTED.md`](docs/GETTING_STARTED.md)
- 发布说明：[`release_notes/`](release_notes/)
- DeepWiki：https://deepwiki.com/ZHangZHengEric/Sage
- Slack 社区：https://join.slack.com/t/sage-b021145/shared_invite/zt-3t8nabs6c-qCEDzNUYtMblPshQTKSWOA

如果你是在评估 Sage 作为产品平台的价值，先看这个 README；如果你要接入、扩展或实现功能，再继续阅读 `docs/`。

## 架构概览

```mermaid
flowchart TD
    User[用户界面] --> Web[Web 应用]
    User --> Desktop[桌面应用]
    User --> Examples[示例程序]
    Web --> Server[app/server]
    Desktop --> DesktopCore[app/desktop/core]
    Server --> Runtime[sagents]
    DesktopCore --> Runtime
    Examples --> Runtime
    Runtime --> Tools[工具系统]
    Runtime --> Skills[技能系统]
    Runtime --> Sandbox[沙箱]
    Runtime --> Obs[可观测性]
    Tools --> MCP[mcp_servers]
```

## 仓库导览

```text
Sage/
├── sagents/          # 核心运行时与编排
├── app/server/       # 主后端与 Web 应用
├── app/desktop/      # 桌面端后端、UI 与打包脚本
├── examples/         # 轻量可运行示例
├── mcp_servers/      # 内置 MCP Server
├── docs/             # 技术文档
└── release_notes/    # 版本发布说明
```

## 文档

技术文档统一放在 [`docs/`](docs/)：

- [`docs/README.md`](docs/README.md)
- [`docs/GETTING_STARTED.md`](docs/GETTING_STARTED.md)
- [`docs/CORE_CONCEPTS.md`](docs/CORE_CONCEPTS.md)
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)
- [`docs/CONFIGURATION.md`](docs/CONFIGURATION.md)
- [`docs/API_REFERENCE.md`](docs/API_REFERENCE.md)
- [`docs/DEVELOPMENT.md`](docs/DEVELOPMENT.md)
- [`docs/TROUBLESHOOTING.md`](docs/TROUBLESHOOTING.md)

作为仓库首页，README 会刻意保持比 `docs/` 更短；更细的实现细节统一收敛在 `docs/` 中。

## 开发

后端：

```bash
python -m app.server.main
```

前端：

```bash
cd app/server/web
npm install
npm run dev
```

桌面端构建：

```bash
app/desktop/scripts/build.sh release
```

## 参与贡献

欢迎贡献。若你修改了运行时行为，建议在同一个变更中同步更新 `docs/` 中对应的文档页面，让产品入口与技术说明保持一致。

## 社区

- Issues：https://github.com/ZHangZHengEric/Sage/issues
- Slack：https://join.slack.com/t/sage-b021145/shared_invite/zt-3t8nabs6c-qCEDzNUYtMblPshQTKSWOA

## 许可证

MIT，见 [`LICENSE`](LICENSE)。
