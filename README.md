<div align="center">

# 🌟 **Experience Sage's Power**

![logo](assets/logo.png)

[![English](https://img.shields.io/badge/🌍_English-Current-yellow?style=for-the-badge)](README.md)
[![简体中文](https://img.shields.io/badge/🇨🇳_简体中文-点击查看-orange?style=for-the-badge)](README_CN.md)
[![License: MIT](https://img.shields.io/badge/📄_License-MIT-blue.svg?style=for-the-badge)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/🐍_Python-3.11+-brightgreen.svg?style=for-the-badge)](https://python.org)
[![Version](https://img.shields.io/badge/🚀_Version-0.9.7-green.svg?style=for-the-badge)](https://github.com/ZHangZHengEric/Sage)

# 🧠 **Sage Multi-Agent Framework**

### 🎯 **Making Complex Tasks Simple**

> 🌟 **A production-ready, modular, and intelligent multi-agent orchestration framework for complex problem solving.**

</div>

---

## ✨ **Key Features**

- 🧠 **Intelligent Task Decomposition**: Automatically breaks down complex problems with dependency tracking.
- 🔄 **Agent Orchestration**: Seamless coordination between specialized agents (Planning, Execution, Observation, Summary).
- 🛠️ **Extensible Tool System**: Plugin-based architecture supporting **MCP Servers** and auto-discovery.
- ⚡ **Dual Modes**: **Deep Research** for analysis and **Rapid Execution** for speed.
- 📊 **Context Management**: Advanced **Context Budget** controls for precise token optimization (v0.9.7+).
- 🌐 **Modern UI**: Vue3 + FastAPI web interface with real-time streaming and visualization.
- 🐍 **Python 3.11+ Optimized**: Fully typed and linted codebase for enterprise-grade reliability.

## 🚀 **Quick Start**

### Installation

```bash
git clone https://github.com/ZHangZHengEric/Sage.git
cd Sage
pip install -r requirements.txt
# For Web UI
pip install -r app/server/requirements.txt
```

### Running Sage

**Interactive Web Demo (Streamlit)**:
```bash
streamlit run app/sage_demo.py -- \
  --default_llm_api_key YOUR_API_KEY \
  --default_llm_model deepseek-chat \
  --default_llm_api_base_url https://api.deepseek.com
```

> If you get "ModuleNotFoundError: No module named 'sagents'", set PYTHONPATH: `export PYTHONPATH=/path/to/your/Sage:$PYTHONPATH`

**Command Line Interface (CLI)**:
```bash
python app/sage_cli.py \
  --default_llm_api_key YOUR_API_KEY \
  --default_llm_model deepseek-chat \
  --default_llm_base_url https://api.deepseek.com
```

**Modern Web App (FastAPI + Vue3)**:

The modern web application is now structured as `app/server` (Backend) and `app/web` (Frontend).

**Deploy with Docker Compose**:
```bash
docker-compose up -d
```
Access the application at `http://localhost:30051`.

## 🤖 **Supported Models**

```mermaid
graph LR
    U[User Input] --> AC[Agent Controller]
    AC --> WF
    AC --> RM

    subgraph WF[Workflow]
        A[Analysis] --> B[Planning] --> C[Execution] --> D[Observation] --> E[Summary]
        D -- "Loop" --> B
        C -- uses --> X[🛠️ Tool System]
    end
    E --> R[Result]

    subgraph RM[Resource Management]
        F[TaskManager]
        G[MessageManager]
        H[Workspace]
    end
```

## 📅 **What's New in v0.9.7**

- **Context Budget**: New parameters (`--context_history_ratio`, etc.) for granular context control.
- **Unified Parameters**: Standardized `default_llm_*` arguments across Server, CLI, and Demo.
- **Stability**: Full Python 3.11+ type safety compliance and code style optimizations.
- **[View Full Release Notes](release_notes/v0.9.7.md)**

## 📚 **Documentation**

- [**Full Documentation**](docs/README.md)
- [**API Reference**](docs/API_REFERENCE.md)
- [**Configuration Guide**](docs/CONFIGURATION.md)
- [**Tool Development**](docs/TOOL_DEVELOPMENT.md)

---
<div align="center">
Built with ❤️ by the Sage Team
</div>
