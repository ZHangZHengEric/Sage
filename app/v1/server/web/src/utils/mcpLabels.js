const normalizeServerName = (name = '') => {
  return String(name)
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '_')
    .replace(/^_+|_+$/g, '')
}

export const getMcpServerLabel = (serverName, t = null) => {
  if (!serverName) return serverName
  if (!t) return serverName

  const normalized = normalizeServerName(serverName)
  if (!normalized) return serverName

  const key = `mcp.server.${normalized}`
  const translated = t(key)
  return translated !== key ? translated : serverName
}

