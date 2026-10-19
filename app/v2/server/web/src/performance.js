export const purposeLabels = { agent: '主模型', conversation_summary: '摘要压缩', memory_recall_query: '记忆检索', continuation_judge: '续跑判断' }
export function duration(ms) {
  if (ms == null || !Number.isFinite(ms)) return '—'
  if (ms < 1000) return `${Math.round(ms)} ms`
  if (ms < 60000) return `${(ms / 1000).toFixed(2)} s`
  return `${(ms / 60000).toFixed(2)} min`
}
export function percentage(value) { return value == null ? '—' : `${(value * 100).toFixed(1)}%` }
export function timeRange(period, day, now = new Date()) {
  let end = new Date(now), start
  if (period === 'day') {
    start = new Date(`${day}T00:00:00`)
    end = new Date(start); end.setDate(end.getDate() + 1)
  } else {
    start = new Date(end.getTime() - Number(period) * 3600000)
  }
  return { start: start.toISOString(), end: end.toISOString() }
}
export function chartSegments(buckets, metric, quantile, width = 900, height = 180) {
  const values = buckets.map(b => b[metric]?.[quantile] ?? null)
  const finite = values.filter(v => v != null)
  const maximum = Math.max(1, ...finite)
  const points = values.map((v, i) => v == null ? null : [16 + (width - 32) * i / Math.max(1, values.length - 1), height - 20 - (height - 40) * v / maximum])
  const segments = []; let current = []
  for (const p of points) {
    if (p) current.push(p)
    else if (current.length) { segments.push(current); current = [] }
  }
  if (current.length) segments.push(current)
  return { maximum, points: points.filter(Boolean), segments: segments.map(s => s.map(p => p.join(',')).join(' ')) }
}
