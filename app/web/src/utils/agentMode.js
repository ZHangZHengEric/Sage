const LEGACY_AGENT_MODE_MAP = {
  multi: 'simple'
}

export const normalizeAgentMode = (mode, fallback = 'simple') => {
  if (!mode) return fallback
  return LEGACY_AGENT_MODE_MAP[mode] || mode
}
