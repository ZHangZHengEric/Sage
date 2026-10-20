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

test('raw inspector reads complete diagnostic events from the selected span', async () => {
  const { diagnosticRecords } = await import('../src/trace-presentation.js')
  const original = 'password=keep-' + 'x'.repeat(100000)
  const span = {events:[
    {name:'first_token',attributes:{duration_ms:100}},
    {name:'sage.diagnostic.response',timestamp:'2026-10-20T00:00:00Z',attributes:{
      'sage.diagnostic.kind':'response','sage.diagnostic.data':JSON.stringify({response:{text:original}})}},
  ]}
  const records = diagnosticRecords(span)
  assert.equal(records.length,1)
  assert.equal(records[0].data.response.text,original)
  assert.equal(records[0].kind,'response')
})

test('detail tabs show payloads once and preserve distinct wire data and events', async () => {
  const { detailTabs } = await import('../src/trace-presentation.js')
  const input = {messages:[{role:'user',content:'hello'}]}, output = {text:'done'}
  const span = {attributes:{'input.value':JSON.stringify(input),'output.value':JSON.stringify(output), 'sage.performance.data':'transport copy', 'sage.performance.total_ms':100, model:'test', request_id:'r'},events:[
    {name:'sage.diagnostic.request',attributes:{'sage.diagnostic.kind':'request','sage.diagnostic.data':JSON.stringify({request_id:'r',request:{messages:input.messages,temperature:.5},normalized_request:input})}},
    {name:'sage.diagnostic.response',attributes:{'sage.diagnostic.kind':'response','sage.diagnostic.data':JSON.stringify({request_id:'r',response:output})}},
    {name:'first_token',timestamp:'2026-10-20T00:00:00Z',attributes:{duration_ms:50}},
  ]}
  const before = JSON.stringify(span), tabs = detailTabs(span)
  assert.deepEqual(tabs.map(t => t.id), ['input','output','raw','events','attributes'])
  const raw = tabs.find(t => t.id === 'raw').value
  assert.equal(raw.length, 1)
  assert.equal(raw[0].data.request.temperature, .5)
  assert.equal(raw[0].data.normalized_request, undefined)
  assert.deepEqual(tabs.find(t => t.id === 'events').value.map(e => e.name), ['first_token'])
  assert.deepEqual(tabs.find(t => t.id === 'attributes').value, {'sage.performance.total_ms':100,model:'test',request_id:'r'})
  assert.equal(JSON.stringify(span), before)
})

test('empty and fully duplicated sections are hidden for nested attributes', async () => {
  const { detailTabs } = await import('../src/trace-presentation.js')
  const tabs = detailTabs({attributes:{input:{value:'{"a":1,"b":2}'},sage:{diagnostic:{data:JSON.stringify({request:{b:2,a:1}})}}},events:[]})
  assert.deepEqual(tabs.map(t => t.id), ['input'])
  assert.deepEqual(detailTabs({attributes:{},events:[]}), [])
})
