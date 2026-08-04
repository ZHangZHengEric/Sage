export const THINKING_LEVEL_OPTIONS = ['minimal', 'low', 'medium', 'high', 'max']

export const getThinkingLevelOptions = (model) => (
  String(model || '').trim() ? [...THINKING_LEVEL_OPTIONS] : []
)

export const getDefaultThinkingLevel = (model) => (
  String(model || '').trim() ? 'medium' : null
)
