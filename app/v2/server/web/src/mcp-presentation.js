export function mcpServerKey(server, currentUserId = '') {
  return JSON.stringify([server._owner?.user_id || currentUserId, server.name])
}
function approvalServer(key) {
  if (!key?.startsWith('mcp:')) return ''
  try { return decodeURIComponent(key.split(':')[1]) } catch { return '' }
}

// Saved discovery names keep disabled/offline services visible; live definitions
// provide descriptions and schemas. Both are joined within the same owner.
export function mcpToolInventory(servers, catalogs, currentUserId = '') {
  const rows = [], matched = new Set()
  for (const server of servers) {
    const ownerId = server._owner?.user_id || currentUserId
    const definitions = catalogs.filter(catalog => (catalog.owner?.user_id || currentUserId) === ownerId)
      .flatMap(catalog => catalog.tools).filter(tool => tool.source === 'mcp')
    const savedNames = new Set(server.tools || [])
    const live = definitions.filter(tool => {
      const source = approvalServer(tool.approval_key)
      return source ? source === server.name : savedNames.has(tool.name)
    })
    const byName = new Map(live.map(tool => [tool.name, tool]))
    for (const name of new Set([...savedNames, ...byName.keys()])) {
      const definition = byName.get(name)
      if (definition) matched.add(JSON.stringify([ownerId, name]))
      rows.push({ key: JSON.stringify([ownerId, server.name, name]), serverKey: mcpServerKey(server, currentUserId),
        server, serverName: server.name, owner: server._owner,
        tool: definition || { name, source: 'mcp', category: 'MCP' },
        hasDefinition: Boolean(definition), state: server.disabled ? 'disabled' : definition ? 'available' : 'unknown' })
    }
  }
  for (const catalog of catalogs) {
    const ownerId = catalog.owner?.user_id || currentUserId
    for (const tool of catalog.tools.filter(tool => tool.source === 'mcp')) {
      if (matched.has(JSON.stringify([ownerId, tool.name]))) continue
      rows.push({ key: JSON.stringify([ownerId, null, tool.name]), serverKey: 'unmatched', server: null,
        serverName: approvalServer(tool.approval_key) || '未匹配服务', owner: catalog.owner,
        tool, hasDefinition: true, state: 'unknown' })
    }
  }
  return rows
}
