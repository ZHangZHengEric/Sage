export const sanitizeSessionTitle = (value = '') => {
  let text = String(value ?? '')

  text = text.replace(
    /^\s*(?:<enable_plan>\s*(?:true|false)\s*<\/enable_plan>\s*|<enable_deep_thinking>\s*(?:true|false)\s*<\/enable_deep_thinking>\s*)+/i,
    ''
  )
  text = text.replace(/^\s*(?:<skill>[\s\S]*?<\/skill>\s*)+/i, '')
  text = text.replace(/<(?:skills|active_skills|available_skills)>[\s\S]*?<\/(?:skills|active_skills|available_skills)>/gi, ' ')
  text = text.replace(/<\/?[\w:-]+(?:\s[^>]*)?>/g, ' ')
  text = text.replace(/\s+/g, ' ').trim()

  const meaningfulText = text.replace(/[.\u2026。\-_=,:;!?'"`~()[\]{}<>/\\|]+/g, '').trim()
  if (!meaningfulText) return ''

  return text
}
