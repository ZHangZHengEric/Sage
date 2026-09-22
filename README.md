# Sage

[English](README.md) · [简体中文](README_CN.md) · [Documentation](docs/en/README.md) · [Releases](https://github.com/ZHangZHengEric/Sage/releases) · [MIT License](LICENSE)

Sage brings AI agents into the workspace where your work happens. Give an agent a project, connect the models and tools it needs, and work with it from the first instruction through file changes, tool execution, and review.

Use the desktop app for hands-on work, the web application for multi-user access, or the Python runtime to build your own agent experience. Sage is open source under the MIT license.

## A workspace for work that goes beyond chat

**Work with your project in context.** Keep conversations, project files, execution progress, and a terminal in one desktop workspace. Start in the shared Agent Workspace or connect an existing project directory, then inspect the files and results as the agent works.

**Turn capabilities into reusable agents.** Choose a model, define instructions, and combine built-in tools, Skills, and MCP connections. Reuse that configuration across tasks, or define an Agent package in `sage.yaml` to integrate it into your own application.

**Collaborate with visibility and control.** Follow model output and tool activity as they happen. Pause a Run, add input, handle an approval, or cancel execution. Desktop Studio brings agents into a shared conversation with member-directed messages; Server Studio adds Agent package editing, immutable versions, execution history, and review.

**Build on an extensible foundation.** SAgents v2 separates the agent runtime from the application that hosts it. Model providers, storage, memory, tools, and scheduling have explicit extension interfaces, so you can adapt the runtime to your application without adopting a particular UI.

## Put Sage to work

| Workflow | How Sage supports it |
| --- | --- |
| Code and project work | Connect a project, let an agent read and edit files with configured tools, and inspect execution alongside the results. |
| Repeatable specialist tasks | Package instructions, model choices, Skills, and tools into an Agent you can use again. |
| Multi-agent collaboration | Give Studio members distinct responsibilities and direct messages to the member who should handle them. |
| Your own agent product | Embed SAgents v2 and provide your own interface, authentication, credentials, and workspace policies. |

Model routes in Desktop v2 support **OpenAI Chat Completions**, **OpenAI Responses**, and **Anthropic Messages** protocols. Skills supply reusable workflows; MCP connections bring external tools into the agent's available capabilities.

## Choose an entry point

| Entry point | Best for | Code and guide |
| --- | --- | --- |
| Desktop v2 | A local workspace for conversations, projects, files, and agents | [Flutter desktop](app/desktop_v2/README.md) |
| Server v2 | A multi-user web application with model, Agent, Skill, and MCP management | [Server and web client](app/server_v2/README.md) |
| SAgents v2 | Embedding the agent runtime in your own application | [Runtime guide](sagents/v2/README.md) |
| Legacy applications | The existing Desktop, Web, CLI, TUI, and Chrome extension | [Application guides](docs/en/applications/README.md) |

The repository contains both generations. SAgents v2, Desktop v2, and Server v2 require **Python 3.12+**; legacy applications retain a Python 3.10+ baseline. Desktop v2 has its own settings and data layout and does not import Desktop v1 data. Features and configuration are specific to each entry point.

## Quick start

### Prepare the source checkout

The following commands use a POSIX shell on macOS or Linux:

```bash
git clone https://github.com/ZHangZHengEric/Sage.git
cd Sage
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

On Windows, create the environment with `py -3.12 -m venv .venv` and activate it with `.venv\Scripts\Activate.ps1` in PowerShell.

### Desktop v2

Install Flutter with desktop support for your platform and a bundled Dart SDK compatible with [pubspec.yaml](app/desktop_v2/pubspec.yaml) (`^3.12.2`). After preparing the Python environment above, run:

```bash
cd app/desktop_v2
flutter pub get
flutter run -d macos
```

Use `-d windows` or `-d linux` for the corresponding desktop target, with its native build tools installed. The integrated PTY terminal currently supports macOS and Linux.

The app starts its local Python sidecar automatically. In Settings, add a model route with its protocol, endpoint, model name, and API key, then configure an Agent to use it. Start a conversation in the shared Agent Workspace or register a project directory to work with its files. Add Skills and MCP connections as needed.

Desktop v2 stores runtime data and settings in `~/sage/runtime`, imported Skills in `~/sage/skills`, and the default shared workspace in `~/sage/agent_workspace`. Agent and model settings are managed in the app rather than through environment-variable overrides.

See the [Desktop v2 guide](app/desktop_v2/README.md) for workspace behavior, configuration, and development checks. For packaged desktop builds, consult [Releases](https://github.com/ZHangZHengEric/Sage/releases) and the instructions for that release; the repository's existing desktop release workflow targets the legacy Tauri app.

### Server v2

Server v2 requires MySQL, Redis, and Node.js compatible with Vite 7 (Node.js 22.12+ is suitable). From the repository root, with the Python environment active:

```bash
python -m pip install -e '.[server-v2]'
cp app/server_v2/.env.example app/server_v2/.env
```

Edit `app/server_v2/.env` before starting:

- Set `SAGE_SERVER_MYSQL_URL` and `SAGE_SERVER_REDIS_URL` to your service connections.
- Set `SAGE_SERVER_JWT_SECRET` to your own secret of at least 32 bytes.
- Set `SAGE_SERVER_ADMIN_USERNAME` and `SAGE_SERVER_ADMIN_PASSWORD` for the initial administrator.

Build the web client and start the server:

```bash
cd app/server_v2/web
npm install
npm run build
cd ../../..
python -m app.server_v2
```

Open [http://127.0.0.1:8090](http://127.0.0.1:8090), sign in with the administrator credentials you configured, and add a model and an Agent. API documentation is available at `/docs`; Agent package management is available at `/studio`.

Server v2 currently runs with **one worker**. MySQL persistence and Redis event replay do not make the runtime horizontally scalable. See the [Server v2 guide](app/server_v2/README.md) for configuration and deployment boundaries.

### Embed SAgents v2

Use `SAgentBuilder` to load an Agent package and create an `SAgentApplication`. The host supplies model credentials, user identity, workspace access, and any tool execution environment.

```python
from sagents.v2 import SAgentApplication, SAgentBuilder
```

The [runtime quick start](sagents/v2/README.md#quick-start) includes a complete `sage.yaml` and a runnable Python example. The [integration manual](sagents/v2/使用手册.md) covers capability selection and configuration in detail (Chinese).

### Existing applications

The legacy entry points remain available with their own setup instructions:

| Application | Start here |
| --- | --- |
| Web | Run `./scripts/dev-up.sh` from the repository root; see the [Web guide](docs/en/applications/WEB.md). This starts the legacy stack. |
| Desktop | See [release assets](https://github.com/ZHangZHengEric/Sage/releases) and the [Desktop guide](docs/en/applications/DESKTOP.md). |
| CLI | Configure the model, then use `sage doctor`, `sage run`, or `sage chat`; see the [CLI guide](docs/en/applications/CLI.md). |
| TUI | See the [terminal guide](docs/en/applications/TUI.md) for installation and launch commands. |
| Chrome extension | Load `app/chrome-extension/` as an unpacked extension and connect it to the backend; see the [extension guide](docs/en/applications/CHROME_EXTENSION.md). |

## How the pieces fit together

```text
Desktop v2 (Flutter + local FastAPI)    Server v2 (Web + multi-user API)
                  \                    /
                     SAgents v2
             Agent packages · Sessions · Runs
          Models · Tools · Skills · Context · Memory
              Storage · Jobs · Sandbox · Events
```

A **Session** owns durable conversation history. A **Run** is one execution attempt within that Session. An **Agent package** selects instructions, models, tools, Skills, and runtime components. The host application owns its user interface, authentication, credentials, and conversation index.

Runtime events let applications show model output, tool activity, approvals, and completion. Disconnecting an observer does not cancel the underlying Run. Storage and scheduling guarantees depend on the selected implementations: the built-in configurations target a single process or host, and local process execution does not provide container-level isolation.

Read the [runtime architecture](sagents/v2/ARCHITECTURE.md) for extension contracts and the [single-host concurrency guide](docs/zh/architecture/sagents-v2-single-host-concurrency.md) for current limits (Chinese).

## Documentation

| Topic | Reference |
| --- | --- |
| Documentation index | [English](docs/en/README.md) · [简体中文](docs/zh/README.md) |
| Desktop v2 | [Setup, workspace, models, and runtime behavior](app/desktop_v2/README.md) |
| Server v2 | [Configuration, storage, and Agent packages](app/server_v2/README.md) |
| SAgents v2 | [Overview and examples](sagents/v2/README.md) · [Integration manual](sagents/v2/使用手册.md) |
| Server Agent platform | [Packages, Studio, APIs, and validation boundaries](docs/zh/architecture/SERVER_V2_AGENT_PLATFORM.md) |
| Deployment | [Environment layouts and Docker Compose](deploy/README.md) |
| Changes | [Release notes](release_notes/) · [Development changelog](change_log.md) |

Some component guides are currently in Chinese. Start with the guide for your chosen entry point; older application guides describe the legacy stack.

## Development

```text
Sage/
├── sagents/v2/          # Embeddable v2 agent runtime
├── sagents/             # Legacy runtime and shared agent modules
├── app/desktop_v2/      # Flutter desktop and local Python sidecar
├── app/server_v2/       # Multi-user server and web client
├── app/desktop/         # Legacy Tauri desktop
├── app/server/          # Legacy server and web client
├── app/cli/             # CLI
├── app/terminal/        # Terminal UI
├── app/chrome-extension/
├── app/skills/          # Built-in Skills
├── common/              # Shared application infrastructure
├── mcp_servers/         # MCP integrations
├── tests/               # Runtime and application tests
├── examples/            # Integration examples
├── deploy/              # Deployment and monitoring configuration
└── docs/                # English and Chinese documentation
```

For Python changes, install `pytest` and run the tests for the component you modify. For example, from the repository root:

```bash
python -m pip install pytest pytest-asyncio pytest-timeout
python -m pytest tests/sagents/v2 tests/app/desktop_v2 tests/app/server_v2 -q
```

For Desktop v2 changes:

```bash
cd app/desktop_v2
flutter analyze
flutter test
```

Contributions are welcome through [Issues](https://github.com/ZHangZHengEric/Sage/issues) and pull requests. Include the affected entry point, reproduction steps, and relevant validation results.

## Community

Use [GitHub Issues](https://github.com/ZHangZHengEric/Sage/issues) for bugs and feature requests, or join the [Slack community](https://join.slack.com/t/sage-b021145/shared_invite/zt-3t8nabs6c-qCEDzNUYtMblPshQTKSWOA) for discussion.

## Sponsors

Thank you to **RcrAI** and **Data** for supporting Sage.

## License

Sage is available under the [MIT License](LICENSE).
