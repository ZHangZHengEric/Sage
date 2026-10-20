import test from 'node:test'
import assert from 'node:assert/strict'
import { duration, percentage, timeRange, chartSegments, populatedBuckets } from '../src/performance.js'
test('missing timings are never presented as zero', () => {
  assert.equal(duration(null), '—'); assert.equal(percentage(null), '—')
  assert.equal(duration(1234), '1.23 s'); assert.equal(percentage(.125), '12.5%')
})
test('relative windows retain exact hours', () => {
  const range = timeRange('6', '', new Date('2026-10-19T10:00:00Z'))
  assert.equal(range.start, '2026-10-19T04:00:00.000Z')
  assert.equal(range.end, '2026-10-19T10:00:00.000Z')
})
test('calendar day uses local midnight and the following date', () => {
  const range = timeRange('day','2026-10-19')
  const a = new Date(range.start), b = new Date(range.end)
  assert.equal(a.getHours(),0); assert.equal(a.getDate(),19); assert.equal(b.getDate(),20)
})
test('trend leaves gaps where there are no samples', () => {
  const buckets = [1,null,3].map(v => ({ first_token_ms:{ p95:v } }))
  const graph = chartSegments(buckets,'first_token_ms','p95')
  assert.equal(graph.segments.length,2); assert.equal(graph.points.length,2)
  assert.equal(graph.maximum,3)
})

test('a single populated bucket retains its time and measured value', () => {
  const buckets = [{ time:'2026-10-20T06:00:00Z', first_token_ms:{p95:null} }, {time:'2026-10-20T07:00:00Z', measured:4, first_token_ms:{p95:3510}}]
  const graph = chartSegments(buckets, 'first_token_ms', 'p95')
  assert.equal(graph.observations.length, 1)
  assert.equal(graph.observations[0].bucket.time, buckets[1].time)
  assert.equal(graph.observations[0].value, 3510)
  assert.equal(graph.segments.length, 1)
  assert.equal(graph.points.length, 1)
})
test('the bucket table shows recent activity first and retains incomplete requests', () => {
  const buckets = [{time:'2026-10-20T01:00:00Z', requests:0, measured:0}, {time:'2026-10-20T02:00:00Z', requests:1, measured:1}, {time:'2026-10-20T03:00:00Z', requests:1, measured:0}]
  assert.deepEqual(populatedBuckets(buckets).map(b => b.time), [buckets[2].time, buckets[1].time])
  assert.equal(buckets.length, 3)
})
