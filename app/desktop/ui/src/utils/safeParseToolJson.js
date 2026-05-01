/**
 * 容错解析工具返回的 JSON 字符串（如 todo_write 结果）：
 * BOM/trim、双层 JSON 字符串、字符串值内未转义换行（传输层偶发破坏）后再 parse。
 */

function stripBom (s) {
  return String(s).replace(/^\uFEFF/, '').trim()
}

/**
 * JSON 源码中若字符串值内出现字面换行（非法），转义为 \\n 再供 JSON.parse。
 */
export function escapeIllegalNewlinesInJsonStrings (jsonStr) {
  let out = ''
  let i = 0
  let inString = false
  let escaped = false
  while (i < jsonStr.length) {
    const c = jsonStr[i]
    if (escaped) {
      out += c
      escaped = false
      i++
      continue
    }
    if (inString) {
      if (c === '\\') {
        out += c
        escaped = true
        i++
        continue
      }
      if (c === '"') {
        inString = false
        out += c
        i++
        continue
      }
      if (c === '\n' || c === '\r') {
        if (c === '\r' && jsonStr[i + 1] === '\n') i++
        out += '\\n'
        i++
        continue
      }
      out += c
      i++
      continue
    }
    if (c === '"') inString = true
    out += c
    i++
  }
  return out
}

/**
 * @param {unknown} content toolResult.content 或整段 tool 消息
 * @returns {unknown|null} 解析成功返回值；无法解析返回 null
 */
export function parseToolJsonValue (content) {
  if (content == null || content === '') return null
  if (typeof content === 'object') return content

  if (typeof content !== 'string') return null

  const s0 = stripBom(content)
  const tryParse = (str) => {
    try {
      return JSON.parse(str)
    } catch {
      return undefined
    }
  }

  let v = tryParse(s0)
  if (v !== undefined) {
    if (typeof v === 'string') {
      const innerText = stripBom(v)
      if (
        (innerText.startsWith('{') && innerText.endsWith('}')) ||
        (innerText.startsWith('[') && innerText.endsWith(']'))
      ) {
        const inner = tryParse(innerText)
        if (inner !== undefined) return inner
      }
    }
    return v
  }

  try {
    const outer = JSON.parse(s0)
    if (typeof outer === 'string') {
      const inner = tryParse(stripBom(outer))
      if (inner !== undefined) return inner
    }
  } catch (_) { /* ignore */ }

  const repaired = escapeIllegalNewlinesInJsonStrings(s0)
  if (repaired !== s0) {
    v = tryParse(repaired)
    if (v !== undefined) {
      if (typeof v === 'string') {
        const innerText = stripBom(v)
        if (
          (innerText.startsWith('{') && innerText.endsWith('}')) ||
          (innerText.startsWith('[') && innerText.endsWith(']'))
        ) {
          const inner = tryParse(innerText)
          if (inner !== undefined) return inner
        }
      }
      return v
    }
  }

  return null
}

/**
 * todo 等需要「对象」语义时的安全解析；非对象返回空对象。
 */
export function parseToolJsonObjectRecord (content) {
  const v = parseToolJsonValue(content)
  if (v != null && typeof v === 'object' && !Array.isArray(v)) return v
  return {}
}

/** 用于原始数据弹窗右侧等：尽量格式化为缩进 JSON */
export function stringifyToolContentPretty (content) {
  const v = parseToolJsonValue(content)
  if (v !== null && typeof v === 'object') {
    try {
      return JSON.stringify(v, null, 2)
    } catch {
      return String(content)
    }
  }
  if (typeof content === 'string') return content
  if (content == null) return ''
  try {
    return JSON.stringify(content, null, 2)
  } catch {
    return String(content)
  }
}
