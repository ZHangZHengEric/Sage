# 基于 SAgents v2 开发宿主项目

[English](../../en/architecture/sagents-host-development.md) · [代码阅读指南](code-reading-guide.md) · [可运行参考项目](../../../examples/sagents_v2_host/)

**新项目先采用一个装配入口、一份 Agent manifest 和统一的 Run 调试标识。**

三份文档分工：[本指南](sagents-host-development.md)讲接入、调试和自定义插件协议；[Runtime 配置参考](sagents-runtime-reference.md)查组件参数与默认值；[sage.yaml 配置参考](sagents-manifest-reference.md)查 Agent Package 全部字段。

自定义插件从[协议总表](#哪些模块支持插件各自是什么协议)和[完整示例](#一个完整独立的插件)开始阅读。
CLI、HTTP 服务和桌面应用可以有不同产品行为，但不要分别实现模型预算、插件加载、Session 历史和恢复状态机。
本文的命令行参数是参考项目的约定，不是 SDK 自动读取的全局环境变量。

## 现在的开发入口

```text
SAgentBuilder.build(runtime=..., models=...) → App
    ↓ app.load_agent(Package)       一个 Package 一个 Agent，加载结果可复用
    ↓ app.entrypoint().run_stream(command, context, agent=agent)
    ↓ stream.events / stream.wait()
    ↓ app.update_agent(agent=agent, package=...)  发布新版本
await app.close()                   统一关闭所有版本及资源
```

参考项目的文件按职责划分：

| 文件 | 职责 |
| --- | --- |
| [sage.yaml](../../../examples/sagents_v2_host/sage.yaml) | 可版本管理的 Agent 配置；只引用 App 模型 ID |
| [models.yaml](../../../examples/sagents_v2_host/models.yaml) | App 模型路由、请求参数、能力和凭据引用 |
| [plugins.py](../../../examples/sagents_v2_host/plugins.py) | 独立的自定义插件、参数模型和注册声明 |
| [bootstrap.py](../../../examples/sagents_v2_host/bootstrap.py) | `HostSettings`、配置加载、Builder 和宿主端口注入 |
| [__main__.py](../../../examples/sagents_v2_host/__main__.py) | CLI 参数、用户身份、StartRun、事件消费与关闭 |

核心调用就是：

```python
app = await build_application(settings)
try:
    agent = app.loaded_agents[0]  # bootstrap 中 load_agent 的结果
    stream = await app.entrypoint().run_stream(command, context, agent=agent)
    async for event in stream.events:
        render(event)
    result = await stream.wait()
finally:
    await app.close()
```

这段是宿主接线示意；可直接执行的完整实现见上述参考项目。
长期运行的服务在启动时创建 Application，在关闭时释放；请求处理函数复用它，不能每个 HTTP 请求都创建一套进程服务。
身份由宿主认证后生成 `RequestContext`，不要直接信任客户端传来的 principal/tenant。

## App、模型和 Agent 的边界

| 配置 | 所有者 | 内容 |
| --- | --- | --- |
| runtime.yaml | App | 存储、执行、观测等组件选择与参数 |
| models.yaml | App | 模型 ID、协议、连接、凭据引用、请求参数、能力与限制 |
| sage.yaml | 单个 Agent Package | 指令、模型 ID 引用、工具、Skill、预算和子 Agent 声明 |

Desktop 将模型设置转换成 App 模型目录；Server 将当前用户授权的模型目录注入 App；CLI 支持 `--models ./models.yaml`，TUI 复用 CLI 入口。各宿主保留自己的认证、密钥和持久化管理，不要求第三方实现这些产品层逻辑。

模型完整字段与更新 API 见 [App 模型配置](sagents-runtime-reference.md#app-模型配置)。运行中的配置更新使用 App 的 `update_models` / `update_model`，Builder 不承担运行期状态管理。自定义模型插件依旧实现 `model.provider` 协议，提前注册，再由模型配置的 `plugin` 指定；插件独立实现，不需要继承 Desktop 或 Server 的代码。

## 加载输入、复用和更新

```python
from pathlib import Path
from sagents.v2 import SAgentBuilder

app = await SAgentBuilder().with_defaults(session_root="./runtime").build(models="./models.yaml")
try:
    agent = await app.load_agent("./agents/assistant")  # 目录中的 sage.yaml
    # 也支持 Path("./assistant.yaml")、SageManifest 或配置字典。
    # 文本显式写为 app.load_agent(config_text=yaml_or_json, base_path=package_root)。
    # runtime 同样支持 RuntimeConfig、字典、路径，文本使用 runtime_config_text=。
    newer = await app.update_agent(agent=agent, package="./agents/assistant")
finally:
    await app.close()
```

路径字符串不作为 YAML 猜测。`package` 与 `config_text`、`runtime` 与 `runtime_config_text`、`models` 与 `models_config_text` 分别互斥。
内存配置含 instruction 文件引用时必须给 `base_path`，且文件不能越出该目录。
一个新 Package 必须恰有一个 Agent，不再通过名称二次选择。
普通 SDK 的 `agent.id` 来自 Package ID，两个 Package 的内部 Agent 都叫 main 也不会冲突。
`StartRun.agent_id` 与 `resolved_spec_hash` 使用加载结果的 `agent.id` 与 `agent.composition_hash`；入口校验两者。

重复加载同一份 Package 和模型配置返回同一个 handle。App 模型目录更新后可重新 load 原 Package 获取新版本；Package 自身改变必须显式 update；更新保留逻辑 ID，返回新 handle。
旧 handle 不会被修改，已运行任务也不会切换版本。校验失败不替换当前版本；并发更新使用当前 handle，过期 handle 会被拒绝。
App 统一持有调度器与所有已加载版本，关闭时先停止调度，再释放各版本及共享存储。
目前版本保留到 App 关闭；高频更新的长期服务需关注内存占用，不会自动驱逐仍可能被恢复使用的版本。

本机 SDK 在运行数据目录的 `agent-revisions/` 保存原始解析快照，重启后从快照恢复待调度旧运行，
而不是用最新 Package 代替。手动继续挂起运行时，先用 `await app.agent_for_run(run_id, context)`
取回经授权校验的原版本，再传给 `entrypoint().continue_run(..., agent=agent)`。
缺失或身份不兼容的快照不能自动换版本执行。归档与 Session 数据一起保留；
其中可能包含配置内容，应按私有运行数据管理。该本机快照存储不是分布式 Package Registry。
Desktop / Server 使用 `HostAgentExecution` 注入已有受理和驱动契约，依然从各自持久化的受理快照恢复，
一次运行的模型、沙箱和授权仍由该运行的 driver 管理；加载复用不等于复用这些 Run 资源。
`build(package)` 已移除，公开入口拒绝多 Agent Package。所有宿主使用 build → load_agent → 显式运行。

子 Agent 同样独立加载，再按父 Package 声明的名称绑定：

```python
reviewer = await app.load_agent("./agents/reviewer")
coder = await app.load_agent("./agents/coder", subagents={"reviewer": reviewer})
```

默认委派只传任务消息：未指定 `child_session_id` 时创建独立的串行 Session，第一条 `user` 消息就是父 Agent 发来的任务；指定时在该子 Session 追加新的 `user` 任务消息，保留子会话自己的历史。`parent_run_id`、`parent_tool_call_id` 和 Session 父子关系用于追踪、结果回传及目录归属，不会隐式复制父会话消息或附件。父 Agent 应在 `content` 中明确提供必要背景和资源引用；`original_task` 仅作为追踪元数据，不会自动成为子会话消息。显式请求的底层 `FORK` 模式仍保留其原有快照语义，不是默认委派行为。

绑定固定到具体版本。更新 reviewer 不会改变已加载的 coder；要采用新版本，显式
`app.update_agent(agent=coder, package="./agents/coder", subagents={"reviewer": updated_reviewer})`。
内部恢复快照包含完整执行图，公开 Package 仍只有一个 Agent。托管 `AgentPackageBundle`
使用 `dependencies` 保存各个独立子 Package，服务通过同一个 `load_agent` 加载。

CLI 内置预设也按此方式加载；TUI 默认调用 `sage v2 chat --json`，共用 CLI 的实现。

## 先离线跑通，再接真实模型

仓库根目录，Python 3.12+：

```bash
# 打印真实装配计划与 readiness；不创建或执行 Run
.venv/bin/python -m examples.sagents_v2_host --offline --inspect

# 跑完一个确定性 Run，不需要模型 API Key，也不调用网络
.venv/bin/python -m examples.sagents_v2_host --offline

# 相同入口切换调试级别、运行数据目录
.venv/bin/python -m examples.sagents_v2_host --offline --log-level debug --runtime-root /tmp/my-sagents-debug
```

真实模型：修改 `sage.yaml` 的 provider/base_url/model，通过环境提供 `MODEL_API_KEY`，然后去掉 `--offline`。
SDK 不会因为模型名或网关有误自动切换其他实现。离线模型只用于开发验证，不用于恢复真实模型创建的 Run。

`--inspect` 会构建 Application、打开配置的服务并执行 readiness 检查，退出时关闭应用；它不是完全无 I/O 的 YAML 校验。
离线模式只替换模型端口，默认参考配置不含网络工具；修改 manifest 后不能再据此保证全部插件无网络访问。

## 配置应放在哪里

| 配置种类 | 放置位置 | 常见内容 |
| --- | --- | --- |
| Agent 定义 | `sage.yaml` | instructions、模型绑定、工具/Skill 白名单、预算 |
| 选用的能力实现 | App 的 runtime.capabilities 与 Package plugins | 插件 ID、scope、插件参数；采用 manifest.runtime 时须由宿主传给 build |
| 宿主部署设置 | `HostSettings` / 宿主配置模块 | runtime 根目录、日志级别、配置文件路径 |
| 宿主资源对象 | 唯一 bootstrap 中的 `Builder.with_*()` | SessionStore、模型并发预算、ExecutionBindingProvider、诊断 sink |
| 单次运行 | `StartRun` 与其配置 | 输入、Session、幂等键、已受理的配置身份 |
| 请求身份 | `RequestContext` | principal、tenant、授权上下文 |
| 密钥 | manifest 凭据引用对应的环境/凭据提供者 | 参考项目使用 `MODEL_API_KEY` |

`SageManifestLoader.load(path, environment=...)` 支持已声明的环境 overlay，但只允许覆盖 `runtime / policies / interfaces`。
不能假定它可以覆盖任意字段，也没有一个通用的“所有环境变量自动覆盖 YAML”规则。

显式 `with_*()` 注入用于替换对应宿主端口；插件选择、声明配置与宿主锁定依赖则由装配层合并。
模型、存储、estimator 等宿主锁定依赖不能被插件配置冒充替换。**普通 SDK 使用 `agent.resolved_plan` 查看该版本的最终绑定；`app.resolved_plan` 是首次装配的进程视图。**
宿主自定义执行的完整运行组件计划在其 Run 装配与诊断中查看，加载句柄不会提前伪造该计划。
`with_shared_runtime()` 只借用其声明的进程服务，不代表复制全部 Builder 配置或产品策略。

## 各项目保持一致的调试方式

参考项目 stdout 输出运行事件与最终状态，stderr 输出 `sage.log/v1` 结构化日志。
模型诊断通过 `FilesystemDiagnosticSink` 写入 `runtime_root/sessions` 下对应 Session/Run 的目录。
目录中的诊断文件可能包含业务输入，按宿主私有数据管理；脱敏不等于可以公开整份会话。

建议其他项目也保留这些调试入口：

1. **看装配**：输出 `app.resolved_plan` 的 capability、plugin_id、scope、source 与 `composition_hash`；不要输出原始密钥配置。
2. **看资源**：`with_readiness_check()` 后检查 `app.resource_readiness`。readiness 不是一次真实模型/工具执行验收。
3. **追踪一次运行**：保存并关联 `session_id → run_id → step_id / request_id / tool_call_id`；具体字段随记录类型出现。
4. **先查事件，再查诊断**：Session 事件、状态、检查点是事实；日志和模型诊断只用于排障，不能作为恢复输入。
5. **保持同一条入口**：离线测试注入 `ScriptedModelProvider`；实际运行移除该注入，保留 bootstrap 和事件消费路径。

常见问题的阅读位置：

| 现象 | 先看什么 |
| --- | --- |
| 插件选错、配置未生效 | `resolved_plan.providers` 的 source 与 plugin_id，再查 manifest/宿主注入 |
| 模型请求内容或预算不对 | 模型诊断中的请求，`AgentCompositionFactory.create_context()` |
| 运行挂起、等待审批 | Run 事件与 interaction 状态；不要重复提交工具调用 |
| 恢复报告配置身份不一致 | 已持久化的受理配置、composition hash、绑定记录；不要换成当前最新 hash 绕过校验 |
| 关闭或沙箱回收异常 | 应用/Run 资源所有权，再查 execution lifecycle；close 与持久化 reconciliation 分开 |

## 一个入口，参数表达差异

Desktop、Server 和第三方项目都使用 `SAgentBuilder.build()`；循环装配统一使用
`AgentCompositionFactory.create_loop()`。宿主仍负责认证、目录、审批和沙箱策略，
这些产品行为通过参数或已有端口注入，不需要另写一套装配器。

**Agent 定义通过 Agent Package 提供。** Package 中的 `sage.yaml` 描述 Agent、模型绑定、
工具、Skill、策略，也可以包含 `runtime`。部署时可把运行配置作为参数传入；它和 YAML
使用同一个 `RuntimeConfig`，不是另一套配置格式。

```python
from sagents.v2 import SAgentBuilder
from examples.sagents_v2_host.plugins import compactor_registration

builder = SAgentBuilder().with_defaults(session_root="./runtime")
builder.register(compactor_registration())  # 先注册，再装配
app = await builder.build(runtime={
    "capabilities": {
        "context.unit-compactor": {
            "plugin": "example.context.reference-compactor",
            "scope": "agent",
            "config": {"minimum_characters": 4},
        },
    },
})
agent = await app.load_agent("examples/sagents_v2_host/sage.yaml")
# 使用完成后 await app.close()；真实模型仍需要对应的凭据。
```

`build()` 不传 runtime 时使用与 Desktop 共用的组件默认配置；不会读取个人模型密钥或电脑设置。
显式 runtime 是完整配置，不做隐式深合并；需要继承默认项时先调用
`from sagents.v2 import default_runtime` 的 `default_runtime(session_root)`，再修改其 capabilities。App 的 runtime 优先于 Package 内的旧 runtime 字段。
实际资源按需在首次加载 Agent 时创建；因此 `build()` 后直接关闭也合法。
已解析的 Package 不允许覆盖为不同 runtime，恢复仍使用受理时的配置。
Server 的部署设置与 Package 能力选择在宿主适配层合并后传入。

插件使用同一份 `CapabilitySelection`：`plugin / name / scope / config`。
`ExtensionRegistration` 声明能力、支持的 scope、参数 JSON Schema、可选的参数模型和工厂。
Schema 校验在工厂调用前进行；是否允许额外字段由插件 schema 决定，参考插件明确拒绝未知字段。
宿主注入的可信依赖与用户 `config` 分开，用户参数不能覆盖锁定依赖。
插件实现互不导入，可以有重复代码。参考项目的字节估算器用于展示接入契约，不是厂商 tokenizer。

两端都接受提前注册：`DesktopV2Service(..., extensions=(registration,))` 和
`ServerHost(..., extensions=(registration,))`，不再接受旧的 `package_extensions` 参数。
注册提供实现，`runtime.capabilities` 选择实现和参数；不要把插件工厂调用散落在业务代码里。

宿主需要自己受理 Run 时使用已有的以下接口，不实例化内部 assembler/materializer：

| 接口 | 用途 |
| --- | --- |
| `application.compose_run(callback)` | 装配与资源所有权边界；不受理、不执行、不恢复 Run |
| `application.materialize_agent(..., runtime=...)` | 在现有 Application 中按同一个标准解析作用域组件 |
| `SAgentBuilder.with_shared_runtime(application)` | 为 Package 应用借用同一进程服务 |
| `AgentCompositionFactory.create_loop(...)` | 共用授权、上下文预算、历史和循环接线 |
| `application.process_provider(capability, selection, dependencies=...)` | 通过同一插件校验和缓存创建应用持有的进程级提供者 |

`create_loop()` 的显式参数包括 `context_providers`（替换默认顺序）、
`developer_instructions`、`context_agent_id`、`completion_gates` 和 `automatic_memory_recall`。
默认行为保持原样；Desktop 指定既有提示顺序和根 Agent 预算，并只为对应根运行启用 plan/goal 门控。
这是宿主策略参数，不是可以任意更改已受理 Run 的配置；宿主仍需冻结并校验恢复输入。

Desktop 沙箱提供者也通过 `process_provider()` 获取，应用负责提供者的关闭和并发复用。
其现有沙箱配置继续兼容；自定义构造参数放在 `execution.sandbox` 的宿主配置
`provider_config` 中，单次沙箱的网络/资源等执行参数仍由沙箱规格处理。
提供者关闭和持久化沙箱暂停/释放是不同的职责，后者继续走 execution lifecycle。

阅读路径：Server 的 `bootstrap.py → packages/builder.py → runtime/loop.py → runtime/driver.py`；
Desktop 的 `backend/composition.py → run_composition.py`，配置翻译在 `component_plan.py`，
模型路由在 `model_providers.py`。两端的产品策略和插件实现保持独立。

## 生命周期与恢复约定

- 注入对象默认由宿主持有；需要转移所有权时显式使用 `with_owned_resources()`。构建失败时，尚未转交的宿主资源仍由宿主清理。
- `compose_run()` 回调只登记本次新建且归本次运行所有的资源：`resources.own(service)`；执行依赖可用 `dependency=True`。
- 成功后宿主关闭返回的 `ComposedRun`；装配失败由该边界回滚。不要把借用的进程资源登记成 Run 私有资源。
- 正常关闭时服务先于其依赖释放，失败的服务可重试清理；持久化沙箱暂停/释放仍走 execution lifecycle。
- 观察流断开不等于取消 Run。需要取消时走运行控制接口，不依靠丢弃 iterator。
- 同一次受理重试复用幂等键；新用户操作使用新键。示例每次启动默认生成新键，不实现生产级请求去重存储。
- 保留受理时的配置快照和身份。未知外部副作用应挂起或核对，不能通过“重新运行一遍”恢复。
- 默认内置配置适合本机示例；持久化 Session 不代表所有 scheduler/job/plugin 都具备跨进程恢复或分布式能力。

## 项目应具备的测试

至少覆盖：配置解析/最终绑定、离线 Run、资源关闭与构建失败、请求幂等、审批暂停/恢复、恢复时配置不漂移、未知副作用不被重放。
涉及子 Agent 时增加隔离、委派和子 Run 恢复测试；新插件另测其契约，并保持实现独立。

```bash
.venv/bin/pytest -q tests/sagents/v2/test_host_starter_example.py tests/sagents/v2/test_unified_host_configuration.py
.venv/bin/pytest -q tests/sagents/v2/test_builder_matrix.py tests/sagents/v2/test_run_composition_lifecycle.py
```

仓库测试默认有 30 秒防挂死时限；性能要求用独立断言，单项时限用 `pytest.mark.timeout(...)`。

Desktop 和 Server 的沙箱提供者均通过应用的插件生命周期创建。Server 的配置与 Agent 校验使用宿主预注册的同一个 registry。


## 验证入口

- Python：`.venv/bin/python -m pytest tests/sagents/v2 tests/app/v2/server tests/app/v2/desktop tests/app/clients/cli --ignore=tests/sagents/v2/live`。
- Desktop：在 `app/v2/desktop` 运行 `flutter test`。`unified_sidecar_test.dart` 使用真实 Python sidecar，默认仅替换模型响应。
- 真实模型：在同一目录运行 `SAGE_DESKTOP_LIVE_CATALOG="$HOME/sage/runtime/desktop-catalog.json" flutter test test/unified_sidecar_test.dart`。使用目录首个 Agent 绑定的模型；可通过 `SAGE_DESKTOP_LIVE_MODEL` 显式选择模型 ID。测试使用隔离数据目录，验证两轮回答和历史回忆，会产生真实模型请求费用。
- TUI：在 `app/clients/terminal` 运行 `cargo test --offline`，覆盖 CLI v2 启动参数、事件协议和交互。

底层装配回归使用私有 `_build_package` 检验执行图；第三方接入测试使用公开的
`build()` / `load_agent()`，不要在应用代码里调用私有装配器。

## 自己实现插件：从契约开始

本指南与两份逐字段参考配套阅读：[Runtime 配置参考](sagents-runtime-reference.md)、[sage.yaml 配置参考](sagents-manifest-reference.md)。

插件由两层协议组成：

1. **统一装配协议**：ExtensionDescriptor 描述插件身份、能力、API 版本、参数和 scope；ExtensionRegistration 提供 factory/start/stop。
2. **领域协议**：factory/start 返回的对象要实现该能力真正需要的方法，例如 ContextUnitCompactor.compact 或 ToolExecutor.execute/reconcile。注册成功只证明声明可解析，不会证明方法和恢复行为正确。

实现类可以使用结构化 Protocol，不要求继承内置插件或共同基类。插件之间保持独立；共享 SDK 契约，不导入其他插件的内部代码。一个插件可以提供多个能力，但必须为每一个 offer 返回正确对象。

### 哪些模块支持插件、各自是什么协议

下表覆盖当前内置注册表提供的全部 capability。方法列用于定位，**参数、返回值和异步要求以链接中的公共协议为准**。新增实现必须完整实现协议，不能只实现表中某个常用方法。对于暂时没有独立 Protocol 的扩展点，表中明确说明其实际适配契约，不把它包装成更稳定的承诺。

| capability | 协议 / 源码 | 方法 | 关键要求 |
| --- | --- | --- | --- |
| `agent.continuation-policy` | [ContinuationPolicy](../../../sagents/v2/agent/policy/continuation.py) | `decide` | 返回继续、完成或请求交互的决策；不能绕开预算和授权 |
| `artifact.store` | [ArtifactStore](../../../sagents/v2/runtime/artifact/contracts.py) | `put`、`get`、`delete` | 不可变产物内容流与引用；不是 Session 主存储 |
| `context.reducer` | [ContextReducer](../../../sagents/v2/context/contracts.py) | `reduce` | 返回上下文投影；不能改写权威历史 |
| `context.summarizer` | [ConversationSummarizer](../../../sagents/v2/context/summary.py) | `summarize` | 根据请求生成摘要文本 |
| `context.summary-store` | [ConversationSummaryStore](../../../sagents/v2/context/summary.py) | `get`、`save`、`delete` | 遵守 expected_revision 的并发更新语义 |
| `context.unit-compactor` | [ContextUnitCompactor](../../../sagents/v2/context/contracts.py) | `compact` | 异步、无副作用；仅使用真实持久引用 |
| `context.unit-compactor` | [ContextUnitCompactor](../../../sagents/v2/context/contracts.py) | `compact` | 对不可拆分单元生成替代投影，不能破坏工具调用配对 |
| `credentials.provider` | [CredentialProvider](../../../sagents/v2/runtime/credentials/provider.py) | `resolve` | 将声明解析为 CredentialMaterial，不把密钥写日志 |
| `execution.job-runtime` | [JobRuntime](../../../sagents/v2/runtime/execution/jobs/provider.py) | `capabilities`、`submit`、`inspect`、`wait`、`cancel`、`read_output`、`handle_run_pause`、`list_run_jobs`、`mark_orphaned`、`adopt`、`purge_terminal`、`close` | 后台工作状态、输出游标、取消、孤儿认领和清理 |
| `execution.sandbox` | [SandboxProvider](../../../sagents/v2/runtime/execution/sandbox/provider.py) | `capabilities`、`provision`、`attach`、`inspect`、`snapshot`、`restore`、`release`、`terminate`、`purge_terminated` | API v3；返回 SandboxHandle，提供 filesystem/process/network 子端口；宿主必须授权执行绑定 |
| `execution.scheduler` | [Scheduler](../../../sagents/v2/runtime/execution/scheduler/provider.py) | `capabilities`、`submit`、`claim`、`renew`、`release`、`assert_fence`、`execute_fenced`、`cancel`、`close` | 租约、fencing 与原子执行是语义要求，不只是方法名 |
| `flow.node` | [RunnableNode](../../../sagents/v2/flow/contracts.py) | `run` | 节点结果必须表达完成/挂起/失败，遵守检查点和重复执行边界 |
| `interface.protocol-adapter` | [ProtocolAdapter](../../../sagents/v2/interfaces/protocols/contracts.py) | `capabilities`、`translate` | RuntimeEvent 的单向投影，保留 source identity 和丢失信息说明 |
| `memory.provider` | [MemoryProvider](../../../sagents/v2/memory/contracts.py) | `capabilities`、`recall`、`remember`、`forget`、`get`、`health` | 长期记忆，保持访问范围和幂等写入语义 |
| `memory.recall-query` | [MemoryRecallQueryGenerator](../../../sagents/v2/memory/query.py) | `generate` | 将用户输入转换为召回查询 |
| `model.provider` | [ModelProvider](../../../sagents/v2/model/provider.py) | `capabilities`、`probe_capabilities`、`stream` | capabilities/probe_capabilities/stream；输出 ModelStreamEvent，不直接伪造 RuntimeEvent |
| `observability.diagnostic-sink` | [DiagnosticSink](../../../sagents/v2/runtime/observability/contracts.py) | `begin_model_request`、`complete_model_request`、`record_model_first_token`、`fail_model_request` | 模型请求/响应诊断，不能作为恢复权威输入 |
| `observability.log-sink` | [LogSink](../../../sagents/v2/runtime/observability/contracts.py) | `write`、`close` | 同步日志投影，声明 format_version，避免阻塞执行 |
| `observability.trace-sink` | [TraceSink](../../../sagents/v2/runtime/observability/contracts.py) | `start_span`、`add_event`、`end_span`、`close` | 同步 span/event 投影，声明 format_version，异步导出应有有界队列 |
| `package.registry` | [InMemoryAgentPackageRegistry](../../../sagents/v2/package/registry/registry.py) | `capabilities`、`save_draft`、`validate`、`test`、`publish`、`retire`、`get`、`list` | 当前以注册表对象接口适配，没有独立 Registry Protocol；单个进程服务不是分布式仓库保证 |
| `session-memory.provider` | [SessionMemoryProvider](../../../sagents/v2/session_memory/contracts.py) | `capabilities`、`sync`、`recall`、`forget_session`、`health` | 同步会话记忆索引、检索及清理 |
| `session.store` | [SessionStore](../../../sagents/v2/runtime/session/contracts.py) | `capabilities`、`create_run`、`get_run`、`list_dispatchable_runs`、`get_run_result`、`get_session`、`get_start_command`、`get_run_context`、`put_attachment`、`get_attachment`、`copy_attachment`、`export_session_backup`、`restore_session_backup`、`get_checkpoint`、`get_suspension`、`get_interaction`、`get_execution_resource`、`list_pending_execution_releases`、`list_execution_resources`、`get_interaction_resolution`、`authorize_session_actor`、`delete_session`、`list_descendant_sessions`、`list_session_runs`、`propose_session_commit`、`publish_session_commit`、`reject_session_commit`、`get_session_commit_proposal`、`list_session_commit_proposals`、`read_session_events`、`read_events`、`read_stream_previews`、`read_fork_base_events`、`subscribe_events`、`publish_stream_preview`、`commit_model_stream_batch`、`commit_run`、`commit_execution_resource`、`enqueue_steer`、`claim_steers`、`resolve_interaction`、`request_resume` | 权威 Run/Session/事件/检查点事务；不是任意 key-value 存储 |
| `skill.catalog` | [SkillCatalog](../../../sagents/v2/skill/contracts.py) | `list_skills`、`get_skill` | 发现允许使用的 Skill 描述 |
| `skill.loading` | [SkillLoadingPlugin](../../../sagents/v2/skill/plugins/loading.py) | `create_loader` | 当前是 create_loader(**ports) 的工厂适配契约，没有独立 SkillLoading Protocol；返回兼容 SkillLoader 的加载器 |
| `skill.source` | [SkillSource](../../../sagents/v2/skill/contracts.py) | `fetch` | 取得 SkillBundle；materialize 由另一个工作区端口负责 |
| `tool.catalog` | [ToolCatalog](../../../sagents/v2/tool/provider.py) | `list_tools`、`get_tool` | 工具 schema 与副作用元数据；白名单仍由 Agent/宿主控制 |
| `tool.executor` | [ToolExecutor](../../../sagents/v2/tool/provider.py) | `execute`、`reconcile` | execute 与 reconcile 必须一起实现；取消另看 CancellableToolExecutor |
| `tool.selection-policy` | [ToolSelectionPolicy](../../../sagents/v2/tool/selection.py) | `prepare`、`select`、`expand_tools`、`expanded_tools`、`restore_expanded_tools`、`release_run` | 选择模型可见工具，不得扩大授权范围 |
| `workspace.initializer` | [WorkspaceInitializer](../../../sagents/v2/workspace/contracts.py) | `initialize` | 同步 initialize(root)，返回创建的文件；不能越过工作区导入宿主私有状态 |

一些端口通过 Builder 注入，**不是额外的 capabilities 插件名**：

| 端口 | 注入方式 / 契约 | 边界 |
| --- | --- | --- |
| DerivedStateStore | `with_derived_state_store`；[协议](../../../sagents/v2/runtime/session/contracts.py) | 摘要等可重建状态，支持版本竞争控制 |
| SkillWorkspace | `with_skill_provider(catalog, source, workspace)`；[协议](../../../sagents/v2/skill/contracts.py) | 受控 materialize，不能由 Skill 自行取得宿主路径权限 |
| ExecutionBindingProvider | `with_execution_binding_provider`；[协议](../../../sagents/v2/runtime/execution/binding.py) | 宿主授予的工作区/沙箱绑定，涉及恢复与释放 |
| 模型并发预算 | `with_model_budget` | 宿主共享的模型并发资源 |
| Run driver | `with_run_driver_factory` / HostAgentExecution | 高级宿主受理快照与恢复契约，普通项目无需实现 |

### 一个完整、独立的插件

以下插件使用工具提供的真实持久引用压缩工具结果，不进行 token 估算。

```python
"""Standalone compactor example using exact characters and durable references."""
from pydantic import BaseModel, ConfigDict, Field
from sagents.v2.contracts.items import TextBlock
from sagents.v2.runtime.extensions import CapabilityOffer, ExtensionDescriptor, ExtensionRegistration, ExtensionScope


class ReferenceConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    minimum_characters: int = Field(default=4, gt=0)


class ReferenceCompactor:
    def __init__(self, *, minimum_characters=4):
        self.minimum_characters = minimum_characters

    async def compact(self, messages):
        projected = []
        for message in messages:
            reference = message.metadata.get("context_reference", {})
            uri = reference.get("uri") if isinstance(reference, dict) else None
            if message.role == "tool" and uri and len(message.model_dump_json()) >= self.minimum_characters:
                projected.append(message.model_copy(update={"content": (TextBlock(text=f"[Stored tool result: {uri}]"),)}))
            else:
                projected.append(message)
        return tuple(projected) if tuple(projected) != messages else None


def compactor_registration() -> ExtensionRegistration:
    return ExtensionRegistration(
        descriptor=ExtensionDescriptor(
            plugin_id="example.context.reference-compactor", version="2.0.0", name="Example reference compactor",
            provides=(CapabilityOffer(capability="context.unit-compactor", api_version="2"),),
            supported_scopes=frozenset({ExtensionScope.AGENT}), config_schema=ReferenceConfig.model_json_schema(),
        ), config_model=ReferenceConfig,
        factory=lambda context, dependencies: ReferenceCompactor(**context.config),
    )
```

在 App 创建前注册，参数仍走 runtime 标准：

```python
from sagents.v2 import SAgentBuilder
from sagents.v2.composition.defaults import default_runtime

builder = SAgentBuilder()
builder.register(compactor_registration())
config = default_runtime("./runtime").model_dump(mode="json")
config["capabilities"]["context.unit-compactor"] = {
    "plugin": "myproject.context.reference-compactor",
    "config": {"minimum_characters": 3},
}
app = await builder.build(runtime=config)
try:
    agent = await app.load_agent("./agents/assistant")
finally:
    await app.close()
```

可直接运行的同类实现见 [plugins.py](../../../examples/sagents_v2_host/plugins.py)，接线见 [bootstrap.py](../../../examples/sagents_v2_host/bootstrap.py)。不要只在 YAML 填一个 Python 包名；注册表必须有真实工厂。

### 注册协议逐项说明

| 对象 / 字段 | 必填 / 默认 | 责任 |
| --- | --- | --- |
| `ExtensionDescriptor.plugin_id` | 必填 Identifier | 稳定且不冲突的插件 ID |
| `version` | 必填 string | 插件实现版本；与 capability API 版本分开 |
| `api_version` | `2` | descriptor API 标识 |
| `name` / `description` | name 必填，description="" | 可读名称和用途 |
| `provides` | 非空 CapabilityOffer 数组 | 这个插件实际提供的能力集合 |
| `dependencies` | `[]` | 所依赖能力的声明，按图解析，不能有不可满足的依赖 |
| `supported_scopes` | 非空集合 | 真正能正确工作的生命周期范围 |
| `default_scope` | null | 必须属于支持集合；缺省可按 process→tenant→agent→run 选择最宽范围，但具体装配点还会明确请求 scope |
| `config_schema` | `{}` | JSON Schema；建议显式限制 additionalProperties=false |
| `capabilities` | `{}` | provider 保障声明；应与实际能力一致 |
| `built_in` | false | 元数据；第三方不能靠自填 true 取得内置信任 |
| `availability` | available=true，reason=null | 可用性探测结果，不能隐瞒未安装的可选依赖 |
| `ExtensionRegistration.factory` | 必填 | `(context, dependencies) → instance`，可同步或异步 |
| `start` | null | 可选 `(instance, context, dependencies) → provider 映射`，可异步 |
| `stop` | null | 可选 `(instance, reason) → None`，可异步 |
| `config_model` | null | 推荐提供 Pydantic 类型模型，补默认值并验证参数，与 schema 保持一致 |

CapabilityOffer：capability 与 api_version 必填，name 默认 default，multi_provider 默认 false。同一 descriptor 不能重复 `(capability, name)`。多数能力 API 为 2，沙箱能力为 3，必须看对应 offer/宿主要求，不能全部机械填 2。

ExtensionDependency：capability 必填，api_version 默认 `>=2,<3`，name 默认 null，optional 默认 false。通过 ProviderSet 获取声明的依赖，不要在插件中重新创建一个 App 或隐式查找另一个插件单例。长生命周期实例不能持有已销毁的短生命周期依赖。

ExtensionScopeContext：scope、scope_id 必填，tenant_id/agent_id/run_id 默认 null，config 默认 `{}`。这里只获得对应作用域身份；不要在 process 插件里把第一次看到的 run_id 保存成所有请求的身份。

### 多端口插件和资源清理

例如一个插件同时提供 ToolCatalog、ToolExecutor，它可以返回一个容器实例，并显式分配两个端口：

```python
from sagents.v2.runtime.extensions import CapabilityKey

def start_tools(instance, context, dependencies):
    return {
        CapabilityKey(capability="tool.catalog", name="custom"): instance.catalog,
        CapabilityKey(capability="tool.executor", name="custom"): instance.executor,
    }

async def stop_tools(instance, reason):
    await instance.close()
```

将 start_tools、stop_tools 交给 ExtensionRegistration；descriptor.provides 必须声明同样两个 key。工具 catalog 的 name 要与对应 executor 匹配。单端口插件若不提供 start，也没有 instance.start，默认把 instance 本身作为提供对象。

启动与关闭顺序：

1. 按 schema/config_model 校验参数、解析依赖和 scope 后创建实例；factory 内部失败时，它自己要清理尚未返回给宿主的资源。
2. 有注册 start 时调用它，否则调用实例 start；两者都没有时使用实例作为 provider。实际返回 key 必须符合 provides。
3. 成功实例归作用域管理；后续启动失败会回滚已启动实例。
4. 关闭优先调用 registration.stop，再尝试 instance.stop(reason)，最后 instance.close()。支持 awaitable，按依赖生命周期释放。
5. StopReason 包括 scope_closed、start_failed、host_shutdown、reload。close/stop 应可安全重复或在失败后继续清理；不要依赖析构函数释放连接。

process/tenant/agent 范围可能同时服务多个 Run。将每个 Run 的暂存数据按 run_id 隔离并有界清理；外部 I/O 不要放在长期持有的共享锁内。资源被宿主借用时不要重复关闭宿主对象。

### 不同领域必须守住的语义

- **模型插件**：capabilities/probe 输出真实能力，stream 保持文本增量、工具调用 ID 与结束语义；供应商异常转换为可判断的错误，不伪造成功响应。调用过程有取消/断流，不能把任意中断当作已完成。
- **工具插件**：ToolDefinition 的副作用、幂等和取消能力必须真实；execute 使用 operation_id 对接外部幂等/对账。无法判定副作用是否已经发生时 reconcile 返回不确定，交给框架挂起处理，不能简单重放。
- **SessionStore**：实现完整事务/CAS、事件序列、幂等、actor 授权、检查点和恢复契约。仅能保存 messages 的后端不是合格 SessionStore。派生索引不能代替权威事件。
- **Scheduler**：execute_fenced 必须保证校验到 mutation 完成之间旧租约不会被新租约取代；仅 assert_fence 后无锁调用 callback 不满足协议。并发租户限额也必须符合能力声明。
- **Sandbox/Job**：提供真实可查询状态、重连/取消/释放结果；不能用“接口返回成功”冒充外部进程已终止。宿主决定网络和路径授权，插件负责落实。
- **摘要/Context**：只改变模型看到的投影；保留工具调用/结果配对及必要引用，不删除或重写原始 Session 历史。持久摘要遵守修订号竞争检查。
- **协议适配器**：只转换 RuntimeEvent，不把 AG-UI/MCP/A2A 的展示帧当作权威执行状态。丢失信息要明确报告。
- **日志/Trace**：不是恢复输入；限流和缓冲有界，不能泄漏凭据。观察系统异常不应被伪装成业务状态。

### 插件应如何测试

先验证领域协议，再验证装配，不必所有测试都访问真实模型：

| 测试层 | 应覆盖内容 | 仓库参考 |
| --- | --- | --- |
| 参数 | 默认值、边界、未知参数、缺少依赖、不支持 scope | [扩展测试](../../../tests/sagents/v2/test_extension_discovery_matrix.py) |
| 装配 | 预注册→build→load_agent，确认选中自定义插件；错误配置不能替换旧版本 | [加载测试](../../../tests/sagents/v2/test_loaded_agents.py) |
| 生命周期 | factory/start 失败回滚，stop/close，借用对象不重复关闭 | [资源生命周期测试](../../../tests/sagents/v2/test_run_composition_lifecycle.py) |
| 领域语义 | 输入输出契约、并发、幂等、取消、异常和不确定结果 | 各领域 contracts/provider 以及对应 tests/sagents/v2 测试 |
| 恢复 | 挂起、进程重启、原版本继续；不能切换到新插件参数重放旧副作用 | [加载测试](../../../tests/sagents/v2/test_loaded_agents.py)、Session/执行恢复测试 |
| 独立性 | 不依赖其他插件私有实现，不跨层导入宿主 UI | [边界测试](../../../tests/sagents/v2/test_source_boundary_matrix.py) |

纯 estimator 至少验证空消息、Unicode、长输入和参数非法；工具/存储/调度器则需要真正的失败注入与恢复测试。最后用目标宿主的真实入口验收，不能只验证 factory 能返回对象。

## 旧数据升级与部署

旧 `sage.yaml` 顶层 `models` / `credentials` 不再被接受。新项目直接使用独立 App 模型配置；已有项目必须先迁移存储中的 Package，不能只修改磁盘示例。不要删除 Session 或修改 `resolved_spec_hash` 来规避错误。

仓库提供显式离线迁移脚本：

```bash
# Server：先审计，再停止所有写入进程并执行迁移。
python -m scripts.v2.migrate_app_models
python -m scripts.v2.migrate_app_models --writers-stopped --backup /secure/app-models-before.json

# Desktop：root 是实际 runtime 目录，不是工作区。
python -m scripts.v2.migrate_desktop_app_models --root /path/to/sage/runtime
python -m scripts.v2.migrate_desktop_app_models --root /path/to/sage/runtime --apply --writers-stopped
```

Server 脚本读取部署环境的数据库配置，在事务内写入；先用独占新文件保存原始记录，再更新 Package 内容、Bundle 引用及相关索引。当前迁移只接受旧 Server 标准模型引用；遇到额外连接或请求参数会中止，需先制定其 App 模型映射，不能静默丢弃。旧 Run 的身份保持不变；没有模型快照的历史 Run 保持原来按授权模型目录解析的恢复规则，不能凭迁移重建过去不存在的模型快照。

Desktop 脚本将原 `llm-provider:` 引用改成 App 模型 ID，迁移 RSI、目录和 Session 中的 Package。实际模型设置与运行环境中的 provider 快照保留。所有受影响的 JSON 文件和完整 RSI 数据库先备份到 runtime/backups；它不是跨文件事务，执行中断时应停止客户端、从该备份恢复后再重试。两个脚本都支持重复审计，迁移完成后待改动数量应为零。

先在备份副本验收，部署时确保所有旧写入进程停止。回滚需要同时恢复旧程序和迁移前数据；新旧 schema 不可混用。最后验证真实模型两轮对话、历史读取和挂起恢复，不能只依赖服务健康检查。
