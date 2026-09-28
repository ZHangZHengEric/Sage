/**
 * 从不完整或不合法的 JSON 参数字符串里尝试取出某几个「字符串字段」的值（便于流式时预览命令等）。
 */

function unescapeJsonStringFragment (fragment) {
  if (!fragment) return ''
  return fragment.replace(/\\(.)/gu, (_, ch) => {
    switch (ch) {
      case 'n': return '\n'
      case 'r': return '\r'
      case 't': return '\t'
      case '"': return '"'
      case '\\': return '\\'
      default: return `\\${ch}`
    }
  })
}

/**
 * @param {string} raw arguments 拼接中的原始片段
 * @param {string[]} fieldNames 如 ['command','cmd']
 */
export function extractIncompleteJsonStringField (raw, fieldNames) {
  if (!raw || typeof raw !== 'string') return ''
  for (const key of fieldNames) {
    const escapedKey = JSON.stringify(key).slice(1, -1)
    const re = new RegExp(
      `"${escapedKey}"\\s*:\\s*"((?:[^"\\\\]|\\\\.)*)`,
      'u'
    )
    const m = raw.match(re)
    if (m?.[1] != null) return unescapeJsonStringFragment(m[1])
  }
  return ''
}
