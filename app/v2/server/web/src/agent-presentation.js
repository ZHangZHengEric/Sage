import { modelOutputBudget } from './model-presentation.js'

export const agentSections = [
  { id: 'basic', label: '基本信息', icon: 'user' },
  { id: 'plugins', label: '能力编排', icon: 'grid' },
  { id: 'memory', label: '记忆', icon: 'history' },
  { id: 'budgets', label: '运行预算', icon: 'clock' },
  { id: 'tools', label: '可用工具', icon: 'tools' },
  { id: 'skills', label: '可用技能', icon: 'skill' },
  { id: 'approval', label: '工具审批', icon: 'shield' },
  { id: 'execution', label: '执行权限', icon: 'code' },
]
const sectionKeys = {
  basic: ['name', 'description', 'instructions'], plugins: ['plugins', 'model_id', 'fast_model_id'],
  memory: ['memory'], budgets: ['budgets'], tools: ['tools', 'external_tools'],
  approval: ['tool_approval'], execution: ['execution_policy', 'sandbox'],
}
function canonical(value) {
  if (Array.isArray(value)) return value.map(canonical)
  if (value && typeof value === 'object') return Object.fromEntries(Object.keys(value).sort().map(key => [key, canonical(value[key])]))
  return value
}
export function sameConfiguration(a, b) { return JSON.stringify(canonical(a)) === JSON.stringify(canonical(b)) }
export function cloneConfiguration(value) { return JSON.parse(JSON.stringify(value)) }
export function sectionChanges(form, saved, skills, savedSkills) {
  return { ...Object.fromEntries(Object.entries(sectionKeys).map(([section, keys]) => [section, keys.some(key => !sameConfiguration(form?.[key], saved?.[key]))])),
    skills: !sameConfiguration([...(skills || [])].sort(), [...(savedSkills || [])].sort()) }
}
export const budgetFields = [
  { key: 'max_steps', label: '最大运行步数', unit: '步', min: 1, max: 10000, help: '限制每阶段可执行的步骤。留空继承入口和全局预算；均未设置时，普通智能体默认 24 步，工作流默认 100 次节点访问。开启自动续阶段后可能继续下一阶段，整次运行仍受时间和总 Token 预算限制。' },
  { key: 'wall_time_seconds', label: '运行时间上限', unit: '秒', min: 1, step: 'any', help: '限制整次运行的时间。留空继承全局时间预算；全局也未设置时，不额外设置整次运行的时限。模型请求和工具各自的超时限制仍然有效。' },
  { key: 'output_tokens', label: '输出 Token 预算', unit: 'Token', min: 1, help: '限制每次模型请求的输出预算，不是整次运行的累计输出。留空继承全局输出预算；未配置时，跟随所选模型的单次输出预算、协议默认值和有效探测结果。仍受模型的实际输出限制。' },
  { key: 'input_tokens', label: '输入 Token 预算', unit: 'Token', min: 1, help: '影响可携带的历史与工具内容。留空继承全局输入预算，再与模型上下文窗口取较小值；两者均未配置时默认 32,768 Token。上下文管理还会预留输出空间。' },
  { key: 'system_tokens', label: '系统 Token 预算', unit: 'Token', min: 1, help: '留空继承全局配置；未配置时默认值为 16,384 Token。此项为保留配置，当前不会按此数值独立截断系统提示词或工具定义。' },
  { key: 'protected_recent_tokens', label: '保留近期 Token', unit: 'Token', min: 0, help: '留空继承全局配置；未配置时默认值为 8,192 Token，0 表示显式配置为零。此项为保留配置，当前以完整的近期对话单元进行保护，不按该数值逐 Token 裁剪。' },
  { key: 'total_tokens', label: '总 Token 预算', unit: 'Token', min: 1, help: '限制整次运行累计消耗的输入与输出 Token 总量。留空继承全局总量预算；全局也未设置时，不额外设置总 Token 上限。模型容量、单次输出预算等限制仍然有效。' },
]

// Context defaults: AgentCompositionFactory.create_context; stage defaults:
// AgentLoopEngine and the flow driver. Inherited data is presentation-only.
export function agentBudgetPlaceholder(key, form = {}, models = [], defaults = {}) {
  const model = models.find(item => item.id === form.model_id) || (!form.model_id && models.find(item => item.is_default)) || {}
  const global = defaults.budgets || {}
  const minimum = (...values) => { const numbers = values.filter(Number.isFinite); return numbers.length ? Math.min(...numbers) : null }
  const values = {
    max_steps: minimum(defaults.entrypoint?.config?.max_steps, global.max_steps) ?? (defaults.entrypoint?.type === 'flow' ? 100 : 24),
    wall_time_seconds: global.wall_time_seconds ?? '不设时限',
    output_tokens: global.output_tokens ?? modelOutputBudget(model, model.request?.max_output_tokens) ?? '跟随模型',
    input_tokens: minimum(global.input_tokens, model.limits?.context_window) ?? 32768,
    system_tokens: global.system_tokens ?? 16384,
    protected_recent_tokens: global.protected_recent_tokens ?? 8192,
    total_tokens: global.total_tokens ?? '不设总量上限',
  }
  const value = values[key]
  return `${typeof value === 'number' ? value.toLocaleString('en-US') : value}（系统默认）`
}
export const agentHelp = {
  name: '智能体在列表和对话中的显示名称，用于区分用途，不会替代系统提示词。',
  description: '概括这个智能体的用途，便于浏览和搜索。具体行为由系统提示词与配置共同决定。',
  instructions: '定义角色、回答方式和行为要求。更长的提示词会占用更多输入上下文；保存后的变更用于后续运行。',
  recall: '新建智能体默认：开启。允许在运行时检索已保存的相关记忆。实际结果受可用数据、记忆后端和作用域限制。',
  auto_write: '新建智能体默认：开启。允许按既有记忆策略自动写入信息。关闭会停止自动写入新的记忆，不会删除已有记忆。',
  scope: '系统默认：当前智能体。当前智能体、当前会话和当前用户使用不同作用域，影响记忆的隔离、检索与写入。',
  external: '系统默认：不授权外部工具。仅允许所选工具；取消所有勾选会禁用外部工具，后续新增工具需要单独授权。',
  approval: '新建智能体默认：免审批；逐工具规则默认继承。单个工具的规则可以覆盖默认审批模式，命令权限和沙箱限制仍然生效。旧配置未设置此项时沿用既有策略。',
  shell: '新建智能体默认：允许用户设置工作区内自动执行。此处规定权限上限，用户设置和审批策略仍会进一步限制执行，不代表所有命令均可直接运行。',
  network: '系统默认：禁止联网。允许联网会扩大沙箱任务可访问的范围，不会授予额外工具或账号权限。',
  model: '系统默认：使用当前用户的默认模型。未指定主模型时，后续运行跟随模型供应商页面设置的默认模型。',
  fast_model: '系统默认：跟随主模型。可单独选择用于辅助任务的模型；实际使用场景由能力编排配置决定。',
}
