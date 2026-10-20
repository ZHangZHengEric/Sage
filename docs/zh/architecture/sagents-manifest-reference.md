---
layout: default
title: Agent Manifest 配置参考
parent: 架构
nav_order: 14
lang: zh
ref: v2-detail-sagents-manifest-reference
---

{% include lang_switcher.html %}

# SAgents sage.yaml 配置参考

[接入开发指南](sagents-host-development.md) · [Runtime 配置参考](sagents-runtime-reference.md) · [代码阅读指南](code-reading-guide.md)

`sage.yaml` 定义一个 Agent Package。**一个 Package 恰好一个 Agent；一个 App 可以加载多个 Package。** App 负责运行环境与生命周期，Package 负责 Agent 的指令、模型 ID 引用、能力范围和预算。加载返回 Agent handle，不需要再用名称选择一次 Agent。

## 目录

- [最小配置与加载](#最小配置与加载)
- [文件、字符串与路径](#文件字符串与路径)
- [顶层字段总表](#顶层字段总表)
- [metadata](#metadata)
- [模型 ID 引用](#模型-id-引用)
- [agents](#agents)
- [预算与策略](#预算与策略)
- [entrypoint 与 flows](#entrypoint-与-flows)
- [runtime 与 plugins](#runtime-与-plugins)
- [interfaces](#interfaces)
- [tests 与 environments](#tests-与-environments)
- [子 Agent、复用、更新与恢复](#子-agent复用更新与恢复)
- [完整配置示例](#完整配置示例)
- [校验和常见错误](#校验和常见错误)

## 最小配置与加载

下面是结构完整的文本对话 Package。App 必须先配置模型 ID `primary`，连接参数与凭据写在独立的 `models.yaml` 中。

```yaml
schema_version: sage/v2
kind: agent-package
metadata:
  id: example.assistant
  version: "1.0.0"
  name: Assistant
agents:
  main:
    name: Assistant
    instructions:
      inline: "请准确回答用户问题。需要澄清时说明缺少的信息。"
    models:
      primary: primary
entrypoint:
  agent: main
```

```python
from sagents.v2 import SAgentBuilder

app = await SAgentBuilder().build(models="./models.yaml")
try:
    agent = await app.load_agent("./agents/assistant")
    # StartRun.agent_id = agent.id
    # StartRun.resolved_spec_hash = agent.composition_hash
    # stream = await app.entrypoint().run_stream(command, context, agent=agent)
finally:
    await app.close()
```

完整命令、身份、事件消费见[可运行参考项目](../../../examples/v2/host/)；无需真实模型的验收命令：

```bash
.venv/bin/python -m examples.v2.host --offline
```

`main` 是 Package 内部引用键，供 `entrypoint.agent` 使用；`metadata.id` 是 Package 身份。普通 SDK 的加载结果 `agent.id` 来自 Package ID，不要用内部 `main` 代替它创建 StartRun。Desktop/Server 可以保留它们自己的持久化 Agent ID；调用方始终使用实际加载/受理结果。

## 文件、字符串与路径

| 输入 | 调用 | 规则 |
| --- | --- | --- |
| Package 目录 | `app.load_agent("./agents/assistant")` | 读取其中 sage.yaml |
| 文件路径 | `app.load_agent("./assistant.yaml")` | 公开 load_agent 支持指定文件，路径字符串不会当成配置正文 |
| Path | `app.load_agent(Path("./agents/assistant/sage.yaml"))` | 与路径字符串相同 |
| 字典 | `app.load_agent({...})` | 按 SageManifest 校验 |
| 已校验模型 | `app.load_agent(manifest)` | 深复制配置，后续修改原字典不会修改已加载版本 |
| YAML/JSON 正文 | `app.load_agent(config_text=text)` | 必须使用命名参数，顶层是对象 |
| 内存配置引用文件 | `app.load_agent(config_text=text, base_path=package_root)` | instructions.path 必须是 base_path 内的真实文件 |

`package` 与 `config_text` 必须且只能提供一个。传文件路径时不能另传 base_path，基准目录由文件位置决定。直接使用低层 `SageManifestLoader.load` 则要求文件名为 `sage.yaml`；这是它与公开 `load_agent` 路径输入的区别。

不支持在任意字符串中自动展开 `${VAR}`；模型密钥通过 App 的 credentials 声明读取环境变量。YAML 重复键会被拒绝，未知模型字段会被拒绝。JSON null 与“未填写”须符合各字段类型；例如 budgets 接受 null，tools 则应写数组或省略。

## 顶层字段总表

| 字段 | 类型 | 默认 / 必填 | 作用 |
| --- | --- | --- | --- |
| `schema_version` | 固定字符串 | `sage/v2` | schema 版本 |
| `kind` | `agent-package` / `application` | `agent-package` | 文档种类标签；新 Package 推荐 agent-package，application 标签也不能绕过一个 Package 一个 Agent |
| `metadata` | 对象 | 必填 | Package 身份、版本和显示名称 |
| `runtime` | RuntimeConfig | 字段默认配置 | 可供宿主选用的 runtime 声明；load_agent 不会覆盖已创建 App 的 runtime |
| `plugins` | PluginDeclaration 数组 | `[]` | 插件声明与默认参数，ID 不可重复 |
| `policies` | PolicyConfig | budgets 全部 null | Package 预算上限 |
| `agents` | 内部 Agent 名 → AgentDefinition | schema 默认 `{}`，公开加载必须恰好一项 | Agent 定义 |
| `flows` | Flow 名 → FlowDefinition | `{}` | 显式流程图 |
| `entrypoint` | ApplicationEntrypoint | 必填 | Package 入口；统一 load_agent 路径选择唯一 Agent |
| `interfaces` | 接口名 → InterfaceDeclaration | `{}` | 协议适配器声明 |
| `tests` | TestDeclaration | scenarios=[]，gates={} | 测试元数据，不因 load_agent 自动执行 |
| `environments` | 环境名 → overlay 对象 | `{}` | 由宿主显式选择的环境覆盖 |

通用 Identifier：1–192 字符，首字符字母或数字，其余允许字母、数字、`._:@/-`。ToolName 更严格：字母开头，后续仅字母、数字、下划线，最长 192。SkillName 允许空格，但不能有 `/`、`\`、NUL，最长 192。指令正文保留前后空白；大多数普通字符串会去除首尾空白。

## metadata

| 字段 | 类型 | 默认 | 含义 |
| --- | --- | --- | --- |
| `id` | Identifier | 必填 | 稳定 Package ID；更新时保持不变 |
| `version` | string | 必填 | 面向开发者的版本标签；建议引号包裹，如 "1.0.0" |
| `name` | string | 必填 | 显示名称 |
| `description` | string / null | null | 可选说明 |

metadata.version 不是加载缓存的唯一依据。实际版本身份包括解析内容与固定的子 Agent 图；`agent.composition_hash` 才是本次装配身份。不要通过只修改 version 让旧运行自动采用新定义。

## 模型 ID 引用

模型路由和凭据由 App 统一管理，在 `models.yaml` 中配置。`sage.yaml` 只保存槽位与 App 模型 ID 的绑定：

```yaml
agents:
  main:
    name: Assistant
    instructions: {inline: "准确回答问题。"}
    models: {primary: primary, fast: primary}
```

同一 ID 可以供多个 Package 使用；这里的 `primary`、`fast` 是用途槽位，右侧值才是 App 模型 ID。模型不存在时加载失败，不会自动选择其他模型。子 Agent 的 `delegation_model_bindings` 同样引用 App 模型 ID。

顶层 `models` 和 `credentials` 已移除，即使为空也会报错。不要在 Package 中复制模型连接配置。完整字段、默认值、推理参数、能力探测和更新方式见 [App 模型配置](sagents-runtime-reference.md#app-模型配置)。

## agents

虽然字段名仍为 agents 映射，公开 Package 必须只有一个条目。不要为多个 Agent 向这个映射增加键；把它们分别保存成 Package。

| AgentDefinition 字段 | 类型 | 默认 / 必填 | 含义 |
| --- | --- | --- | --- |
| `name` | string | 必填 | Agent 显示名 |
| `description` | string / null | null | 可选说明 |
| `instructions` | Instructions | 必填 | inline 或 path 二选一 |
| `mode` | simple / fibre / team | simple | Agent 运行模式；声明 subagents 不会自动授权委派 |
| `models` | 槽位 → App 模型 ID | `{}` | 本 Agent 模型绑定 |
| `delegation_model_bindings` | 槽位 → App 模型 ID | `{}` | 作为子 Agent 时显式指定覆盖父 Run 选择的模型绑定 |
| `entrypoint` | AgentEntrypoint | loop/react | Agent 内部执行方式 |
| `tools` | ToolName 数组 | `[]` | 工具允许范围；不是安装工具的声明 |
| `tool_approval` | ToolApprovalConfig / null | null | Agent 的工具审批偏好；不能替代宿主授权 |
| `skills` | SkillName 数组 | `[]` | Skill 允许范围；需宿主有对应 catalog/source |
| `preload_skills` | SkillName 数组 | `[]` | 每个新 Run 首次模型调用前预加载一次；必须是本 Agent `skills` 的子集 |
| `subagents` | Identifier 数组 | `[]` | 可委派子 Agent 的别名；加载时必须绑定独立 handle |
| `budgets` | AgentBudgets | 每项 null | 本 Agent 预算，与 Package 上限合并 |
| `memory` | AgentMemoryBehavior | 见下表 | 记忆行为开关 |
| `sandbox` | AgentSandboxConfig | network=none | 向宿主请求的网络范围，不是执行授权 |

`preload_skills` 属于每个 Agent 的独立配置，例如：

```yaml
skills: [python, testing]
preload_skills: [testing]
```

父 Agent、各层级子 Agent，以及同一 Session 续接产生的新 Run，均在首次模型调用
（包括辅助模型调用）前按各自配置初始化。预加载仍受当前 Run 的技能授权约束，
不能扩大权限；加载失败报告 `skill.preload_failed`，包含 Agent、Run、技能及底层错误。
默认技能和手动加载的技能使用相同预算，可被淘汰；不要求常驻、不自动补回，
需要时可调用 `load_skill`。初始化顺序按声明顺序，预算不足可淘汰较早加载的技能；
单个技能本身超过加载预算则初始化失败。

暂停或进程重启后恢复同一 Run 时，恢复持久化的初始化进度和激活列表，
不补回已淘汰技能；初始化中途恢复只继续尚未完成的部分。未配置字段时保持现有懒加载行为。

Instructions 示例（二选一，不能同时写，也不能都省略）：

```yaml
instructions:
  path: prompts/assistant.md
```

path 指向 Package 目录内部的文件；越界路径、指向目录或通过符号链接逃出目录会被拒绝。加载时读取并固定内容；修改文件后需 update_agent，不会让已加载 Agent 静默变化。

| memory 字段 | 类型 | 默认 | 含义 |
| --- | --- | --- | --- |
| `recall` | boolean | false | 是否使用长期记忆召回 |
| `auto_write` | boolean | false | 是否自动写入记忆 |
| `scope` | string | agent | 记忆作用域标识，由宿主/记忆服务约束 |

`sandbox.network` 只接受 none/unrestricted，默认 none。unrestricted 只是请求，宿主可以拒绝；这里不配置目录映射、密钥或进程执行权限。

ToolApprovalConfig：default=auto_approve（也可 ask）；tools 默认 `{}`，每个工具的值为 inherit/ask/auto_approve。inherit 回到 default。null 表示没有显式 Agent 审批配置。批准偏好不会扩大 tools 白名单、模型权限、沙箱范围或已有 Run 的授权。

```yaml
tool_approval:
  default: ask
  tools:
    Read: auto_approve
    Execute: inherit
```

这里的工具名仅演示结构，必须换成你实际注册并允许的名称。

## 预算与策略

`policies` 目前只有 budgets；`policies.budgets` 与 `agents.main.budgets` 具有相同字段。字段默认为 null，表示该层未设置约束。

| 字段 | 类型 / 范围 | 单位 | 作用 |
| --- | --- | --- | --- |
| `max_steps` | 正整数 / null | 步 | Agent 执行步数上限 |
| `input_tokens` | 正整数 / null | tokens | 输入上下文预算 |
| `system_tokens` | 正整数 / null | tokens | 系统部分预算 |
| `protected_recent_tokens` | 非负整数 / null | tokens | 最近历史保护预算，允许 0 |
| `output_tokens` | 正整数 / null | tokens | 输出预算 |
| `total_tokens` | 正整数 / null | tokens | 总 token 预算 |
| `wall_time_seconds` | 正数 / null | 秒 | 运行时间预算 |

Package 与 Agent 两层都设置时，取非空值中的较小值形成策略上限；还受宿主与单次运行限制。Agent 的 max_steps 未设置时，解析器还读取 entrypoint.config.max_steps；新配置请统一写 budgets.max_steps，避免同一项多处定义。不要把 null 当成服务保证无限执行，也不要把预算超时当成 HTTP 观察流超时。

```yaml
policies:
  budgets: {max_steps: 40, total_tokens: 100000}
agents:
  main:
    name: Assistant
    instructions: {inline: "完成用户任务。"}
    budgets: {max_steps: 20}
```

该片段展示合并关系：max_steps 最终上限为 20；片段不是可单独加载的完整 Package。

## entrypoint 与 flows

顶层 entrypoint 的 schema 支持 agent 或 flow，且必须二选一；**当前统一 app.load_agent 路径要求入口为 Package 中的唯一 Agent**。不要仅设顶层 flow 后期待它生成 Agent handle。使用 Flow 时，让唯一 Agent 的内部 entrypoint 指向 flow。

AgentEntrypoint 字段：type 默认为 loop（可选 flow），loop 默认为 react（可为 null），flow 默认为 null，config 默认 `{}`。标准 loop 装配支持 react；config 不是任意开关注册表，传入不受支持的内容不代表引擎会使用它。

```yaml
agents:
  main:
    name: Workflow
    instructions: {inline: "按显式流程执行。"}
    entrypoint: {type: flow, loop: null, flow: work}
flows:
  work:
    version: "1"
    start: done
    nodes:
      - {id: done, type: end}
entrypoint: {agent: main}
```

这是无需外部节点依赖的流程结构片段。真实 tool、interaction、subflow 节点必须有对应注册与执行契约，不能仅靠 YAML 名字完成安装。

| FlowDefinition 字段 | 类型 | 默认 | 用途 |
| --- | --- | --- | --- |
| `version` | string | 必填 | Flow 版本 |
| `start` | Identifier | 必填 | 起始节点 ID |
| `nodes` | FlowNode 数组 | 必填 | 节点集合 |
| `edges` | FlowEdge 数组 | `[]` | 连边 |

| FlowNode 字段 | 类型 | 默认 | 用途 |
| --- | --- | --- | --- |
| `id` | Identifier | 必填 | 节点 ID |
| `type` | agent/tool/interaction/parallel/join/subflow/end | 必填 | 节点类型 |
| `agent` | Identifier / null | null | Agent 节点目标；外部目标在 load_agent 的 subagents 中绑定 |
| `tool` | ToolName / null | null | 工具节点目标 |
| `interaction` | Identifier / null | null | 交互节点引用 |
| `flow` | Identifier / null | null | 子流程引用 |
| `blocking_scope` | string / null | null | 阻塞作用域，按节点实现解释 |
| `config` | 对象 | `{}` | 节点专属参数，不能跨节点假定含义相同 |

FlowEdge：from、to 为必填 Identifier；when 为可选条件字符串，默认 null；priority 默认整数 0。from/to 对应源码 source/target 别名，YAML 推荐 from/to。具体条件与图合法性还需 Flow 编译/运行校验；schema 通过不代表所有节点可运行。

## runtime 与 plugins

runtime 的全部字段、组件默认值、插件参数在[Runtime 配置参考](sagents-runtime-reference.md)。这里最重要的是 App 级边界：`load_agent` 使用 App runtime，不能由后加载的 Package 重配共享进程服务。需要采用 manifest.runtime 时，先读取 manifest 再 `build(runtime=manifest.runtime)`。

PluginDeclaration：id 必填；version 可选字符串，默认 null；config 默认 `{}`。插件 ID 不可重复。version 声明与插件匹配/发现机制相关，不等于自动 pip 安装；应在宿主预注册对应实现。

```yaml
plugins:
  - id: example.context.reference-compactor
    config: {minimum_characters: 4}
runtime:
  capabilities:
    context.unit-compactor:
      plugin: example.context.reference-compactor
      config: {minimum_characters: 3}
```

在宿主选择这份 runtime 且已注册示例插件时，selection.config 的 3 优先于插件声明中的 4。普通 load_agent 不会因为看到这段 runtime 就自动改变 App。自定义插件参数同样经过 schema/config_model 校验，资源同样由作用域管理；插件实现保持独立。

## interfaces

```yaml
interfaces:
  chat:
    plugin: sage.protocol.ag-ui
    enabled: true
    config: {enable_sage_extensions: true}
```

| 字段 | 类型 | 默认 | 用途 |
| --- | --- | --- | --- |
| `plugin` | Identifier | 必填 | 协议适配器插件 |
| `name` | Identifier / null | null | 可选 provider 名称 |
| `enabled` | boolean | true | 是否启用该声明 |
| `scope` | process/tenant/agent/run/null | null | 使用装配默认；显式值需插件支持 |
| `config` | 对象 | `{}` | 插件参数 |

内置适配器包括 native、ag-ui、acp、a2a、mcp，ID 为 `sage.protocol.<名称>`。声明适配器不会自动创建 HTTP 监听端口、登录接口或路由；这些由宿主负责。Server 的现有 HTTP 接口也不是通过任意 Package 改写的。

## tests 与 environments

TestDeclaration：scenarios 为对象数组，默认 `[]`；gates 为对象，默认 `{}`。它们是声明数据，load_agent 不自动执行测试，不自动把 gates 变成生产权限或上线阻断。

```yaml
environments:
  development:
    policies:
      budgets: {max_steps: 5}
    runtime:
      capabilities:
        observability.log-sink:
          plugin: sage.logging.stdout
          config: {min_level: debug}
```

环境覆盖必须由宿主显式选择：

```python
from sagents.v2.package.manifest import SageManifestLoader
manifest = SageManifestLoader().load(
    "./agents/assistant/sage.yaml", environment="development"
)
# 然后 build(runtime=manifest.runtime)，再 load_agent(manifest)。
```

只允许覆盖 runtime、policies、interfaces。不能用 environments 改 agents、metadata 或 App 模型配置。对象递归合并，非对象值替换；不存在的环境名会报错。`app.load_agent` 没有 environment 参数，环境变量也不会自动选中某个 overlay。

## 子 Agent、复用、更新与恢复

父 Package 仍只定义 main：

```yaml
agents:
  main:
    name: Coder
    instructions: {inline: "完成任务，必要时委派 reviewer 审核。"}
    mode: fibre
    subagents: [reviewer]
```

reviewer 另存一个独立 Package，加载时绑定：

```python
reviewer = await app.load_agent("./agents/reviewer")
coder = await app.load_agent("./agents/coder", subagents={"reviewer": reviewer})
# 相同配置及绑定重复加载，复用同一个 handle。
reviewer_v2 = await app.update_agent(agent=reviewer, package="./agents/reviewer")
# 子版本更新不会静默改变父版本，明确发布父版本才采用新的 reviewer。
coder_v2 = await app.update_agent(
    agent=coder, package="./agents/coder", subagents={"reviewer": reviewer_v2}
)
```

绑定键必须与声明的子 Agent 名称（含 Flow 引用的外部 Agent）完全匹配，不能缺少或额外提供；handle 必须属于同一个 App。simple 模式不因声明 subagents 自动开放委派；fibre/team 的行为还受宿主、工具和授权控制。

托管 Bundle 的外层形态与 sage.yaml 不同：AgentPackageBundle 使用 manifest、files、dependencies；dependencies 的每项仍是独立 Bundle。**dependencies 不是 SageManifest 顶层字段，不能直接加进 sage.yaml。** 文件承载和源码插件授权由宿主托管流程处理。

更新必须保持 Package/Agent 身份；配置变更后普通 load_agent 会要求使用 update_agent。加载失败不会替换当前版本，过期 handle 的并发更新会被拒绝。旧 handle 与已受理 Run 保持原版本；恢复先 `await app.agent_for_run(run_id, context)`，再传给 continue_run。版本归档缺失或不匹配时不能自动以最新 Agent 替换。旧版本目前保留到 App 关闭。

## 完整配置示例

这是单 Agent、有显式模型预算与日志适配器的完整声明。运行前在 App 中配置模型 ID `primary`；如果采用其中 runtime，宿主须显式传给 build。没有配置工具和 Skill，避免误以为声明名称会自动安装它们。

```yaml
schema_version: sage/v2
kind: agent-package
metadata:
  id: example.support
  version: "1.0.0"
  name: Support Assistant
runtime:
  deployment_profile: controlled_host
  capabilities:
    session.store:
      plugin: sage.session.filesystem
      config: {root: /srv/support/runtime}
    observability.log-sink:
      plugin: sage.logging.stdout
      config: {stream: stderr, min_level: info, format: json}
policies:
  budgets: {max_steps: 30, total_tokens: 100000, wall_time_seconds: 600}
agents:
  main:
    name: Support Assistant
    instructions: {inline: "准确回答问题；缺少事实时明确说明。"}
    mode: simple
    models: {primary: primary, fast: primary}
    tools: []
    skills: []
    budgets: {max_steps: 20, output_tokens: 4096}
    memory: {recall: false, auto_write: false, scope: agent}
    sandbox: {network: none}
entrypoint: {agent: main}
interfaces:
  chat:
    plugin: sage.protocol.ag-ui
    config: {enable_sage_extensions: true}
```

模型能力和窗口数值只是示例声明，不能复制后当作供应商保证，应以目标模型的探测结果为准。

## 校验和常见错误

分三层验证，不能只验证 YAML 能解析：

1. **结构与引用**：SageManifestLoader 校验字段；CompositionResolver 结合 App 模型目录校验模型、入口和策略引用。公开 load_agent 额外保证一个 Package 一个 Agent。
2. **装配**：预注册插件，build App，load_agent，检查 resolved plan/readiness；这一步可以打开存储、连接外部服务，不是纯静态解析。
3. **执行**：通过真实入口完成对话、工具调用、挂起/恢复；供应商配置可能只有在真实请求时才暴露问题。

纯结构检查：

```python
from sagents.v2.package.manifest import SageManifestLoader
manifest = SageManifestLoader().load("./agents/assistant/sage.yaml")
assert len(manifest.agents) == 1
assert manifest.entrypoint.agent in manifest.agents
```

| 症状 | 原因 / 处理 |
| --- | --- |
| 一个 Package 放两个 Agent 被拒绝 | 拆成独立 Package，用 subagents 绑定 |
| 改 sage.yaml.runtime 没生效 | App runtime 已固定；修改宿主 build 参数并考虑旧 Run 恢复 |
| Changed Package 要求 update | 正常版本保护；使用当前 handle 调 update_agent |
| 找不到 instructions 文件 | 检查 Package 基准目录，内存输入提供 base_path |
| App credentials 声明存在但请求失败 | 检查环境变量/host provider，声明不是实际密钥 |
| 工具在 YAML 里但无法调用 | tools 只是允许范围；还需 catalog/executor、宿主授权和有效执行绑定 |
| subagents 声明存在却不委派 | 检查 mode、显式绑定和宿主授权 |
| Profile 显示支持却供应商报错 | 检查 route_fingerprint、实际模型协议和探测是否过期 |
| scope/required_guarantees 报错 | 实现不支持要求，不要通过删除校验假装具备能力 |

源码：[manifest 目录](../../../sagents/v2/package/manifest/)、[公开输入解析](../../../sagents/v2/composition/inputs.py)、[子 Agent 图解析](../../../sagents/v2/composition/agent_graph.py)、[加载与版本管理](../../../sagents/v2/composition/loaded_agents.py)。
