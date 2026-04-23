---
layout: default
title: Sandbox / LLM / Observability
parent: Architecture
nav_order: 8
description: "Sandbox abstraction (Local / Remote / Passthrough), LLM client wrapper with capability probe, ObservabilityManager and OpenTelemetry"
lang: en
ref: architecture-sagents-sandbox-obs
---

{% include lang_switcher.html %}

# Sandbox / LLM / Observability

This chapter groups three cross-cutting concerns:

- **Sandbox**: every entry point that "executes user/Agent code" goes through one unified interface.
- **LLM layer**: model clients, capability probes, prompt cache and so on are wrapped in `SageAsyncOpenAI`.
- **Observability**: a session's runtime trail is dispatched through `ObservabilityManager` to multiple handlers; OpenTelemetry is the default implementation.

These don't show up in business flows directly, but if any of them breaks the whole runtime breaks – hence a dedicated chapter.

## 1. Sandbox `sagents/utils/sandbox/`

### 1.1 Module Composition

```mermaid
flowchart TB
    Iface[interface.py · ISandboxHandle abstraction]
    Cfg[config.py · SandboxConfig + VolumeMount]
    Factory[factory.py · SandboxProviderFactory]

    subgraph Providers ["providers/"]
        Local[local · venv + bwrap/seatbelt isolation]
        Remote[remote · OpenSandbox / K8s / Firecracker]
        Pass[passthrough · no isolation, host execution]
    end

    Iface -.implemented by.-> Local
    Iface -.implemented by.-> Remote
    Iface -.implemented by.-> Pass
    Cfg --> Factory
    Factory -->|by mode| Local
    Factory -->|by mode| Remote
    Factory -->|by mode| Pass
```

`ISandboxHandle` is the **only** interface the tool layer sees – every implementation looks the same to a tool.

### 1.2 Three Sandbox Modes

```mermaid
flowchart LR
    Tool[tool/impl/* calls sandbox] --> SH{ISandboxHandle}
    SH -->|LOCAL| L[Local venv + Linux bwrap / macOS seatbelt]
    SH -->|REMOTE| R[Remote container / MicroVM]
    SH -->|PASSTHROUGH| P[Run directly in current process cwd]
    L --> Use1[default for desktop/server]
    R --> Use2[shared / multi-tenant / restricted]
    P --> Use3[examples / CLI debug]
```

- **LOCAL**: default. Each session gets its own `sandbox_agent_workspace`, plus resource limits (CPU time, memory, allowed paths).
- **REMOTE**: outsource execution to OpenSandbox / Kubernetes / Firecracker; the factory selects the implementation by `remote_provider`.
- **PASSTHROUGH**: no isolation at all, run on the host – mostly for local CLI and examples.

### 1.3 Key Capabilities of ISandboxHandle

```mermaid
flowchart TB
    H[ISandboxHandle] --> Meta[Metadata<br/>sandbox_type / sandbox_id / workspace_path]
    H --> Cmd[execute_command<br/>workdir / timeout / env_vars]
    H --> Py[execute_python<br/>requirements / workdir / timeout]
    H --> FS[File I/O<br/>read_file / write_file / list_dir]
    H --> Mounts[volume_mounts<br/>host/virtual path mapping]
```

The tool layer (`execute_command_tool`, `file_system_tool`, ...) only ever calls this surface; it has no idea whether the implementation is a venv or a remote container.

### 1.4 One Tool Call End-to-End

```mermaid
sequenceDiagram
    autonumber
    participant Agent
    participant TM as ToolManager
    participant Tool as execute_command_tool
    participant Sandbox as ISandboxHandle
    participant Provider as Local/Remote/Passthrough

    Agent->>TM: run_tool("execute_command", args)
    TM->>Tool: invoke implementation
    Tool->>Sandbox: execute_command(cmd, ...)
    Sandbox->>Provider: actually run (venv subprocess / remote RPC / host)
    Provider-->>Sandbox: CommandResult
    Sandbox-->>Tool: CommandResult
    Tool-->>TM: truncated string output
    TM-->>Agent: tool_message
```

### 1.5 Interaction with Skills

```mermaid
flowchart LR
    Sess[Session] --> SC[SessionContext.init_more]
    SC --> Sandbox[(sandbox instance)]
    SC --> SSM[SandboxSkillManager]
    SSM -->|copy/project| SkillDir[(fixed path inside sandbox)]
    Tool -->|read/write| Sandbox
    Tool -->|read skill assets| SkillDir
```

`SandboxSkillManager` bridges "skill → sandbox": once the sandbox is up, it places skill packages at conventional paths inside, so in-sandbox tool scripts can use them like local files.

## 2. LLM Layer `sagents/llm/`

### 2.1 Module Composition

```mermaid
flowchart TB
    SAOAI[SageAsyncOpenAI · dual-client wrapper]
    Chat[chat.py · stream + tool-call assembly]
    Embed[embedding.py · embedding wrapper]
    Cap[capabilities.py · sanitize_model_request_kwargs]
    MCap[model_capabilities.py · startup capability probe]

    SAOAI -->|standard / fast| Chat
    SAOAI --> Embed
    SAOAI -.uses.-> Cap
    MCap -.injects after probing.-> SAOAI
```

### 2.2 SageAsyncOpenAI: Dual Clients

```mermaid
flowchart LR
    Caller[Agent calls chat.completions.create] --> Sage[SageAsyncOpenAI]
    Sage -->|model_type=standard| Std[Standard client<br/>main LLM]
    Sage -->|model_type=fast| Fast[Fast client<br/>routers / classifiers]
    Fast -.fallback when not configured.-> Std
    Sage --> San[sanitize_model_request_kwargs<br/>scrub kwargs by capability]
    San --> Std
    San --> Fast
```

Highlights:

- Interface is fully `AsyncOpenAI`-compatible, only adds a `model_type` parameter.
- Capability flags (`supports_multimodal` / `supports_structured_output` / ...) are attached to the client object so call sites can read them directly without threading config through the stack.
- `sanitize_model_request_kwargs` strips request fields that the underlying model does not support (e.g. drop `reasoning_effort` for non-reasoning models).

### 2.3 Startup Capability Probe

```mermaid
flowchart TD
    Boot[Startup: lifecycle.initialize_system] --> Probe[probe_connection / capabilities]
    Probe --> P1[Send a minimal request<br/>verify connectivity + model name]
    Probe --> P2[Send structured-output request<br/>infer supports_structured_output]
    Probe --> P3[Send image input request<br/>infer supports_multimodal]
    P1 --> Cap[(model_capabilities dict)]
    P2 --> Cap
    P3 --> Cap
    Cap --> SAOAI[wrapped into SageAsyncOpenAI]
```

The probe runs once; its result lives with `SageAsyncOpenAI` for the entire lifetime so we don't reprobe per request.

## 3. Observability `sagents/observability/`

### 3.1 Module Composition

```mermaid
flowchart TB
    Base[base.py · BaseTraceHandler abstract events]
    Mgr[manager.py · ObservabilityManager multi-handler dispatcher]
    Otel[opentelemetry_handler.py · default impl]
    Runtime[agent_runtime.py · runtime-side helpers]

    Base -.implemented by.-> Otel
    Otel -->|registered into| Mgr
    Mgr --> Runtime
```

### 3.2 Event Model

```mermaid
flowchart LR
    Chain[on_chain_start/end/error<br/>whole session]
    Agent[on_agent_start/end/error<br/>one Agent run]
    LLM[on_llm_start/end/error<br/>one model call]
    Tool[on_tool_start/end/error<br/>one tool call]
    Msg[on_message_start/end<br/>one message]

    Chain --> Agent --> LLM
    Agent --> Tool
    Agent --> Msg
```

`BaseTraceHandler` defines the **shape** of observability: chain / agent / llm / tool / message events, all paired (`start` / `end`, plus optional `error`).

### 3.3 ObservabilityManager Dispatch

```mermaid
flowchart LR
    Source[components emit events] --> Mgr[ObservabilityManager]
    Mgr --> H1[OpenTelemetryTraceHandler]
    Mgr --> H2[Custom handler 1]
    Mgr --> H3[Custom handler N]
    Mgr -.handler raises.-> Skip[only logged, others continue]
```

The dispatcher tolerates a single handler raising: the main flow is not interrupted and other handlers keep working.

### 3.4 OpenTelemetry Implementation

```mermaid
flowchart TD
    Start[on_*_start] --> NewSpan[create OTel Span]
    NewSpan --> Attach[context.attach onto stack<br/>contextvars-safe across tasks]
    Action[business runs] --> Anno[span.set_attribute / add_event]
    End[on_*_end] --> Finalize[span.set_status OK<br/>span.end + pop]
    Err[on_*_error] --> ErrSpan[span.record_exception<br/>set_status ERROR + pop]
```

Highlights:

- Uses a `ContextVar` span stack so that nested async tasks don't tangle parent/child relationships.
- Cross-context detach errors are explicitly swallowed (very common when an async generator is cancelled across boundaries).
- This layer only **produces** OTel spans; where they are exported (Jaeger / Tempo / OTLP) is decided by the OpenTelemetry SDK config outside the runtime.

## 4. How They Connect

```mermaid
sequenceDiagram
    autonumber
    participant SA as SAgent
    participant Obs as ObservabilityManager
    participant LLM as SageAsyncOpenAI
    participant Tool as ToolProxy
    participant SB as Sandbox

    SA->>Obs: on_chain_start(session_id)
    SA->>Obs: on_agent_start
    SA->>LLM: chat.completions.create(...)
    LLM-->>Obs: on_llm_start/end
    LLM-->>SA: streaming response (with tool_call)
    SA->>Tool: run_tool
    Tool->>SB: execute_command / read_file
    Tool-->>Obs: on_tool_start/end
    SB-->>Tool: result
    Tool-->>SA: tool_message
    SA->>Obs: on_agent_end
    SA->>Obs: on_chain_end
```

Within a single session: business logic moves through `SAgent`; everything "observable from the outside" is emitted via `ObservabilityManager`; everything that "executes across a process boundary" funnels into `SageAsyncOpenAI` and `ISandboxHandle`. That is how sagents decouples cross-cutting concerns.

## 5. Extending: Custom Handler / Provider

### 5.1 Custom Observability Handler

```python
from sagents.observability.base import BaseTraceHandler

class MyHandler(BaseTraceHandler):
    def on_llm_start(self, session_id, model_name, messages, step_name=None, **kwargs):
        print(f"[LLM start] session={session_id} model={model_name} step={step_name}")

    def on_llm_end(self, response, **kwargs):
        print("[LLM end]", getattr(response, "usage", None))

manager.add_handler(MyHandler())
```

- You only need to override the events you care about; the rest fall through to the no-op base impl.
- Raising inside a handler will not break the main flow but **is** logged, which makes debugging easy.

### 5.2 Custom Remote Sandbox

```python
from sagents.utils.sandbox.interface import ISandboxHandle, SandboxType, CommandResult
from sagents.utils.sandbox.factory import SandboxProviderFactory

class MyRemoteSandbox(ISandboxHandle):
    @property
    def sandbox_type(self): return SandboxType.REMOTE
    @property
    def sandbox_id(self): return self._id
    # ... implement the rest of the interface ...

    async def execute_command(self, command, workdir=None, timeout=30, env_vars=None):
        # call your own RPC / HTTP / SSH
        ...
        return CommandResult(success=True, stdout="...", stderr="", return_code=0, execution_time=0.1)

SandboxProviderFactory.register_remote_provider("my_remote", MyRemoteSandbox)
```

After that, `SandboxConfig(mode=SandboxType.REMOTE, remote_provider="my_remote", ...)` will route to your implementation.
