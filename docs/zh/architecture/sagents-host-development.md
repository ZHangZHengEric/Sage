# 基于 SAgents v2 开发宿主项目

[English](../../en/architecture/sagents-host-development.md) · [代码阅读指南](code-reading-guide.md) · [可运行参考项目](../../../examples/sagents_v2_host/)

**新项目先采用一个装配入口、一份 Agent manifest 和统一的 Run 调试标识。**
CLI、HTTP 服务和桌面应用可以有不同产品行为，但不要分别实现模型预算、插件加载、Session 历史和恢复状态机。
本文的命令行参数是参考项目的约定，不是 SDK 自动读取的全局环境变量。

## 现在的开发入口

```text
SAgentBuilder.build(runtime=...) → App
    ↓ app.load_agent(Package)       一个 Package 一个 Agent，加载结果可复用
    ↓ app.entrypoint().run_stream(command, context, agent=agent)
    ↓ stream.events / stream.wait()
    ↓ app.update_agent(agent=agent, package=...)  发布新版本
await app.close()                   统一关闭所有版本及资源
```

参考项目的文件按职责划分：

| 文件 | 职责 |
| --- | --- |
| [sage.yaml](../../../examples/sagents_v2_host/sage.yaml) | 可版本管理的 Agent 配置；只引用凭据，不保存密钥 |
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

## 加载输入、复用和更新

```python
from pathlib import Path
from sagents.v2 import SAgentBuilder

app = await SAgentBuilder().with_defaults(session_root="./runtime").build()
try:
    agent = await app.load_agent("./agents/assistant")  # 目录中的 sage.yaml
    # 也支持 Path("./assistant.yaml")、SageManifest 或配置字典。
    # 文本显式写为 app.load_agent(config_text=yaml_or_json, base_path=package_root)。
    # runtime 同样支持 RuntimeConfig、字典、路径，文本使用 runtime_config_text=。
    newer = await app.update_agent(agent=agent, package="./agents/assistant")
finally:
    await app.close()
```

路径字符串不作为 YAML 猜测。`package` 与 `config_text`、`runtime` 与 `runtime_config_text` 分别互斥。
内存配置含 instruction 文件引用时必须给 `base_path`，且文件不能越出该目录。
一个新 Package 必须恰有一个 Agent，不再通过名称二次选择。
普通 SDK 的 `agent.id` 来自 Package ID，两个 Package 的内部 Agent 都叫 main 也不会冲突。
`StartRun.agent_id` 与 `resolved_spec_hash` 使用加载结果的 `agent.id` 与 `agent.composition_hash`；入口校验两者。

重复加载同一份有效配置返回同一个 handle。不同配置必须显式 update；更新保留逻辑 ID，返回新 handle。
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
| 选用的能力实现 | manifest 的 `runtime.capabilities` 与 `plugins` | 插件 ID、scope、插件参数 |
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
from examples.sagents_v2_host.plugins import estimator_registration

builder = SAgentBuilder().with_defaults(session_root="./runtime")
builder.register(estimator_registration())  # 先注册，再装配
app = await builder.build(runtime={
    "capabilities": {
        "context.token-estimator": {
            "plugin": "example.context.byte-estimator",
            "scope": "agent",
            "config": {"bytes_per_token": 4.0},
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
