export function number(value) {
  return value == null ? '—' : new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 0 }).format(value)
}
export function cost(value) {
  return value == null ? '—' : new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 6 }).format(value)
}
export function attribute(span, key) {
  const attributes = span?.attributes || {}
  if (Object.hasOwn(attributes, key)) return attributes[key]
  return key.split('.').reduce((value, part) => value?.[part], attributes)
}
export function diagnosticRecords(span) {
  return (span?.events || []).filter(event => event.name?.startsWith('sage.diagnostic.')).map(event => {
    const value = attribute(event, 'sage.diagnostic.data')
    try { return { kind: attribute(event, 'sage.diagnostic.kind'), timestamp: event.timestamp, data: JSON.parse(value) } }
    catch { return { kind: attribute(event, 'sage.diagnostic.kind'), timestamp: event.timestamp, data: value } }
  })
}
export function pretty(value) {
  if (value == null) return '未采集'
  if (typeof value === 'string') {
    try { return JSON.stringify(JSON.parse(value), null, 2) } catch { return value }
  }
  return JSON.stringify(value, null, 2)
}
export function spanTree(spans) {
  const byId = new Map(spans.map(span => [span.span_id, span])), children = new Map()
  for (const span of byId.values()) {
    const parent = byId.has(span.parent_id) ? span.parent_id : null
    if (!children.has(parent)) children.set(parent, [])
    children.get(parent).push(span)
  }
  for (const rows of children.values()) rows.sort((a, b) => new Date(a.start_time) - new Date(b.start_time))
  const result = [], seen = new Set()
  function visit(root) {
    const pending = [{ ...root, depth: 0 }]
    while (pending.length) {
      const row = pending.pop()
      if (seen.has(row.span_id)) continue
      seen.add(row.span_id); result.push(row)
      for (const child of [...(children.get(row.span_id) || [])].reverse()) pending.push({ ...child, depth: row.depth + 1 })
    }
  }
  for (const span of children.get(null) || []) visit(span)
  // Missing parents and cycles must not hide records from the inspector.
  for (const span of byId.values()) if (!seen.has(span.span_id)) visit(span)
  return result
}
export function waterfall(spans, span) {
  const begins = spans.map(s => new Date(s.start_time).getTime())
  const ends = spans.map(s => new Date(s.end_time || s.start_time).getTime())
  const start = Math.min(...begins), range = Math.max(1, Math.max(...ends) - start)
  return { left: `${Math.max(0, (new Date(span.start_time).getTime() - start) / range * 100)}%`,
    width: `${Math.max(0, (new Date(span.end_time || span.start_time).getTime() - new Date(span.start_time).getTime()) / range * 100)}%` }
}
