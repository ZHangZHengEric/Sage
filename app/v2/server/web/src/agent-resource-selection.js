import { toolPresentation } from './resource-presentation.js'

const sourceLabels = { official: '官方工具', host: '智能体管理', mcp: 'MCP 工具', a2a: '远端智能体', external: '外部工具', skills: '技能' }
export function resourceId(scope, name) { return `${scope}:${name}` }
export function resourceNames(ids, scope) {
  const prefix = `${scope}:`
  return [...new Set(ids.filter(id => id.startsWith(prefix)).map(id => id.slice(prefix.length)))]
}

export function agentToolChoices(tools, externalNames, externalGroups, selectedTools = [], selectedExternal = []) {
  const items = new Map()
  for (const tool of tools) {
    const presentation = toolPresentation(tool), source = tool.source || 'official'
    const item = { id: resourceId('tools', tool.name), scope: 'tools', name: tool.name, title: presentation.title,
      description: presentation.description, source, sourceLabel: sourceLabels[source] || source,
      category: presentation.category, available: true }
    items.set(item.id, item)
  }
  const connections = new Map()
  for (const group of externalGroups) for (const name of group.tools) {
    const existing = connections.get(name) || []
    existing.push({ id: JSON.stringify([group.source, group.name]), name: group.name, source: group.source })
    connections.set(name, existing)
  }
  for (const name of externalNames) {
    const groups = connections.get(name) || [], source = groups[0]?.source || 'external'
    const item = { id: resourceId('external_tools', name), scope: 'external_tools', name, title: name, description: '',
      source, sourceLabel: sourceLabels[source], connections: groups, available: true }
    items.set(item.id, item)
  }
  for (const [scope, names] of [['tools', selectedTools], ['external_tools', selectedExternal]]) for (const name of names) {
    const id = resourceId(scope, name)
    if (!items.has(id)) items.set(id, { id, scope, name, title: name, description: '', source: scope === 'tools' ? 'official' : 'external',
      sourceLabel: scope === 'tools' ? '内置工具' : '外部工具', available: false })
  }
  return [...items.values()]
}

export function agentSkillChoices(skills, selected = []) {
  const items = new Map(skills.map(skill => [skill.name, { id: resourceId('skills', skill.name), scope: 'skills', name: skill.name,
    title: skill.name, description: skill.description || '', source: 'skills', sourceLabel: '技能', available: true }]))
  for (const name of selected) if (!items.has(name)) items.set(name, { id: resourceId('skills', name), scope: 'skills', name, title: name,
    description: '', source: 'skills', sourceLabel: '技能', available: false })
  return [...items.values()]
}

export function agentMemberChoices(agents, selected = []) {
  const items = new Map(agents.map(agent => [agent.id, { id: agent.id, name: agent.id,
    title: agent.name, description: agent.description || '', source: 'agents', sourceLabel: '智能体', available: true }]))
  for (const id of selected) if (!items.has(id)) items.set(id, { id, name: id, title: id,
    description: '', source: 'agents', sourceLabel: '智能体', available: false })
  return [...items.values()]
}

export function filterResourceChoices(items, selected, { query = '', source = '', connection = '', category = '', state = 'all' } = {}) {
  const search = query.trim().toLocaleLowerCase()
  return items.filter(item => (!source || item.source === source) && (!connection || item.connections?.some(group => group.id === connection)) &&
    (!category || item.category === category) && (state === 'all' || state === 'selected' && selected.has(item.id) ||
      state === 'unselected' && !selected.has(item.id) || state === 'unavailable' && !item.available) &&
    (!search || [item.name, item.title, item.description, item.sourceLabel, item.category, ...(item.connections || []).map(group => group.name)].join(' ').toLocaleLowerCase().includes(search)))
}

// A bulk action always addresses a concrete snapshot, including matches on other pages.
export function selectResourceResults(selected, results, checked) {
  const next = new Set(selected)
  for (const item of results) {
    if (!checked) next.delete(item.id)
    else if (item.available) next.add(item.id)
  }
  return next
}
