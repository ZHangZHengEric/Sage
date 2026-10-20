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
  const records = (span?.events || []).filter(event => event.name?.startsWith('sage.diagnostic.')).map(event => {
    const value = attribute(event, 'sage.diagnostic.data')
    try { return { kind: attribute(event, 'sage.diagnostic.kind'), timestamp: event.timestamp, data: JSON.parse(value) } }
    catch { return { kind: attribute(event, 'sage.diagnostic.kind'), timestamp: event.timestamp, data: value } }
  })
  const stored = attribute(span, 'sage.diagnostic.data')
  if (stored != null) records.unshift({kind:attribute(span, 'sage.diagnostic.kind') || 'record', timestamp:span.start_time, data:decoded(stored)})
  return records
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

function decoded(value) {
  if (typeof value !== 'string') return value
  try { return JSON.parse(value) } catch { return value }
}
function canonical(value) {
  if (Array.isArray(value)) return value.map(canonical)
  if (value && typeof value === 'object') return Object.fromEntries(Object.keys(value).sort().map(key => [key, canonical(value[key])]))
  return value
}
function sameValue(a, b) {
  return a != null && b != null && JSON.stringify(canonical(decoded(a))) === JSON.stringify(canonical(decoded(b)))
}
function hasContent(value) {
  return value != null && value !== '' && (typeof value !== 'object' || Object.keys(value).length > 0)
}
export function detailTabs(span) {
  if (!span) return []
  const input = attribute(span, 'input.value'), output = attribute(span, 'output.value')
  const raw = diagnosticRecords(span).flatMap(record => {
    const data = record.data
    if (!data || typeof data !== 'object' || Array.isArray(data)) return [record]
    const unique = { ...data }
    if (sameValue(unique.request, input)) delete unique.request
    if (sameValue(unique.normalized_request, input) || sameValue(unique.normalized_request, data.request)) delete unique.normalized_request
    if (sameValue(unique.response, output)) delete unique.response
    if (sameValue(unique.request_id, attribute(span, 'request_id') ?? span.request_id)) delete unique.request_id
    return Object.keys(unique).length ? [{ ...record, data:unique }] : []
  })
  const events = (span.events || []).filter(event => !event.name?.startsWith('sage.diagnostic.'))
  // Payloads have dedicated tabs. Keep timing events and summary attributes,
  // but omit their serialized transport copies from the attributes inspector.
  const hidden = new Set(['input.value', 'output.value', 'sage.diagnostic.data', 'sage.diagnostic.kind', 'sage.performance.data'])
  function uniqueAttributes(value, prefix = '') {
    return Object.fromEntries(Object.entries(value || {}).flatMap(([key, item]) => {
      const path = prefix ? `${prefix}.${key}` : key
      if (hidden.has(path)) return []
      if (item && typeof item === 'object' && !Array.isArray(item)) {
        const nested = uniqueAttributes(item, path)
        return Object.keys(nested).length ? [[key, nested]] : []
      }
      return [[key, item]]
    }))
  }
  const attributes = uniqueAttributes(span.attributes)
  return [
    {id:'input', name:'输入', value:input}, {id:'output', name:'输出', value:output},
    {id:'raw', name:'原始记录', value:raw}, {id:'events', name:'事件', value:events},
    {id:'attributes', name:'属性', value:attributes},
  ].filter(item => hasContent(item.value))
}
