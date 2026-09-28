/**
 * 解析 todo_write 的 function.arguments（字符串或对象）。
 * 流式增量下参数常为未闭合 JSON，JSON.parse 会失败；在 "tasks":[ 之后按顺序提取 "id" 字段供折叠 UI 使用。
 */
export function parseTodoWriteToolCallArguments (raw) {
  const empty = { tasks: [], taskIdsOrdered: [] }
  if (raw == null) return empty

  if (typeof raw === 'object' && !Array.isArray(raw)) {
    const tasks = Array.isArray(raw.tasks) ? raw.tasks : []
    return { tasks, taskIdsOrdered: orderedIdsFromTaskObjects(tasks) }
  }

  if (typeof raw !== 'string') return empty

  const s = raw.trim()
  if (!s) return empty

  try {
    const o = JSON.parse(s)
    if (o && typeof o === 'object' && Array.isArray(o.tasks)) {
      return { tasks: o.tasks, taskIdsOrdered: orderedIdsFromTaskObjects(o.tasks) }
    }
  } catch (_) {
    /* 流式未完成 */
  }

  const tasksRegionStart = s.search(/"tasks"\s*:\s*\[/i)
  const scan = tasksRegionStart >= 0 ? s.slice(tasksRegionStart) : s
  return { tasks: [], taskIdsOrdered: extractIdsFromJsonLikeFragment(scan) }
}

function orderedIdsFromTaskObjects (tasks) {
  const out = []
  const seen = new Set()
  for (const item of tasks) {
    if (!item || item.id == null || item.id === '') continue
    const id = String(item.id)
    if (seen.has(id)) continue
    seen.add(id)
    out.push(id)
  }
  return out
}

function extractIdsFromJsonLikeFragment (s) {
  const taskIdsOrdered = []
  const seen = new Set()
  const re = /"id"\s*:\s*"((?:[^"\\]|\\.)*)"/g
  let m
  while ((m = re.exec(s)) !== null) {
    const inner = m[1]
    const id = inner.replace(/\\(.)/g, (_c, ch) => {
      if (ch === '"' || ch === '\\') return ch
      if (ch === 'n') return '\n'
      return `\\${ch}`
    })
    if (!id || seen.has(id)) continue
    seen.add(id)
    taskIdsOrdered.push(id)
  }
  return taskIdsOrdered
}
