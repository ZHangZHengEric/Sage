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
  { key: 'max_steps', label: '最大运行步数', unit: '步', min: 1, max: 10000, help: '限制一次运行可执行的步骤。较低可能让复杂任务提前结束；留空沿用默认预算。' },
  { key: 'wall_time_seconds', label: '运行时间上限', unit: '秒', min: 1, step: 'any', help: '限制一次运行的时间预算。较短可能让长任务提前停止；留空沿用默认预算。' },
  { key: 'output_tokens', label: '输出 Token 预算', unit: 'Token', min: 1, help: '约束运行中的输出预算。较小可能限制回答与工具规划的长度；留空沿用默认预算。' },
  { key: 'input_tokens', label: '输入 Token 预算', unit: 'Token', min: 1, help: '约束进入模型的输入预算，影响可携带的历史与工具内容。留空沿用默认预算。' },
  { key: 'system_tokens', label: '系统 Token 预算', unit: 'Token', min: 1, help: '约束系统内容的 Token 预算，需为系统提示词和工具定义留出空间。留空沿用默认预算。' },
  { key: 'protected_recent_tokens', label: '保留近期 Token', unit: 'Token', min: 0, help: '为近期内容保留的 Token 预算。设置较大值通常可保护更多近期内容；留空沿用默认预算。' },
  { key: 'total_tokens', label: '总 Token 预算', unit: 'Token', min: 1, help: '约束运行中输入与输出的总 Token 预算。留空沿用默认预算。' },
]
export const agentHelp = {
  name: '智能体在列表和对话中的显示名称，用于区分用途，不会替代系统提示词。',
  description: '概括这个智能体的用途，便于浏览和搜索。具体行为由系统提示词与配置共同决定。',
  instructions: '定义角色、回答方式和行为要求。更长的提示词会占用更多输入上下文；保存后的变更用于后续运行。',
  recall: '允许在运行时检索已保存的相关记忆。实际结果受可用数据、记忆后端和作用域限制。',
  auto_write: '允许按既有记忆策略自动写入信息。关闭会停止自动写入新的记忆，不会删除已有记忆。',
  scope: '决定记忆的隔离范围。当前智能体、当前会话和当前用户使用不同作用域，影响后续的检索与写入。',
  external: '仅允许所选工具。取消所有勾选会禁用外部工具，后续新增工具需要单独授权。',
  approval: '决定工具调用默认是否需要询问。单个工具的审批规则可以覆盖默认；命令权限和沙箱限制仍然生效。',
  shell: '规定命令执行的权限上限。用户设置和审批策略仍会进一步限制执行；允许工作区内自动执行不代表所有命令均可直接运行。',
  network: '决定沙箱任务是否能访问网络。允许联网会扩大可访问范围，不会授予额外工具或账号权限。',
}
