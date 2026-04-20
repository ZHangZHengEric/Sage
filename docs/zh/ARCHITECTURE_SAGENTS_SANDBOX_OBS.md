---

## layout: default
title: 沙箱 / LLM / 可观测性
parent: 架构
nav_order: 8
description: "Sandbox 抽象（Local / Remote / Passthrough）、LLM 客户端封装与能力探针、ObservabilityManager 与 OpenTelemetry"
lang: zh
ref: architecture-sagents-sandbox-obs

{% include lang_switcher.html %}

# 沙箱 / LLM / 可观测性

这一章把三块“横切关注点”合在一起：

- **Sandbox**：所有“执行用户/Agent 代码”的入口都通过统一接口经过它。
- **LLM 层**：模型客户端、能力探针、prompt 缓存等都被封到 `SageAsyncOpenAI` 里。
- **可观测性**：一次会话的运行链路通过 `ObservabilityManager` 派发到多个 handler，OpenTelemetry 是默认实现。

它们不直接出现在“业务流程”里，但任何一个出问题都会让整个 runtime 出问题，所以单独一章。

## 1. 沙箱 `sagents/utils/sandbox/`

### 1.1 模块组成

```mermaid
flowchart TB
    Iface[interface.py · ISandboxHandle 抽象]
    Cfg[config.py · SandboxConfig + VolumeMount]
    Factory[factory.py · SandboxProviderFactory]

    subgraph Providers ["providers/"]
        Local[local · venv + bwrap/seatbelt 隔离]
        Remote[remote · OpenSandbox / K8s / Firecracker]
        Pass[passthrough · 不隔离，宿主直跑]
    end

    Iface -.被实现.-> Local
    Iface -.被实现.-> Remote
    Iface -.被实现.-> Pass
    Cfg --> Factory
    Factory -->|按 mode 选择| Local
    Factory -->|按 mode 选择| Remote
    Factory -->|按 mode 选择| Pass
```



`ISandboxHandle` 是工具层看到的“唯一接口”——无论底下是哪种实现，工具调用都长一样。

### 1.2 三种沙箱模式对比

```mermaid
flowchart LR
    Tool[tool/impl/* 调用沙箱] --> SH{ISandboxHandle}
    SH -->|LOCAL| L[本地 venv + Linux bwrap / macOS seatbelt]
    SH -->|REMOTE| R[远端容器 / MicroVM]
    SH -->|PASSTHROUGH| P[当前进程 cwd 内直接执行]
    L --> Use1[默认桌面/服务端]
    R --> Use2[共享/多租户/受限环境]
    P --> Use3[examples / CLI 调试]
```



- **LOCAL**：默认模式。给每个会话一个独立目录作为 `sandbox_agent_workspace`，再加资源限制（CPU 时间、内存、可访问路径）。
- **REMOTE**：把执行外包给 OpenSandbox / Kubernetes / Firecracker 等远端运行时，工厂根据 `remote_provider` 选择具体实现。
- **PASSTHROUGH**：完全不隔离，直接在宿主机执行，多用于本地 CLI 与 examples。

### 1.3 ISandboxHandle 关键能力

```mermaid
flowchart TB
    H[ISandboxHandle] --> Meta[元数据<br/>sandbox_type / sandbox_id / workspace_path]
    H --> Cmd[execute_command<br/>workdir / timeout / env_vars]
    H --> Py[execute_python<br/>requirements / workdir / timeout]
    H --> FS[文件读写<br/>read_file / write_file / list_dir]
    H --> Mounts[volume_mounts<br/>主机/虚拟路径映射]
```



工具层（`execute_command_tool`、`file_system_tool` 等）只调这套接口，不关心具体实现是 venv 还是远端容器。

### 1.4 一次工具调用的链路

```mermaid
sequenceDiagram
    autonumber
    participant Agent
    participant TM as ToolManager
    participant Tool as execute_command_tool
    participant Sandbox as ISandboxHandle
    participant Provider as Local/Remote/Passthrough

    Agent->>TM: run_tool("execute_command", args)
    TM->>Tool: 调用工具实现
    Tool->>Sandbox: execute_command(cmd, ...)
    Sandbox->>Provider: 实际执行（venv subprocess / 远端 RPC / 直跑）
    Provider-->>Sandbox: CommandResult
    Sandbox-->>Tool: CommandResult
    Tool-->>TM: 截断后的字符串结果
    TM-->>Agent: tool_message
```



### 1.5 与 Skill 的协作

```mermaid
flowchart LR
    Sess[Session] --> SC[SessionContext.init_more]
    SC --> Sandbox[(沙箱实例)]
    SC --> SSM[SandboxSkillManager]
    SSM -->|拷贝/投影| SkillDir[(沙箱内固定路径)]
    Tool -->|读写| Sandbox
    Tool -->|读写技能资源| SkillDir
```



`SandboxSkillManager` 是“技能 → 沙箱”的桥梁：它在沙箱起来后把技能包按约定路径放进去，工具脚本就能像访问本地目录一样使用。

## 2. LLM 层 `sagents/llm/`

### 2.1 模块组成

```mermaid
flowchart TB
    SAOAI[SageAsyncOpenAI · 双客户端封装]
    Chat[chat.py · 流式调用 + 工具调用拼装]
    Embed[embedding.py · 向量化封装]
    Cap[capabilities.py · 请求净化 sanitize_model_request_kwargs]
    MCap[model_capabilities.py · 启动期能力探针]

    SAOAI -->|standard / fast| Chat
    SAOAI --> Embed
    SAOAI -.携带.-> Cap
    MCap -.探测后注入.-> SAOAI
```



### 2.2 SageAsyncOpenAI：双客户端

```mermaid
flowchart LR
    Caller[Agent 调 chat.completions.create] --> Sage[SageAsyncOpenAI]
    Sage -->|model_type=standard| Std[标准模型客户端<br/>主力 LLM]
    Sage -->|model_type=fast| Fast[快速模型客户端<br/>用于 Router/分类等小任务]
    Fast -.未配置时回退.-> Std
    Sage --> San[sanitize_model_request_kwargs<br/>按模型能力清洗参数]
    San --> Std
    San --> Fast
```



要点：

- 接口完全兼容 `AsyncOpenAI`，只是多一个 `model_type` 参数；
- 把模型能力位（`supports_multimodal` / `supports_structured_output` 等）挂到客户端对象上，调用点直接读，不必到处传配置；
- `sanitize_model_request_kwargs` 会按模型能力裁剪请求体，避免“给不支持 reasoning 的模型传 `reasoning_effort`”这类问题。

### 2.3 启动期能力探针

```mermaid
flowchart TD
    Boot[启动: lifecycle.initialize_system] --> Probe[probe_connection / capabilities]
    Probe --> P1[发一条最小请求<br/>验证连通性 + 模型名]
    Probe --> P2[发结构化输出请求<br/>判断 supports_structured_output]
    Probe --> P3[发图片输入请求<br/>判断 supports_multimodal]
    P1 --> Cap[(model_capabilities 字典)]
    P2 --> Cap
    P3 --> Cap
    Cap --> SAOAI[包进 SageAsyncOpenAI]
```



探针运行一次，结果会跟着 `SageAsyncOpenAI` 走完整个生命周期，避免每次请求都查能力。

## 3. 可观测性 `sagents/observability/`

### 3.1 模块组成

```mermaid
flowchart TB
    Base[base.py · BaseTraceHandler 抽象事件]
    Mgr[manager.py · ObservabilityManager 多 handler 派发]
    Otel[opentelemetry_handler.py · 默认实现]
    Runtime[agent_runtime.py · runtime 端便捷封装]

    Base -.被实现.-> Otel
    Otel -->|注册到| Mgr
    Mgr --> Runtime
```



### 3.2 事件模型

```mermaid
flowchart LR
    Chain[on_chain_start/end/error<br/>整次会话]
    Agent[on_agent_start/end/error<br/>单个 Agent 一次执行]
    LLM[on_llm_start/end/error<br/>一次模型调用]
    Tool[on_tool_start/end/error<br/>一次工具调用]
    Msg[on_message_start/end<br/>一条消息]

    Chain --> Agent --> LLM
    Agent --> Tool
    Agent --> Msg
```



`BaseTraceHandler` 把可观测性的“形状”定下来：链路、Agent、LLM、工具、消息这五类事件，全都成对出现（start/end，加可选 error）。

### 3.3 ObservabilityManager 派发

```mermaid
flowchart LR
    Source[各组件触发事件] --> Mgr[ObservabilityManager]
    Mgr --> H1[OpenTelemetryTraceHandler]
    Mgr --> H2[自定义 Handler 1]
    Mgr --> H3[自定义 Handler N]
    Mgr -.单个 handler 抛错.-> Skip[只记 log，不影响其它 handler]
```



派发器对“一个 handler 抛异常”做了容错：不打断主流程，也不会污染别的 handler。

### 3.4 OpenTelemetry 实现

```mermaid
flowchart TD
    Start[on_*_start] --> NewSpan[创建 OTel Span]
    NewSpan --> Attach[context.attach 入栈<br/>contextvars 安全跨 task]
    Action[业务运行] --> Anno[span.set_attribute / add_event]
    End[on_*_end] --> Finalize[span.set_status OK<br/>span.end + 出栈]
    Err[on_*_error] --> ErrSpan[span.record_exception<br/>set_status ERROR + 出栈]
```



要点：

- 用 `ContextVar` 维护 span 栈，保证异步任务嵌套时 span 关系不串。
- 跨 context 的 detach 错误被显式忽略（async 任务跨边界很容易触发）。
- 这一层只“产生”OTel span，至于导出到哪（Jaeger / Tempo / 自托管 OTLP），由进程外的 OpenTelemetry SDK 配置决定，runtime 不关心。

## 4. 三者怎么串起来

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
    LLM-->>SA: 流式响应（含 tool_call）
    SA->>Tool: run_tool
    Tool->>SB: execute_command / read_file
    Tool-->>Obs: on_tool_start/end
    SB-->>Tool: 结果
    Tool-->>SA: tool_message
    SA->>Obs: on_agent_end
    SA->>Obs: on_chain_end
```



一次会话里：业务流程在 `SAgent` 推进，所有“被外部观测到的事情”都通过 `ObservabilityManager` 抛出来，所有“跨进程的执行”都收敛到 `SageAsyncOpenAI` 与 `ISandboxHandle`。这就是 sagents 把横切关注点解耦的方式。

## 5. 二次开发：自定义 Handler / Provider

### 5.1 自定义可观测性 Handler

```python
from sagents.observability.base import BaseTraceHandler

class MyHandler(BaseTraceHandler):
    def on_llm_start(self, session_id, model_name, messages, step_name=None, **kwargs):
        print(f"[LLM start] session={session_id} model={model_name} step={step_name}")

    def on_llm_end(self, response, **kwargs):
        print("[LLM end]", getattr(response, "usage", None))

# 注册
manager.add_handler(MyHandler())
```

- 可以只实现关心的那几个 `on_*`，其它走父类的空实现；
- 抛异常不会影响主流程，但会被 logger 记录，调试时方便定位。

### 5.2 自定义远程沙箱

```python
from sagents.utils.sandbox.interface import ISandboxHandle, SandboxType, CommandResult
from sagents.utils.sandbox.factory import SandboxProviderFactory

class MyRemoteSandbox(ISandboxHandle):
    @property
    def sandbox_type(self): return SandboxType.REMOTE
    @property
    def sandbox_id(self): return self._id
    # ... 其它属性按 interface 实现 ...

    async def execute_command(self, command, workdir=None, timeout=30, env_vars=None):
        # 调你自己的 RPC / HTTP / SSH
        ...
        return CommandResult(success=True, stdout="...", stderr="", return_code=0, execution_time=0.1)

SandboxProviderFactory.register_remote_provider("my_remote", MyRemoteSandbox)
```

之后只要 `SandboxConfig(mode=SandboxType.REMOTE, remote_provider="my_remote", ...)`，工厂就会用你自己的实现。