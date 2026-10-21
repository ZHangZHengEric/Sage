import { componentName, parameterDefaults } from './plugin-presentation.js'

// Presentation only. Availability and schemas always come from the host catalog.
const nodes = [
  ['tool.result-processor', '工具结果处理', '工具与技能', 'file'],
  ['context.reducer', '上下文压缩', '上下文准备', 'history'],
  ['context.summarizer', '摘要生成', '上下文准备', 'file'],
  ['tool.selection-policy', '工具选择', '模型与工具', 'tools'],
  ['model.provider', '模型配置', '模型与工具', 'model'],
  ['skill.loading', '技能加载', '工具与技能', 'skill'],
  ['memory.recall-query', '记忆检索词', '记忆与输出', 'search'],
  ['agent.continuation-policy', '完成判定', '记忆与输出', 'check'],
]

export function capabilityNodes(catalog, modelLabel = '') {
  const configurable = new Set(catalog?.configurable || [])
  const result = nodes.filter(([id]) => configurable.has(id) || (id === 'model.provider' && modelLabel))
    .map(([id, name, group, icon]) => ({ id, name, group, icon }))
  for (const id of configurable) if (!result.some(node => node.id === id)) result.push({ id, name: componentName(id), group: '其他能力', icon: 'settings' })
  return result
}

export function effectivePlugin(catalog, selections, capability) {
  const id = selections?.[capability]?.plugin || catalog?.defaults?.[capability]
  const definition = catalog?.plugins?.find(plugin => plugin.id === id && plugin.capabilities.includes(capability))
  const host = id === catalog?.defaults?.[capability] ? catalog?.default_config?.[capability] || {} : {}
  return { id, definition, available: Boolean(definition && definition.available !== false),
    config: { ...parameterDefaults(definition), ...host, ...(selections?.[capability]?.config || {}) } }
}

function canonical(value) {
  if (Array.isArray(value)) return value.map(canonical)
  if (value && typeof value === 'object') return Object.fromEntries(Object.keys(value).sort().map(key => [key, canonical(value[key])]))
  return value
}
export function selectionChanged(current, saved) { return JSON.stringify(canonical(current)) !== JSON.stringify(canonical(saved)) }

const explanations = {
  'sage.protocol.ag-ui': ['面向聊天前端，传输流式回复、工具状态和审批交互。', ['将 Sage 运行事件转换为 AG-UI 消息，供聊天前端展示。', '审批、暂停恢复等扩展交互取决于 enable_sage_extensions 配置。', '适配器负责事件转换，协议入口由服务端部署管理。']],
  'sage.protocol.a2a': ['面向其他智能体系统，传递任务状态、消息和产物。', ['将 Sage 运行事件转换为 A2A 的任务、消息和产物事件。', '等待用户输入或审批时映射为任务需要输入的状态。', 'A2A 不覆盖 Sage 的全部工具与推理细节。']],
  'sage.protocol.native': ['提供 Sage 原生事件，保留完整的运行信息。', ['直接输出 Sage 原生运行事件，不进行其他协议的格式转换。', '保留运行、工具、审批、工作流和产物等原生语义。', '适合需要读取完整 Sage 运行信息的集成。']],
  'sage.protocol.acp': ['面向 ACP 客户端，传递会话更新和权限请求。', ['将 Sage 事件转换为 ACP 会话更新、权限请求和输入请求。', '不提供 Sage 原生的精确游标回放与工作流语义。', '适配器的加载不代表已对外开放 ACP 服务。']],
  'sage.protocol.mcp': ['转换 MCP 进度通知和信息补充请求；适配器本身不启动 MCP 服务。', ['将关联的运行事件转换为 MCP 进度通知和信息补充请求。', '工具页的 MCP 连接负责接入外部工具服务，此处负责事件格式转换。', '此适配器不提供完整的会话消息流，也不会自行启动 MCP 服务。']],
  'sage.tool-selection.direct': ['将全部已授权工具交给模型选择。', ['主模型看到全部已授权工具，不受展示数量限制。', '工具越多，工具定义占用的上下文通常越多。', '不额外调用模型筛选工具。']],
  'sage.tool-selection.lexical': ['按任务与工具描述的文字相关性筛选。', ['使用 BM25 在本地匹配任务与工具描述。', '不额外调用筛选模型；描述用词会影响匹配结果。']],
  'sage.tool-selection.llm': ['由快速模型理解任务并筛选工具。', ['每个 Run 在准备阶段调用模型筛选工具。', '增加筛选模型请求，耗时和成本取决于所用模型。']],
  'sage.tool-selection.recent': ['优先展示近期使用的工具。', ['根据近期工具调用记录安排展示顺序。', '无需筛选模型；新任务需关注工具覆盖范围。']],
  'sage.context.reducer.persistent-summary': ['需要压缩时，将历史对话整理为持久摘要。', ['在 API 拒绝输入或使用量达到限制等条件下触发压缩。', '使用摘要器保留历史要点，同时保护近期对话。', '摘要作为后续上下文使用，原始会话历史仍保留。']],
  'sage.context.reducer.window': ['需要压缩时，裁剪完整的历史对话单元。', ['压缩时移除较早的对话，保留当前任务相关的近期内容。', '摘要器在此策略下不参与压缩，不产生摘要请求。', '较早内容不再进入本次模型上下文。']],
  'sage.context.summarizer.model': ['调用主模型生成对话摘要。', ['仅在需要生成摘要时调用模型，并非每轮都调用。', '使用 primary 模型槽位，增加摘要请求。', '选择窗口裁剪时，此摘要器不参与上下文压缩。']],
  'sage.context.summarizer.extractive': ['从对话和工具结果中提取任务状态。', ['不调用模型，通过规则保留有限的任务状态和工具结果。', '摘要的细节保留方式与模型摘要不同。', '选择窗口裁剪时，此摘要器不参与上下文压缩。']],
  'sage.skill.loading.lazy': ['需要时再加载技能正文。', ['按需加载技能材料，受活动内容字符上限约束。', '此处决定加载方式；技能授权范围仍由可用技能配置决定。']],
  'sage.memory.recall-query.direct': ['直接使用用户输入检索记忆。', ['不调用模型生成检索词。', '只有开启记忆检索时才会使用，不会自动开启记忆。']],
  'sage.memory.recall-query.llm': ['由快速模型生成记忆检索词。', ['使用 fast 模型槽位，从用户输入生成检索词。', '增加检索词生成请求；只有开启记忆检索时才会使用。']],
  'sage.agent.continuation.deterministic': ['根据工具调用和运行状态判断是否完成。', ['无待执行工具调用时，可按确定性规则结束本轮。', '完成判断不额外调用 Judge 模型，仍受预算等运行约束。']],
  'sage.agent.continuation.llm-judge': ['无待执行工具调用时，由模型判断任务是否完成。', ['通过 Judge 模型检查完成情况，必要时继续运行。', '增加判定模型请求，仍受运行预算等约束。']],
  'sage.agent.continuation.hybrid': ['结合运行规则和模型判断是否完成。', ['混合完成判定在当前运行时使用 LLM Judge 实现。', '模型判定可能产生额外请求，仍受运行预算约束。']],
  'sage.agent.continuation.explicit-status': ['通过 turn_status 工具显式标记结束。', ['模型需要给出明确的结束状态。', '不额外调用 Judge 模型；运行预算等约束仍然有效。']],
  'sage.memory.filesystem-bm25': ['使用文件和 BM25 检索长期记忆。', ['长期记忆保存在配置目录中，通过文字相关性检索。', '是否召回和自动写入仍由智能体记忆设置决定。']],
  'sage.memory.noop': ['关闭长期记忆提供器。', ['不提供长期记忆的检索和写入。', '切换提供器不会自动迁移或删除原记忆文件。']],
  'sage.session-memory.sqlite-bm25': ['使用 SQLite 和 BM25 管理会话记忆。', ['会话记忆持久化到配置目录下的 SQLite 存储。', '切换存储目录不会自动迁移已有会话记忆。']],
  'sage.session-memory.noop': ['关闭会话记忆提供器。', ['不通过会话记忆提供器检索历史材料。', '原始会话记录仍由会话存储管理。']],
  'sage.context.summary-store.session-derived': ['将摘要保存在会话派生状态中。', ['摘要随会话派生状态保存，供后续上下文压缩复用。', '持久性遵循宿主会话存储的保障。']],
  'sage.context.summary-store.ephemeral': ['将摘要临时保存在进程内。', ['摘要存储随进程生命周期存在。', '进程重启后不会保留此存储中的摘要。']],
  'sage.observability.noop': ['关闭观测采集。', ['不记录观测日志、模型诊断或调用链。']],
  'sage.observability.local': ['在本地记录运行日志和模型诊断。', ['日志输出与模型诊断独立配置。', '观测数据不参与会话恢复。']],
  'sage.observability.langfuse': ['使用 Langfuse 记录调用链。', ['由同一插件管理日志输出和链路导出。', '后端不支持的诊断查询会明确标记为不可用。']],
  'sage.observability.otlp': ['通过 OTLP 导出调用链。', ['独立设置日志级别、调用链采样和诊断内容模式。', '配置 Jaeger 查询地址后可查询诊断证据。']],
  'sage.observability.phoenix': ['使用 Phoenix 记录调用链和诊断证据。', ['统一管理日志、模型诊断及链路生命周期。', '原始内容采集与调用链内容模式分别设置。']],
  'sage.workspace.initializer.bare': ['初始化空白工作区。', ['不应用 Claw 工作区初始化模板。', '已有工作区文件仍由工作区初始化规则管理。']],
  'sage.workspace.initializer.claw': ['使用 Claw 模板初始化工作区。', ['按配置语言准备 Claw 工作区指导文件。', '不改变智能体已经配置的工具执行权限。']],
  'sage.package-registry.ephemeral': ['使用进程内 Agent 包管理。', ['包注册信息仅在当前进程中维护。', '进程重启后不会保留该注册表的内存内容。']],
  'sage.artifact.ephemeral': ['在进程内临时保存产物。', ['产物只保留在当前进程的内存中。', '进程重启后不会保留此存储中的产物。']],
  'sage.artifact.filesystem': ['在文件目录中保存产物。', ['使用配置的根目录保存产物文件。', '切换目录不会自动迁移原目录中的文件。']],
}

export function pluginExplanation(plugin, config = {}) {
  const id = typeof plugin === 'string' ? plugin : plugin?.id
  const entry = explanations[id]
  if (!entry) return { description: '由此插件提供该能力。', effects: [plugin?.description || '此插件未提供行为说明，请查看插件定义并验证配置。', '实际效果需通过配置验证和试运行确认。'] }
  const effects = [...entry[1]]
  if (['sage.tool-selection.lexical', 'sage.tool-selection.llm', 'sage.tool-selection.recent'].includes(id)) {
    effects.splice(1, 0, `最多向主模型展示 ${config.max_visible_tools ?? 24} 个完整工具定义，支持按需扩展。`)
  }
  return { description: entry[0], effects }
}
