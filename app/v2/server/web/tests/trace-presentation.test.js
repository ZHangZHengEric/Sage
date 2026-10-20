import test from 'node:test'
import assert from 'node:assert/strict'
import { spanTree, waterfall, pretty, attribute, cost, number } from '../src/trace-presentation.js'
test('tree retains orphans and cycles and sorts actual children', () => {
  const rows = spanTree([
    { span_id:'child',parent_id:'root',start_time:2 },
    { span_id:'root',parent_id:null,start_time:1 },
    { span_id:'a',parent_id:'b',start_time:3 },
    { span_id:'b',parent_id:'a',start_time:4 },
    { span_id:'orphan',parent_id:'missing',start_time:5 },
  ])
  assert.equal(rows.length,5)
  assert.equal(rows[0].span_id,'root')
  assert.equal(rows[1].depth,1)
})
test('raw inspector preserves long strings and handles nested attributes', () => {
  const original = 'secret-'+'x'.repeat(100000)
  assert.equal(pretty(original),original)
  assert.equal(attribute({attributes:{'input.value':original}},'input.value'),original)
  assert.equal(attribute({attributes:{input:{value:original}}},'input.value'),original)
  assert.equal(cost(null),'—'); assert.equal(number(null),'—')
})
test('waterfall uses the trace time range', () => {
  const rows = [{start_time:'2026-10-20T00:00:00Z',end_time:'2026-10-20T00:00:10Z'},
    {start_time:'2026-10-20T00:00:02Z',end_time:'2026-10-20T00:00:05Z'}]
  assert.deepEqual(waterfall(rows,rows[1]),{left:'20%',width:'30%'})
})
