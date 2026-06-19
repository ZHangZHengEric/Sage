# Prompt Cache 友好的消息组织改造计划

## 背景

当前 Agent 的消息组织会把稳定规则、已加载 Skill、运行时上下文和 ToDo 状态混合到系统上下文链路中。这样虽然实现简单，但会导致一些高频变化内容进入靠前的 prompt 前缀，例如当前时间、工作区文件树、权限上下文、ToDo 状态等。

Prompt cache 的核心收益来自“下次推理时历史前缀尽可能不变”。因此，本改造的目标不是单纯减少 token，而是重新划分上下文的稳定度，把长期稳定内容继续放在前面，把每轮变化的内容移动到靠近最新用户输入的位置。

本方案不依赖 provider 侧的 `prompt_cache_key`。缓存收益主要来自消息顺序、内容稳定性、cache breakpoint 和历史压缩 anchor 的组织方式。

## 外部参考结论

### OpenAI Prompt Caching

OpenAI prompt caching 自动启用，命中依赖完全一致的 prompt prefix。官方建议将静态内容放在 prompt 开头，将动态、用户相关内容放在末尾。工具列表也可以被缓存，但必须保持一致。

参考：

- https://developers.openai.com/api/docs/guides/prompt-caching

### Anthropic Prompt Caching

Anthropic 缓存的是 `tools -> system -> messages` 顺序下，到 cache breakpoint 为止的完整前缀。只要 breakpoint 前任意 block 变化，下次 hash 就变化。官方特别提醒不要把 timestamp 这类每次变化的内容放在 cache breakpoint 前。

参考：

- https://platform.claude.com/docs/en/build-with-claude/prompt-caching
- https://platform.claude.com/docs/en/agents-and-tools/tool-use/tool-use-with-prompt-caching

### Hermes Agent

Hermes Agent 的实现中有几个值得参考的设计：

- system prompt assembly 明确包含 identity、platform hints、skills index、context files，并与 memory / ephemeral prompts 分开。
- skill index 有进程内 LRU 和磁盘 snapshot，只有 skill 文件或条件变化时才刷新。
- `pre_llm_call` plugin context 被注入 user message，而不是 system prompt。
- turn 开始时会从 conversation history hydrate todo store，而不是依赖每轮 system prompt 变更。
- Anthropic cache strategy 使用 system prompt + 最近 3 条非 system message 的 4 个 breakpoint。
- context compaction summary 被标记为 reference-only，避免历史任务被模型误读为当前任务。

参考：

- https://raw.githubusercontent.com/NousResearch/hermes-agent/main/agent/prompt_builder.py
- https://raw.githubusercontent.com/NousResearch/hermes-agent/main/agent/turn_context.py
- https://raw.githubusercontent.com/NousResearch/hermes-agent/main/agent/prompt_caching.py
- https://raw.githubusercontent.com/NousResearch/hermes-agent/main/agent/context_compressor.py

### Codex CLI

Codex CLI 的开源实现中，`ModelClient` 是 session-scoped，turn 级设置显式传入。请求结构将 stable instructions、input、tools、reasoning 等分开，并有专门的 compaction endpoint。这里最值得借鉴的是“session 稳定状态”和“turn 动态状态”的边界，而不是 provider 侧 cache key。

参考：

- https://github.com/openai/codex
- https://raw.githubusercontent.com/openai/codex/main/codex-rs/core/src/client.rs

### Claude Code

Claude Code 官方文档显示，它通过 `CLAUDE.md`、auto memory、path-scoped rules 和 skills 组织上下文。长期规则在 session 开始加载，路径相关规则按需加载，task-specific instruction 建议放到 skills，避免所有规则常驻上下文。

参考：

- https://code.claude.com/docs/en/memory

## 改造目标

1. 已加载 Skill 仍然加载到 system message 中，继续享受稳定前缀缓存。
2. Skill index 和已加载 Skill 内容必须保证确定性渲染：相同输入下文本、顺序、空白和分隔符都应一致。snapshot / manifest 是性能优化和稳定性保险，不是 prompt cache 命中的必要条件。
3. ToDo list 从 system context 中移出，不再通过更新 system context 影响 prompt 前缀。
4. 同一 session 恢复时，从当前 session 的 ToDo 状态源读取活跃 ToDo，并注入到最新 user 的推理内容前缀中。
5. 大模型压缩结果仅在压缩会吞掉唯一活跃 ToDo 状态时附带 `todo_state_at_compaction_boundary`，该状态来自真实 ToDo 工具结果解析，而不是 LLM 总结。
6. system context 不再放到 system message 中，而是在每轮推理时放入 `<runtime_context>`，并注入到当前用户消息的前缀中。
7. 压缩摘要必须是 reference-only anchor，不能让历史 remaining work 或旧 ToDo 复活成当前任务。
8. 尽可能保证历史消息 ledger 一旦写入，后续推理不改写旧消息，从而提高缓存命中率和可审计性。

## 当前相关实现

### System Message 构建

`sagents/agent/agent_base.py` 中的 `_build_system_segments()` 当前将系统提示拆成三段：

- `stable`：角色定义、规则、AGENT/USER/SOUL/MEMORY 等相对稳定内容。
- `semi_stable`：可用 Skill 列表、已加载 Skill 内容、Skill 使用提示。
- `volatile`：`system_context`、workspace files、external paths 等高频变化内容。

虽然已经做了稳定度分段，但三段最终仍作为 system messages 前置到历史消息之前。后续应保留 `stable` / `semi_stable`，将 `volatile` 改造成 runtime user context。

### 推理消息组装

`sagents/agent/simple_agent.py` 中的 `run_stream()` 会：

1. 从 `MessageManager.extract_all_context_messages()` 获取历史消息。
2. 调用 `prepare_unified_system_messages()` 构造 system messages。
3. 将 system messages 前置到 history messages。
4. 进入 `_execute_loop()` 发起 LLM 请求。

后续应在这条链路上引入统一 inference view builder，用于向最新 user 临时注入 runtime context 和 todo context。

### ToDo 状态

`sagents/tool/impl/todo_tool.py` 当前将 ToDo 写入 `TODO_LIST_{session_id}.md`，同时在 `_save_todo_file()` 后调用 `_sync_to_system_context()`，把任务列表同步到 `session_context.system_context["todo_list"]`。

这会让 ToDo 的变化污染 system context，并间接影响 system prompt 的稳定前缀。

### 压缩工具

`sagents/tool/impl/compress_history_tool.py` 当前压缩结果 schema 已有 `open_tasks` 字段，但主要由 LLM 根据历史消息总结。它没有强制从当前 ToDo 状态源读取真实 ToDo 并写入压缩结果，也没有足够明确地告诉模型“压缩摘要只是历史参考，不是当前任务指令”。

### Prompt Cache 断点

`sagents/utils/prompt_caching.py` 当前主要根据 `cache_segment` 给 `stable` 和 `semi_stable` system message 添加 cache control，并在最近的 user/assistant 消息上添加滚动断点。

当 volatile runtime context 从 system 移走后，这里的断点策略也需要同步调整。

## 目标消息布局

最终每轮请求的 inference view 推荐组织为：

```text
[system] stable_system

[system] semi_stable_system_with_skills

[user/assistant/tool history]
... 原始历史消息 ...
... reference-only compact anchor ...

[user]
<runtime_context>
...
  <system_context>
    ...
    <todo_list>...</todo_list>  # only when active ToDo exists
  </system_context>
</runtime_context>

<user_request>
用户最新输入
</user_request>
```

runtime context 合并进最新 user 的推理内容，不新增消息，因此不会插入 assistant tool_calls 与 tool result 之间。ToDo 不使用单独 `<todo_context>`，而是作为 runtime context 中 system context 的一部分。

## 关键设计决策

### 1. System 只保留稳定和半稳定内容

`stable_system` 包含：

- agent identity
- 基础行为规则
- 安全边界
- tool-use 规则
- 输出风格规则
- 长期不变的平台说明

`semi_stable_system` 包含：

- available skills index
- 已加载 skill 内容
- skills usage hint
- AGENT.md / USER.md / MEMORY.md 这类稳定项目规则

不再放入 system：

- current_time
- session_id
- workspace tree
- external_paths 文件树
- file_permission 动态描述
- todo_list
- shell completion reminder
- plugin runtime context

### 2. Skill 确定性渲染与 Snapshot 机制

参考 Hermes Agent，Skill 内容继续进入 system。需要优先保证的是“确定性渲染”：如果 Skill 文件、启用状态、语言、模板和工具条件都没有变化，即使每轮重新拼接，最终 system 文本也应该完全一致，从而仍然可以命中 prompt cache。

因此，cache 命中的必要条件不是 snapshot，而是：

- Skill 列表顺序稳定。
- 已加载 Skill 顺序稳定。
- 相同内容的渲染格式稳定，包括空白、换行和分隔符。
- 不把 current_time、workspace tree、临时状态等动态信息混入 Skill system block。
- Skill 是否可见的条件判断稳定，不依赖每轮变化的非必要状态。

snapshot / manifest 的价值主要是：

- 减少每轮重新扫描和渲染 Skill 的开销。
- 作为调试和观测手段，便于比较前后 system hash。
- 在未来 Skill 数量很大时降低 prompt 构造成本。
- 作为稳定性保险，避免不同代码路径渲染出细微不同的文本。

新增 Skill prompt snapshot，建议文件名：

```text
skills_prompt_snapshot.json
```

snapshot 内容建议包含：

```json
{
  "version": 1,
  "manifest": [
    {
      "name": "skill-name",
      "path": "/abs/path/SKILL.md",
      "mtime": 0,
      "size": 0,
      "hash": "optional"
    }
  ],
  "enabled_tools": ["..."],
  "disabled_skills": ["..."],
  "rendered_skill_index": "...",
  "rendered_loaded_skills": "..."
}
```

刷新条件：

- SKILL.md / DESCRIPTION.md mtime、size 或 hash 变化。
- enabled / disabled skill 变化。
- 可用工具集合变化导致 skill 条件匹配结果变化。
- 语言或渲染模板版本变化。

如果暂时不实现 snapshot，也可以先通过确定性排序和 system hash 观测达到 cache 目标。

### 3. Tools 稳定排序

Provider 的 prompt cache 不只看 messages，也会受到 tools schema、tool_choice 等请求结构影响。为了避免同一工具集合因为注册顺序不同而破坏缓存，进入 LLM 请求前应对 tools 做稳定排序。

建议规则：

1. 对 `tools` 按 `function.name` 升序排序。
2. 如果存在同名工具，按 `type`、namespace 或完整 JSON canonical string 作为次级排序键。
3. 排序发生在 provider 请求边界，即 `tool_manager.get_openai_tools()` 之后、发送 LLM 请求之前。
4. 工具 schema 的 JSON key 顺序也尽量 canonicalize，避免序列化层产生不必要差异。
5. baseline tools 尽量稳定常驻。tool expansion / deferred loading 属于低频动态变化，即使偶发影响一次缓存也可以接受。

动态 tools 的风险应按实际概率处理：如果 tool expansion 很少发生，就不需要为了它过度设计；只要基础工具集合和顺序稳定，大多数请求仍能获得稳定前缀。

### 4. Runtime Context 作为最新 User 前缀

将原本 `volatile` system 段里的内容改为本轮推理时临时构造的 `<runtime_context>`：

```xml
<runtime_context>
  <current_time>...</current_time>
  <session_id>...</session_id>
  <private_workspace>...</private_workspace>
  <file_permission>...</file_permission>
  <workspace_files>...</workspace_files>
  <external_paths>...</external_paths>
</runtime_context>
```

注入方式：

1. 找到最新真实 user message。
2. 将 `<runtime_context>` prepend 到该 user message 的 content。
3. 如果 user content 是多模态 list，则 prepend 一个 text block。

不建议插入额外 user message，因为这可能破坏某些 provider 的 tool_call / tool_result 严格序列，也会让历史消息块数量更不稳定。

### 5. Plugin / Shell / 临时提醒统一进入 Volatile User Context

Hermes Agent 将 `pre_llm_call` plugin context 注入 user message，而不是 system prompt。我们应采用相同边界：

- plugin runtime context
- shell completion reminder
- 当前 UI/平台提醒
- 一次性用户引导

这些都属于 volatile user context，不属于 system。

后续可以统一渲染为：

```xml
<runtime_context>
  ...
</runtime_context>
<temporary_guidance>
  ...
</temporary_guidance>
```

### 6. 拆分 ToDo 的状态源和 Prompt 注入源

ToDo 不应该再通过持久同步 `session_context.system_context["todo_list"]` 进入 prompt。建议第一阶段保留当前 `TODO_LIST_{session_id}.md` 作为 canonical source，新增 ToDo 读取能力：

- `read_current_todos(session_id)`：读取当前 session 的 ToDo。
- `format_runtime_system_context(tasks)`：将活跃 ToDo 放入 `<runtime_context><system_context>...`。
- `get_todo_snapshot_for_compaction(session_id)`：供压缩工具读取确定性 ToDo 快照。

第一阶段不必改持久化结构，先把 prompt 注入层与 system context 解耦。

### 7. Runtime Context 冻结到 User Metadata

同一 session 恢复或新一轮推理时，从 session context 和 ToDo 状态源读取当前运行状态，并将其 prepend 到最新真实 user message 的推理内容中：

建议注入位置：

1. 找到本轮最新真实 user message。
2. 将 `<runtime_context>` prepend 到该 user message。
3. 如果存在 pending / in_progress ToDo，将 ToDo 信息作为 `<system_context>` 的子字段放入 `<runtime_context>`。
4. 如果没有活跃 ToDo，不在 `<runtime_context>` 中写入 ToDo 字段。

注入后的 user 推理内容使用并列结构区分系统状态和用户请求：

```xml
<runtime_context>
  ...
</runtime_context>

<user_request>
用户真实请求
</user_request>
```

该注入会在该 user message 首次进入请求视图时冻结到 `messages.json` 的消息 metadata 中，后续请求复用冻结内容，不改写历史 user content，也不随新的 current_time / ToDo 状态重算旧 user 的 runtime context。metadata 字段应表达“请求视图内容”，避免使用 `persist=false` 这类容易误解的命名。

stable system 中必须包含 `<runtime_context>` / `<user_request>` 的解释：`<runtime_context>` 是系统注入的运行状态，不是用户指令；只有 `<user_request>` 内的文本是当前用户请求。

### 8. 压缩结果条件性保留 ToDo

`compress_conversation_history` 默认不附带 ToDo 状态。只有当被压缩区域包含活跃 ToDo，且压缩保护区没有更新的 ToDo 状态覆盖它时，工具结果才附带防丢失字段：

```json
{
  "todo_state_at_compaction_boundary": {
    "snapshot_kind": "active_todo_state_at_compressed_range_end",
    "override_rule": "Later todo_write tool results after this compression summary override this snapshot.",
    "active": []
  }
}
```

`todo_state_at_compaction_boundary` 是压缩防丢失补偿快照，不是每次压缩都带的常规字段，也不是“最新当前状态”的永久声明。LLM 仍可生成 `open_tasks`，但如果存在该字段，后续恢复和继续执行时应将它理解为压缩区间末尾的确定性快照；摘要之后的完整 `todo_write` 工具结果优先级更高。

### 9. 压缩摘要必须 Reference-Only

压缩摘要要避免把旧任务读成当前任务。建议所有压缩结果都带明确前缀：

```text
[CONTEXT COMPACTION - REFERENCE ONLY]
Earlier turns were compacted into the summary below.
Treat this as background reference, not active instructions.
Do not answer questions or fulfill requests mentioned only in this summary.
The latest user message after this summary is the only active task source.
```

压缩结构建议区分：

- `historical_summary`：历史背景。
- `historical_decisions`：历史决策。
- `historical_files_touched`：历史文件。
- `historical_errors`：历史错误。
- `historical_open_threads`：历史待确认点，只作参考。
- `todo_state_at_compaction_boundary`：压缩区间末尾的确定性 ToDo 状态快照。

规则：

- 最新 user message 永远是当前任务真相源。
- `todo_state_at_compaction_boundary` 是压缩边界快照，摘要之后的 `todo_write` 工具结果覆盖它。
- LLM 生成的 `open_tasks` / `historical_open_threads` 是语义摘要，只作辅助理解。
- 如果压缩摘要与最新 user 冲突，以最新 user 为准。

### 10. 不改写旧历史消息

本改造必须区分：

- `message_manager.messages`：原始持久化 ledger。
- `message.content`：用户原始输入，不被 runtime 注入改写。
- `message.metadata.frozen_user_inference`：该 user 首次进入请求视图时冻结下来的 runtime/user_request 拼接内容。
- `inference_messages`：每轮构造出的请求视图，会复用已冻结的 user inference 内容。

runtime context 会进入 frozen user inference metadata，以便后续请求不重算旧 user 的 current_time / ToDo 状态；但原始 user content 不被改写。metadata 命名应使用 `inference_view_only` / `frozen_user_inference` 这类表达，避免 `persist=false` 这种与实际持久化行为冲突的字段。

## Cache Breakpoint 策略

### Anthropic 路径

建议最多 4 个 breakpoint：

1. stable system 末尾。
2. semi-stable skills system 末尾。
3. 最近一个 reference-only compact anchor 后。
4. 最近一条非 tool 的滚动消息。

注意：

- 不要把 breakpoint 放在包含 current_time、workspace tree、runtime todo_list 的动态块上。
- 如果最新 user 中包含 `<runtime_context>`，它只能作为滚动断点候选，不能影响前面的 stable system 命中。
- tools schema 和顺序应尽量稳定。进入 LLM 请求前按 `function.name` 对 tools 排序，避免注册顺序扰动 tools/system/messages 层级缓存。

### OpenAI 路径

不做 `prompt_cache_key`。

优化方式是保持自动 prefix cache 可命中：

- instructions/system 静态内容尽量稳定。
- tools schema 和顺序尽量稳定，进入请求前按 `function.name` 做确定性排序。
- 动态内容全部后置到最新 user。
- 历史压缩 anchor 尽量稳定，不反复重写。

### 观测指标

需要统一记录每次请求的缓存相关 usage：

- prompt tokens
- cached tokens
- cache creation tokens
- cache read tokens
- cached tokens ratio
- stable system hash
- semi-stable system hash
- tools schema hash
- inference view message count

这些指标用于验证改造是否真的提升缓存命中，而不是只移动了内容。

## 可能遗漏与风险

### Tool Call 序列风险

OpenAI 兼容接口要求 assistant tool_calls 后面必须紧跟对应 tool result。runtime/todo context 应合并到最新 user 推理内容中，不能插入 assistant tool_calls 和 tool result 之间。

规避方式：

- runtime context 优先合并进最新 user content，而不是任意插入 user message。
- todo context 合并进最新 user content，而不是新增 assistant/user message。
- 构造 inference view 后增加合法性校验。

### Cache Breakpoint 策略需要更新

volatile system 移走后，`prompt_caching.py` 不能只按 system 段打断点。需要保留 stable / semi-stable system 断点，并增加 compact anchor 断点。

### ToDo 过期清理策略可能影响恢复

当前 ToDo 有过期清理逻辑。改造后，如果同 session 恢复依赖 ToDo 文件，需要确认清理阈值不会误删仍有价值的任务状态。

建议第一阶段将清理策略纳入测试，必要时调整为“只清理其他 session 的临时 ToDo，不清理当前 active session 的 ToDo”。

### 压缩摘要与真实 ToDo 可能冲突

LLM 生成的 `open_tasks` 和确定性 `todo_state_at_compaction_boundary` 可能不一致。

建议规则：

- `todo_state_at_compaction_boundary` 是压缩边界快照。
- `open_tasks` 是语义摘要，可辅助理解。
- 恢复执行时可用 `todo_state_at_compaction_boundary` 防止压缩区间末尾的活跃 ToDo 丢失。
- 摘要之后的完整 `todo_write` 工具结果覆盖该快照。
- 如果 `todo_state_at_compaction_boundary` 与最新 user 冲突，以最新 user 为准。

### 子 Agent / Team / Fibre 模式兼容

Team/Fibre 子会话会继承部分 `system_context`。移除 ToDo 和 runtime volatile system 后，需要检查：

- 子会话是否仍能获取 workspace、permission、parent_session_id。
- 子会话是否应该继承父会话 ToDo。
- member agent 的 skill/system prompt 是否仍稳定。
- 子 agent 的 runtime_context 是否应使用子会话 workspace，而不是父会话 workspace。

### Skill 渲染确定性与 Snapshot 失效边界

Skill cache 命中的关键是确定性渲染。如果每轮重新拼接但输入相同、顺序相同、格式相同，最终 prompt 仍然可以命中缓存。snapshot 不是必要条件，但如果引入 snapshot，判断过粗可能导致 skill 变更后模型仍使用旧 skill index。需要将 skill 文件 manifest、工具条件、语言、模板版本都纳入失效条件。

### Tools 顺序与动态 Tools 影响缓存

即使 message 前缀稳定，如果每轮 tools schema、tools 顺序或 tool_choice 改变，也会影响 provider 缓存。需要在进入 LLM 请求前按 `function.name` 对 tools 做确定性排序，并尽量稳定 baseline tools。

tool expansion / deferred loading 属于低频动态变化，偶发时影响一次缓存可以接受，不需要为了极低概率路径牺牲主路径复杂度。

## 实施计划

### 阶段 1：增加上下文构造能力，不改变行为

1. 新增 runtime context builder，先复用 `_build_system_segments()` 中 volatile 段的构造逻辑。
2. 新增 ToDo snapshot reader 和 formatter。
3. 给 Agent 请求构造层增加 latest-user inference-only 注入工具。
4. 固定 Skill 渲染顺序，记录 stable / semi-stable system hash。
5. 固定 tools 请求顺序，进入 LLM 请求前按 `function.name` 排序并记录 tools schema hash。
6. 可选新增 skill snapshot renderer，但先只记录 snapshot，不切换生产路径。
7. 保持 feature flag 回退旧 system context 注入逻辑，通过测试覆盖新 builder 输出。

### 阶段 2：Skill Snapshot 可选接入 System

1. 如果 Skill 渲染开销或不稳定风险较高，将 available skills index 渲染结果写入 snapshot。
2. 增加 manifest 失效判断。
3. 在无变化时复用 snapshot 渲染结果。
4. 继续记录 stable / semi-stable system hash，便于观测缓存稳定性。

### 阶段 3：将 Runtime Context 从 System 移到最新 User

1. 在 `prepare_unified_system_messages()` 中通过 feature flag 跳过 volatile 段。
2. 在 `SimpleAgent.run_stream()` 组装推理消息时，将 `<runtime_context>` prepend 到最新 user message。
3. 确保该修改冻结到 user metadata，但不写回原始 user content。
4. 增加 tool call 序列合法性测试。

建议 feature flag：

```bash
SAGE_RUNTIME_CONTEXT_IN_USER=true
```

### 阶段 4：ToDo 从 System Context 解耦

1. 修改 `ToDoTool._sync_to_system_context()` 行为：
   - 默认不再写入 `system_context["todo_list"]`。
2. 在最新 user 推理内容的 `<runtime_context><system_context>` 中注入活跃 ToDo。
3. 同 session 恢复时从 ToDo 文件读取当前状态。
4. 确保 ToDo 变化不会改写历史 messages 或 system messages。

建议 feature flag：

```bash
SAGE_TODO_CONTEXT_IN_USER=true
SAGE_TODO_IN_SYSTEM_CONTEXT=false
```

### 阶段 5：压缩工具条件性保留 ToDo 和 Reference-Only 语义

1. 在 `CompressHistoryTool.compress_conversation_history()` 中解析压缩段内的活跃 ToDo 状态。
2. 判断压缩段之后的保护区是否已有更新 ToDo 状态。
3. 仅当压缩段有活跃 ToDo 且保护区无更新 ToDo 时，将 `todo_state_at_compaction_boundary` 写入 `compression_payload` 和 `data`。
4. 更新压缩摘要 prompt，强制 reference-only 语义。
5. 更新 compression anchor 的恢复测试。

### 阶段 6：更新 Prompt Cache 断点策略

1. 保留 stable/semi-stable system 段断点。
2. 对压缩摘要 anchor 或稳定历史前缀增加断点能力。
3. 最新 user/runtime/todo 区域只作为滚动断点，不影响前面稳定缓存。
4. 更新 `tests/sagents/utils/test_prompt_caching.py`。

### 阶段 7：灰度与清理

1. 默认开启新路径前，先在测试和手动会话中比较请求 messages。
2. 记录 prompt cache 命中相关 usage 字段。
3. 观察无回归后，移除旧 volatile system 注入路径或保留为兼容开关。
4. 清理 `system_context["todo_list"]` 相关依赖。

## 测试计划

### 单元测试

1. system messages 不再包含 `<system_context>`、`todo_list`、workspace files。
2. runtime context 出现在最新 user content 前缀。
3. 活跃 ToDo 出现在最新 user content 的 `<runtime_context><system_context>` 中。
4. runtime 注入只写入 frozen user inference metadata，不改写原始 user content。
5. `todo_write` 更新后，下一轮 inference view 能读取到最新 ToDo。
6. `compress_conversation_history` 仅在压缩会丢失活跃 ToDo 时返回 `todo_state_at_compaction_boundary`。
7. 压缩摘要包含 reference-only 前缀。
8. cache control 仍打在 stable/semi-stable system 上。
9. cache control 可打在 compact anchor 后。
10. tool_call/tool_result 严格交替不被 runtime/todo 注入破坏。
11. Skill 在相同输入下重复渲染得到完全一致的文本。
12. tools 在进入 LLM 请求前按 `function.name` 稳定排序。
13. 如果启用 skill snapshot，skill 文件未变化时复用，变化时失效。

### 集成测试

1. 新 session：没有 ToDo 时不注入空噪声或只注入极短空状态。
2. 同 session 恢复：已有 ToDo 能出现在最新推理上下文。
3. ToDo 更新多轮后：历史 messages 不发生旧消息改写。
4. 压缩覆盖唯一活跃 ToDo 状态时，压缩工具结果中的 `todo_state_at_compaction_boundary` 可被后续上下文读取。
5. 压缩摘要中的历史 remaining work 不会在新用户换题后被继续执行。
6. Team/Fibre 子任务：子会话仍能获得 workspace 和权限上下文。
7. skill 变更前后 system hash 行为符合预期。
8. 工具注册顺序变化但工具集合相同时，tools schema hash 保持一致。

### 人工验收

1. 打印两轮连续请求 messages，确认前缀稳定部分 byte-level 尽量一致。
2. 对比开启/关闭新方案的 prompt cache 命中 token。
3. 检查 UI 展示和 session 恢复没有丢失 ToDo。
4. 长会话压缩后继续执行，确认模型能正确接续未完成任务。
5. 验证最新 user 与压缩摘要冲突时，模型遵循最新 user。

## 推荐落地顺序

推荐按以下顺序实施：

1. 固定 Skill 渲染顺序和 tools 请求顺序，记录 system hash / tools schema hash，不改变行为。
2. runtime context 从 system 移到最新 user。
3. ToDo 不再参与 system prompt，改为注入最新 user 的 inference-only 前缀。
4. 压缩工具条件性附带 `todo_state_at_compaction_boundary`，并加入 reference-only 语义。
5. 调整 cache control 断点。
6. 如有必要再接入 skill snapshot，作为性能优化和稳定性保险。
7. 灰度后清理旧兼容路径。

这个顺序能最早验证缓存收益，同时把持久化结构变更延后，降低风险。
