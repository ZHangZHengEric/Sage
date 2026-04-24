export const normalizeAgentMode = (mode, fallback = 'simple') => {
  const normalized = String(mode || '').trim().toLowerCase()
  if (!normalized) return fallback
  if (normalized === 'fibre') return 'fibre'
  if (normalized === 'simple') return 'simple'
  return fallback
}
