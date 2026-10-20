<div align="center">

# 🌟 **Experience Sage's Power**

![cover](assets/cover.png)

[![English](https://img.shields.io/badge/Language-English-blue.svg)](README.md)
[![Chinese](https://img.shields.io/badge/Language-Chinese-red.svg)](README_CN.md)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg?logo=opensourceinitiative)](LICENSE)
[![Python 3.12+](https://img.shields.io/badge/Python-3.12%2B-blue.svg?logo=python)](https://python.org)
[![Version](https://img.shields.io/badge/Version-2.1.1-green.svg)](https://github.com/ZHangZHengEric/Sage)
[![DeepWiki](https://img.shields.io/badge/DeepWiki-Learn%20More-purple.svg)](https://deepwiki.com/ZHangZHengEric/Sage)
[![Slack](https://img.shields.io/badge/Slack-Join%20Community-4A154B?logo=slack)](https://join.slack.com/t/sage-b021145/shared_invite/zt-3t8nabs6c-qCEDzNUYtMblPshQTKSWOA)

# 🧠 **Sage · Custom, Self-Evolving Agents**

### 🎯 **Define Your Agent. Evaluate. Evolve.**

> 🌟 **An open-source platform for building custom, self-evolving AI agents. Define an Agent package, evaluate it, and improve it through multiple RSI rounds — with version history and your choice of which version to adopt.**

</div>

---

New to RSI? [Inspect your first run](docs/en/applications/FIRST_RSI_RUN.md): a scripted Python walkthrough with no model API key.


New to the code? [Start with the code reading guide](docs/en/architecture/code-reading-guide.md): runtime, host call chains, ownership and tests.

Build your own host: [SAgents configuration and debugging guide](docs/en/architecture/sagents-host-development.md) with a runnable offline starter.

## ✨ **Why Sage**

- 📦 **Custom Agent packages** — Define your agent's instructions, Skills, tools, and runtime configuration in `sage.yaml`; reuse packages in Desktop, Server, or your Python application.
- 🧬 **Self-evolution with RSI** — Test and refine packages over configurable rounds using evaluation, tuning, and review agents in separate Sessions. Retain every iteration and choose which version to use.
- 🧩 **Plugin-based architecture** — Compose model, memory, storage, tool, and scheduling providers with explicit contracts and managed lifecycles.
- 🪟 **Native streaming UI (Desktop 2.1)** — Uses the official [OpenUI](https://github.com/thesysdev/openui) parser with Sage’s Flutter Glass renderer. Assistant `openui` blocks render as output arrives, with light/dark themes and 31 native component types: charts, metrics, tabs, diagrams, rich inputs, and immediate local calculations. Local-only interfaces need no submit button or model round-trip; a submit button explicitly hands values back to the assistant. Users can ask naturally without mentioning OpenUI. Enable **Prefer interactive UI** in the composer plus menu, or set **Settings → General → Interactive UI on by default** for new chats; enabling it preloads the complete built-in Skill without a tool call. Presentations stream as native 16:9 slides and export editable PPTX from the same document. This is a supported component subset, not the upstream Web renderer; included in the 2.1.1 desktop packages. [Integration details](app/v2/desktop/README.md#openui).
- 🔄 **Stateful, interactive execution** — Durable Session history, streamed events, and pause/resume with human input and approvals.
- 🤝 **Multi-agent orchestration** — Coordinate Studio members through directed messages, or compose Agent Flows in the runtime.
- 🔌 **An extensible tool ecosystem** — Bring built-in tools, reusable Skills, and [MCP](https://modelcontextprotocol.io/) services into the same agent workflow.
- 🏗️ **One runtime, multiple hosts** — Use SAgents through Desktop and Server, or embed it in your own Python application.

---

## 🧬 **RSI: From Custom Agents to Self-Evolution**

Supply an Agent package, choose a goal, round count, and editable scope, and run an independent RSI (Recursive Self-Improvement) loop.

- **Control what evolves** — Optimize only Skills, or allow instruction guidance, tool enablement, and step budgets. Supply your own test suite or generate one with a test-design agent; test single-turn tasks and conversations with bounded turn counts.
- **Evaluate and review independently** — A separate audit Session checks test-suite alignment with the authorized goal before any target execution. Evaluation and candidate semantic review then check completion, memorization, and goal drift in separate Sessions. An independent final suite is sealed before baseline evaluation.
- **Inspect every iteration** — Retain the original package, every iteration's complete package, test responses, evaluations, and review results. Desktop shows background progress and RSI run histories. Agent settings separately retain saved and applied configuration versions; unapplied candidates stay in their RSI runs.
- **Choose what to adopt** — Optimization produces candidates without replacing your configuration. Inspect the comparison, select a version, and explicitly confirm before Desktop applies it. Keep the original when no better candidate emerges.

See the [RSI workflow guide](docs/en/applications/RSI.md). Use `AgentPackageOptimizer` through the [Python API](sagents/v2/optimization/README.md), or open RSI from [Desktop Agent settings](app/v2/desktop/README.md#rsi-与-agent-版本). Desktop RSI currently supports simple Agents and native tools; installer availability follows each release's notes.

---

## 📰 **Latest updates**

- **2026-10-13** — [Streaming UI: from an answer to a native interactive interface](docs/en/applications/STREAMING_UI.md) — Live generation, local calculations, Process Panel revisions, and editable PPTX export in Desktop 2.1.
- **2026-10-12** — [MCP tools are visible, but calls fail: a five-step diagnostic](knowledge/tutorials/mcp-visible-calls-fail.md)
- **2026-10-12** — RSI: multi-round Agent package optimization, test-suite alignment audits, independent final tests and semantic review, plus Desktop progress and Agent-level version history. [Python API](sagents/v2/optimization/README.md) · [Desktop guide](app/v2/desktop/README.md#rsi-与-agent-版本)
- **2026-10-11** — [OpenRouter free models: selection and limits](knowledge/resources/openrouter-free-models.md)
- **2026-10-11** — [MCP engineering resources: protocols, SDKs, testing, and security](knowledge/resources/mcp-engineering-resources.md)
- **2026-10-11** — [A read-only MCP smoke test through Sage](knowledge/tutorials/mcp-smoke-test.md)

[More agent resources and tutorials →](knowledge/README.md)

---

## 🚀 **Get Started**

Sage, Desktop, Server, and SAgents refer to the current v2 implementation by default. For the legacy version, use the separate [Sage v1 guide](app/v1/README.md).

| Choose your path | Start here |
| --- | --- |
| 💻 **Desktop** — Configure agents, run RSI, and choose versions | [Desktop guide](app/v2/desktop/README.md) |
| 🌐 **Server** — Multi-user web access and Agent Studio | [Server guide](app/v2/server/README.md) |
| 🧠 **SAgents** — Build and optimize agents through Python | [Runtime quick start](sagents/v2/README.md#quick-start) |
| 📦 **Desktop installers** — Available release builds | [Downloads & release instructions](https://github.com/ZHangZHengEric/Sage/releases/tag/v2.1.1) |

### 📦 Desktop installer

1. Download [Sage 2.1.1](https://github.com/ZHangZHengEric/Sage/releases/tag/v2.1.1) for macOS (arm64/x86_64), Windows (x86_64), or Linux (arm64/x86_64).
2. Install and open Sage. Python and the backend are bundled; no repository checkout, system Python, or Flutter is needed. Linux still requires GTK and bubblewrap.
3. Add your model in Settings → Configure an Agent → Start a conversation. Your model service may charge usage fees. See the [Desktop guide](docs/en/applications/DESKTOP.md#first-task).
4. macOS packages are not notarized; Windows installers are not code-signed. See the [release notes](release_notes/v2.1.1.md) for package details.

### 💻 Desktop from source

Requires **Python 3.12+** and **[Flutter](https://flutter.dev/)** with Dart `^3.12.2` and desktop support. On macOS:

```bash
git clone https://github.com/ZHangZHengEric/Sage.git
cd Sage
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[desktop]'
cd app/v2/desktop
flutter pub get
flutter run -d macos
```

**Add a model → Configure an Agent → Start a conversation or open a project.**

The app starts its local backend automatically. Settings and session data live in `~/sage/runtime`; the default workspace is `~/sage/agent_workspace`.

For Windows and Linux setup, see the [Desktop guide](app/v2/desktop/README.md). Sage 2.1 packages and the release boundary are documented in [v2.1.1 release notes](release_notes/v2.1.1.md). GitHub Actions builds Flutter v2 installers with an embedded Python runtime; the legacy Tauri installers belong to v1.

### 🌐 Server from source

Requires **Python 3.12+**, **MySQL**, and **Node.js 22.12+**. From the checkout root, with the Python environment active:

```bash
python -m pip install -e '.[server]'
cp .env.example app/v2/server/.env
```

Set the MySQL connection, JWT secret, and initial administrator credentials in `.env`, then run:

```bash
cd app/v2/server/web
npm install
npm run build
cd ../../..
python -m app.v2.server
```

Open **[localhost:8090](http://localhost:8090)**. Add a model and an Agent to start chatting, or open **`/studio`** to manage Agent packages.

See the [Server guide](app/v2/server/README.md) for configuration. Server currently supports **one worker**; MySQL persistence does not enable horizontal scaling.

### 🧑‍💻 Run your first SAgents agent

**One Python file; no `sage.yaml` required.** After the Python setup above, save as `quickstart.py` and replace `your-model` with an available model:

```python
"""Set MODEL_API_KEY and replace your-model below; no sage.yaml file is needed."""

import asyncio
from uuid import uuid4

from sagents.v2 import ActorRef, RequestContext, SAgentBuilder, StartRun
from sagents.v2.contracts.commands import InputItem
from sagents.v2.contracts.items import TextBlock
from sagents.v2.contracts.principals import PrincipalType
from sagents.v2.package.manifest import SageManifestLoader

AGENT_YAML = """
schema_version: sage/v2
kind: application
metadata: {id: example.assistant, version: 1.0.0, name: Assistant}
agents:
  main:
    name: Assistant
    instructions: {inline: "Be helpful and concise."}
    models: {primary: primary}
entrypoint: {agent: main}
"""

MODELS_YAML = """
credentials:
  api-key: {source: env, key: MODEL_API_KEY}
models:
  primary:
    provider: openai-responses
    base_url: https://api.openai.com/v1
    credential: api-key
    model: your-model
"""


async def main(*, runtime=None, registrations=()):
    from sagents.v2.composition.defaults import default_runtime
    manifest = SageManifestLoader().loads(AGENT_YAML)
    builder = SAgentBuilder()
    for registration in registrations:
        builder.register(registration)
    app = await builder.build(runtime=runtime or default_runtime("runtime"), models_config_text=MODELS_YAML)
    try:
        agent = await app.load_agent(manifest)
        context = RequestContext(actor=ActorRef(
            principal_id="user-1", principal_type=PrincipalType.USER,
        ))
        stream = await app.entrypoint().run_stream(StartRun(
            agent_id=agent.id,
            input=(InputItem(role="user", content=(TextBlock(text="Say hello!"),)),),
            resolved_spec_hash=agent.composition_hash,
            idempotency_key=str(uuid4()),
        ), context, agent=agent)
        async for event in stream.events:
            print(event.model_dump_json())
        print((await stream.wait()).state)
    finally:
        await app.close()


if __name__ == "__main__":
    asyncio.run(main())
```

```bash
export MODEL_API_KEY="your-api-key"
python quickstart.py
```

`loads()` parses YAML text; `build()` accepts the manifest object directly. This prints events and the final state, without file or shell tools. [More configuration options →](docs/en/applications/GETTING_STARTED.md)

---

## 🧠 **Built on SAgents**

```mermaid
flowchart TB
    desktop["Desktop<br/>Flutter workspace"]
    server["Server<br/>Web & Agent Studio"]
    custom["Your application<br/>Python integration"]

    runtime["SAgents<br/>Agent packages · Sessions · Runs"]

    desktop --> runtime
    server --> runtime
    custom --> runtime

    runtime --> intelligence["Models & context<br/>Providers · Memory"]
    runtime --> capabilities["Tools & workflows<br/>Skills · MCP"]
    runtime --> execution["Execution & state<br/>Storage · Sandbox · Events"]
```

- 📦 **Agent package** — Define what an agent can do.
- 💬 **Session** — Keep its conversation history across Runs.
- ⚡ **Run** — Execute a task with live progress and interaction.

Your application owns the UI, authentication, and credentials. Built-in runtime configurations target a single process or host; local process execution is not container isolation.

[Explore the runtime →](sagents/v2/README.md) · [Read the architecture →](sagents/v2/ARCHITECTURE.md)

---

## 📚 **Documentation**

| Learn | Build |
| --- | --- |
| [Documentation index](docs/en/README.md) | [Runtime integration manual](sagents/v2/使用手册.md) |
| [Desktop](app/v2/desktop/README.md) | [Server Agent platform](docs/zh/architecture/SERVER_V2_AGENT_PLATFORM.md) |
| [Server](app/v2/server/README.md) | [Deployment](deploy/README.md) |
| [Versioned source layout](docs/VERSIONED_LAYOUT.md) | v1 directories and import migration |
| [Release notes](release_notes/) | [Development changelog](change_log.md) |

[Model inference provider resources](knowledge/resources/model-inference-providers.md)

Some component guides are currently in Chinese. Use the guide for your chosen entry point.

## 🛠️ **Contributing**

**Your first PR is welcome!** Documentation, translations, examples, tests, bug fixes, and model/tool integrations all help Sage grow. We welcome small, focused improvements and are happy to work with you to get useful, well-tested contributions merged.

Start with the [contribution guide](CONTRIBUTING.md) for setup, component checks, and a PR checklist. Browse [open issues](https://github.com/ZHangZHengEric/Sage/issues), or open an issue to discuss a larger change before building it. A small documentation fix can go straight to a PR.

Explore [`sagents/v2/`](sagents/v2/) for the runtime, [`app/v2/desktop/`](app/v2/desktop/) for the desktop app, and [`app/v2/server/`](app/v2/server/) for the web platform.

## 💬 **Community**

<div align="center">

[![Slack](https://img.shields.io/badge/Join_Slack-4A154B?style=for-the-badge&logo=slack&logoColor=white)](https://join.slack.com/t/sage-b021145/shared_invite/zt-3t8nabs6c-qCEDzNUYtMblPshQTKSWOA)
[![GitHub Issues](https://img.shields.io/badge/Issues_%26_Ideas-238636?style=for-the-badge&logo=github&logoColor=white)](https://github.com/ZHangZHengEric/Sage/issues)

</div>

## 💖 **Sponsors**

<p align="center">
  <img src="assets/sponsors/xunhuanzhineng_logo.svg" height="40" align="middle" alt="RcrAI" />
  &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;
  <img src="assets/sponsors/idata_mark.png" height="64" align="middle" alt="Data" />
</p>

---

<div align="center">

[MIT License](LICENSE) · Built with ❤️ by the Sage Team 🦌

</div>
