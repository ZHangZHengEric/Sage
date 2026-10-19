import { toolPresentation } from './resource-presentation.js'

const sources = { official: '官方工具', host: '智能体管理', mcp: 'MCP 工具', a2a: '远端智能体' }
export function approvalRuleItems(tools, rules = {}) {
  const items = new Map()
  for (const tool of tools) {
    const key = tool.approval_key || tool.name, presentation = toolPresentation(tool), source = tool.source || 'official'
    if (!items.has(key)) items.set(key, { key, name: tool.name, title: presentation.title,
      description: presentation.description, source, sourceLabel: sources[source] || source, available: true })
  }
  for (const key of Object.keys(rules)) if (!items.has(key)) items.set(key, {
    key, name: key, title: key, description: '', source: 'unavailable', sourceLabel: '暂不可用', available: false,
  })
  return [...items.values()]
}
export function approvalOverrideCount(rules = {}) {
  return Object.values(rules).filter(value => value === 'ask' || value === 'auto_approve').length
}
export function changeApprovalRule(rules, key, value) {
  const next = { ...rules }
  if (value === 'inherit') delete next[key]
  else if (value === 'ask' || value === 'auto_approve') next[key] = value
  return next
}
export function approvalChanges(before, after) {
  return [...new Set([...Object.keys(before), ...Object.keys(after)])]
    .filter(key => (before[key] || 'inherit') !== (after[key] || 'inherit')).length
}
