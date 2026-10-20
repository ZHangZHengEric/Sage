// Names follow Desktop v2 settings_screen.dart and its Chinese localization.
export const componentNames = {
  'tool.result-processor': '工具结果处理',
  'derived-state.store': '运行状态存储', 'session.access': '会话访问控制', 'agent.approval-memory': '审批记忆',
  'agent.continuation-policy': 'Run 完成判定', 'tool.selection-policy': '工具选择策略',
  'memory.provider': '长期记忆', 'memory.recall-query': '记忆检索词生成', 'session-memory.provider': '会话记忆',
  'context.summarizer': '上下文摘要器', 'context.reducer': '上下文压缩', 'context.summary-store': '摘要存储',
  'context.token-estimator': 'Token 估算', 'context.unit-compactor': '工具结果压缩', 'skill.loading': 'Skill 加载',
  'observability.diagnostic-sink': '模型请求记录', 'observability.log-sink': '结构化日志', 'observability.trace-sink': '链路追踪',
  'execution.sandbox': '执行沙箱', 'execution.scheduler': '运行调度', 'execution.job-runtime': '后台任务',
  'session.store': '会话存储', 'workspace.initializer': '工作区初始化', 'model.provider': '模型接口',
  'artifact.store': '产物存储', 'credentials.provider': '凭据管理', 'package.registry': 'Agent 包管理',
  'interface.protocol-adapter': '协议适配器', 'skill.catalog': 'Skill 目录', 'skill.source': 'Skill 来源',
  'tool.catalog': '工具目录', 'tool.executor': '工具执行', 'flow.node': '工作流节点',
}
const names = {
  'sage.tool.result-processor.file': '超长结果保存到文件',
  'sage.agent.continuation.deterministic': '无工具调用即完成', 'sage.agent.continuation.llm-judge': '无工具调用 + LLM Judge',
  'sage.agent.continuation.hybrid': '混合完成判定', 'sage.agent.continuation.explicit-status': '结束工具（turn_status）',
  'sage.context.summarizer.model': '模型摘要', 'sage.context.summarizer.extractive': '抽取式摘要',
  'sage.context.reducer.persistent-summary': '持久摘要', 'sage.context.reducer.window': '窗口裁剪',
  'sage.context.summary-store.session-derived': 'Session 派生存储', 'sage.context.summary-store.ephemeral': '临时摘要存储',
  'sage.context.token-estimator.json-heuristic': 'JSON 启发式估算', 'sage.context.token-estimator.unicode-heuristic': 'Unicode 启发式估算', 'sage.context.token-estimator.tiktoken': 'Tiktoken 估算',
  'sage.context.unit-compactor.reference': '工具结果引用',
  'sage.memory.filesystem-bm25': '本地 BM25 记忆', 'sage.memory.noop': '关闭长期记忆',
  'sage.memory.recall-query.direct': '直接使用用户输入', 'sage.memory.recall-query.llm': 'LLM 生成检索词',
  'sage.tool-selection.direct': '直接展示全部工具', 'sage.tool-selection.lexical': 'BM25 相关性选择', 'sage.tool-selection.llm': '大模型工具选择', 'sage.tool-selection.recent': '最近使用优先',
  'sage.session-memory.sqlite-bm25': 'SQLite BM25 会话记忆', 'sage.session-memory.noop': '关闭会话记忆',
  'sage.observability.filesystem': '文件模型请求记录', 'sage.observability.noop': '关闭模型请求记录',
  'sage.logging.filesystem': '轮转文件日志', 'sage.logging.stdout': '控制台日志', 'sage.logging.noop': '关闭日志',
  'sage.trace.langfuse': 'Langfuse 追踪', 'sage.trace.phoenix': 'Phoenix 追踪', 'sage.trace.otlp': 'OpenTelemetry 追踪', 'sage.trace.noop': '关闭追踪',
  'sage.sandbox.local-workspace': '本地工作区沙箱', 'sage.sandbox.ephemeral': '临时内存沙箱', 'sage.sandbox.cube-volume': 'Cube Volume 沙箱',
  'sage.session.filesystem': '文件 Session 存储', 'sage.session.ephemeral': '临时 Session 存储', 'sage.session.mysql': 'MySQL 会话存储', 'sage.session.postgres': 'PostgreSQL 会话存储',
  'sage.workspace.initializer.bare': '空白工作区', 'sage.workspace.initializer.claw': 'Claw Mode',
  'sage.artifact.session': 'Session 产物存储',
  'sage.artifact.ephemeral': '临时产物存储', 'sage.artifact.filesystem': '文件产物存储',
  'sage.credentials.environment': '环境变量凭据', 'sage.credentials.mapping': '凭据映射',
  'sage.flow.agent': 'Agent 节点', 'sage.job.ephemeral': '进程内后台任务', 'sage.package-registry.ephemeral': '进程内 Agent 包管理',
  'sage.protocol.a2a': 'A2A', 'sage.protocol.acp': 'ACP', 'sage.protocol.ag-ui': 'AG-UI', 'sage.protocol.mcp': 'MCP', 'sage.protocol.native': 'Native',
  'sage.scheduler.ephemeral': '进程内运行调度', 'sage.scheduler.filesystem': '文件运行调度',
  'sage.skill.filesystem': '文件 Skill 目录', 'sage.skill.loading.lazy': '按需加载 Skill',
  'sage.tool.ephemeral': '进程内工具', 'sage.tool.mcp': 'MCP 工具', 'sage.tool.multi-agent': '多 Agent 工具', 'sage.tool.official': '内置工具', 'sage.tool.skill': 'Skill 工具',
}
export function pluginName(plugin) { return names[typeof plugin === 'string' ? plugin : plugin?.id] || plugin?.name || plugin || '未选择' }
export function componentName(id) { return componentNames[id] || id }
export const scopeNames = { process: '进程', tenant: '用户', agent: 'Agent', run: 'Run' }
const priority = ['agent.continuation-policy', 'tool.selection-policy', 'memory.provider', 'memory.recall-query', 'session-memory.provider', 'context.summarizer', 'context.reducer', 'context.token-estimator', 'context.summary-store', 'context.unit-compactor']
export function componentGroups(catalog, providers = []) {
  const grouped = new Map()
  for (const plugin of catalog?.plugins || []) for (const capability of plugin.capabilities) {
    if (!grouped.has(capability)) grouped.set(capability, [])
    grouped.get(capability).push(plugin)
  }
  for (const capability of [...Object.keys(catalog?.defaults || {}), ...providers.map(item => item.capability)]) if (!grouped.has(capability)) grouped.set(capability, [])
  return [...grouped].map(([id, plugins]) => ({ id, name: componentName(id), plugins })).sort((a, b) => {
    const rank = id => priority.includes(id) ? priority.indexOf(id) : 100
    return rank(a.id) - rank(b.id) || a.name.localeCompare(b.name, 'zh-CN')
  })
}
export function parameterDefaults(plugin) { return Object.fromEntries(Object.entries(plugin?.schema?.properties || {}).filter(([, field]) => field.default !== undefined).map(([key, field]) => [key, field.default])) }
export function displayValue(value) { return value === undefined || value === null ? '未设置' : typeof value === 'boolean' ? value ? '开启' : '关闭' : typeof value === 'object' ? JSON.stringify(value) : String(value) }
