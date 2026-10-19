export const resourceHelp = {
  name: '用于识别这个连接，创建后不能在此修改。请使用容易区分的名称，便于后续找到对应的服务与工具。',
  description: '用于说明这个连接的用途，帮助你区分服务。修改描述不会改变远端服务本身提供的能力。',
  disabled: '保留连接配置，并使其远端能力不再出现在本租户的可用工具中。恢复启用后可重新使用。',
  timeout: '连接和初始化时允许等待的秒数。过短可能让较慢的服务连接失败，较长会增加错误时的等待。留空使用服务默认值。',
  callTimeout: '单次调用远端工具允许等待的秒数。过短可能中断较长任务，较长会增加等待。留空使用服务默认行为。',
  defaults: '这是新建智能体时的初始工具集，不代表每个智能体当前都能调用。实际可用范围由该智能体选择的工具与执行策略决定。',
  authorization: '在智能体编辑页选择允许使用的工具。此目录只展示可发现的工具，不修改授权，也不会直接运行工具。',
  parameters: '这些是工具在每次调用时接收的输入，不是全局配置。名称、必填项、类型和默认值来自工具定义；实际输入由调用方提供。',
  files: '技能包中的说明、脚本和参考材料。文件浏览只读取内容，不在此执行脚本，也不会自动授权工具。',
  revision: '当前技能内容的修订编号。重新导入或更新后可能产生新修订；当前页面展示已保存的内容。',
  bind: '导入技能后，它会进入当前可用目录。是否提供给某个智能体，需要在该智能体的技能配置中选择。',
  readonly: '这是其他用户的技能。可以阅读当前可见的说明和文件，当前页面禁止修改或删除。',
  protocol: '请与 MCP 服务提供的连接方式保持一致。协议不匹配可能导致连接或工具发现失败；修改后需要刷新工具。',
  url: 'MCP 填工具服务端点。远端智能体填其 base URL，具体调用端点由对方 Agent Card 指定。地址不正确会导致连接失败。',
  key: '用于向这个远端服务认证。已保存的密钥不回显；编辑时留空会保留原密钥，新增时可按服务的认证要求填写。',
}
export const toolCategories = { files: ['文件', 'file', 'olive'], code_search: ['代码检索', 'search', 'olive'], shell: ['命令行', 'code', 'slate'], planning: ['规划', 'check', 'gold'], memory: ['记忆', 'history', 'clay'], web: ['网页', 'link', 'blue'], image: ['图像', 'file', 'clay'], code_quality: ['代码检查', 'shield', 'slate'], interaction: ['交互', 'chat', 'blue'], MCP: ['MCP', 'link', 'blue'], 'agent-management': ['智能体管理', 'agent', 'olive'] }
const names = { file_read: ['读取文件', '按行读取工作区文本，查看文档、代码和配置。'], file_write: ['写入文件', '将文本保存到工作区文件，可覆盖或追加内容。'], file_update: ['修改文件', '按照指定内容修改工作区文件。'], apply_patch: ['应用文件补丁', '将结构化补丁应用到工作区文件。'], list_dir: ['浏览文件夹', '查看工作区目录结构，找到需要的文件。'], glob: ['查找文件', '通过路径模式查找工作区文件。'], grep: ['搜索文件内容', '按关键词或正则表达式定位文件内容。'], execute_shell_command: ['执行命令', '在运行环境中执行命令，完成构建、检查等任务。'], await_shell: ['等待命令完成', '获取后台命令的执行进展与结果。'], kill_shell: ['停止命令', '停止指定的后台命令。'], todo_read: ['读取任务清单', '查看当前任务的计划与进展。'], todo_write: ['更新任务清单', '维护当前任务的计划与完成状态。'], fetch_webpages: ['读取网页', '获取指定网页的正文或远端文件。'] }
export function toolPresentation(item) {
  const [category, icon, tone] = toolCategories[item.category] || [item.category || '其他', 'tools', 'olive']
  const display = item.source === 'official' ? names[item.name] : undefined
  return { title: display?.[0] || item.name, description: display?.[1] || item.description || '', category, icon, tone }
}
export function formatBytes(value) {
  if (value === undefined || value === null) return '—'
  if (value < 1024) return `${value} B`
  return `${(value / (value < 1024 * 1024 ? 1024 : 1024 * 1024)).toFixed(1)} ${value < 1024 * 1024 ? 'KB' : 'MB'}`
}
function reference(schema, root, seen = new Set()) {
  if (!schema?.$ref || !schema.$ref.startsWith('#/') || seen.has(schema.$ref)) return schema || {}
  const next = new Set(seen).add(schema.$ref)
  const resolved = schema.$ref.slice(2).split('/').reduce((value, key) => value?.[key.replace(/~1/g, '/').replace(/~0/g, '~')], root)
  return { ...reference(resolved, root, next), ...Object.fromEntries(Object.entries(schema).filter(([key]) => key !== '$ref')) }
}
export function schemaType(schema, root = {}, depth = 0) {
  if (depth > 8) return 'object'
  schema = reference(schema, root)
  if (schema.anyOf || schema.oneOf) return [...new Set((schema.anyOf || schema.oneOf).map(item => schemaType(item, root, depth + 1)))].join(' | ')
  if (Array.isArray(schema.type)) return schema.type.join(' | ')
  if (schema.type === 'array') return `${schemaType(schema.items || {}, root, depth + 1)}[]`
  return schema.type || (schema.properties ? 'object' : '未指定')
}
const parameterLabels = { file_path: '文件路径', path: '路径', start_line: '起始行', end_line: '结束行', include_line_numbers: '显示行号', content: '文本内容', mode: '写入方式', command: '命令', workdir: '工作目录', block_until_ms: '同步等待时间（毫秒）', env_vars: '环境变量', urls: '网页地址', timeout: '请求超时（秒）', retries: '重试次数', max_length_per_url: '每页内容长度', depth: '目录层数', max_items_per_dir: '每目录条目上限', include_hidden: '包含隐藏文件', pattern: '搜索表达式', glob: '文件模式', output_mode: '输出方式', case_insensitive: '忽略大小写', head_limit: '结果上限' }
const parameterNotes = { file_path: '目标文件路径，受当前工作区访问范围约束。', start_line: '从这一行开始，行号从 1 开始。', end_line: '读取到这一行，包含结束行；null 表示直到文件结尾。', include_line_numbers: '在结果中附带行号，便于定位与修改。', block_until_ms: '同步等待命令结果的最长毫秒数。', env_vars: '包含字符串键值对的 JSON 对象文本。', max_length_per_url: '限制每个网页返回的文本长度。', include_hidden: '是否包含以点开头的隐藏路径。', max_items_per_dir: '每个目录返回的文件与子目录数量上限。' }
export function toolParameters(item) {
  const root = item.input_schema || {}, definition = reference(root, root)
  return Object.entries(definition.properties || {}).map(([name, original]) => {
    const schema = reference(original, root)
    return { name, label: item.source === 'official' ? parameterLabels[name] || name : schema.title || name,
      description: schema.description || (item.source === 'official' ? parameterNotes[name] : '') || '',
      type: schemaType(schema, root), required: definition.required?.includes(name) || false,
      hasDefault: Object.hasOwn(schema, 'default'), default: schema.default, enum: schema.enum, schema }
  })
}
export function markdownBody(source) { return source.replace(/^\uFEFF/, '').replace(/^---\r?\n[\s\S]*?\r?\n(?:---|\.\.\.)[ \t]*(?:\r?\n|$)/, '') }
