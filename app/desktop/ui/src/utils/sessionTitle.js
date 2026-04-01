export const sanitizeSessionTitle = (value = '') => {
  let text = String(value ?? '')

  // 1) Remove leading plan/deep-thinking control tags.
  text = text.replace(
    /^\s*(?:<enable_plan>\s*(?:true|false)\s*<\/enable_plan>\s*|<enable_deep_thinking>\s*(?:true|false)\s*<\/enable_deep_thinking>\s*)+/i,
    ''
  )

  // 2) Remove leading skill selector tag while keeping actual user text.
  text = text.replace(/^\s*<skill>.*?<\/skill>\s*/is, '')

  // 3) Remove skill metadata blocks.
  text = text.replace(/<(?:skills|active_skills|available_skills)>[\s\S]*?<\/(?:skills|active_skills|available_skills)>/gi, ' ')

  // Normalize whitespace.
  text = text.replace(/\s+/g, ' ').trim()

  // If title becomes only punctuation/ellipsis, treat it as empty.
  // This allows UI fallback text instead of showing "..."
  const meaningfulText = text.replace(/[.\u2026。\-_=,:;!?'"`~()[\]{}<>/\\|]+/g, '').trim()
  if (!meaningfulText) {
    return ''
  }

  return text
}
