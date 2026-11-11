import assert from 'node:assert/strict'
import { test } from 'node:test'
import { createRenderer, nextTick, ssrContextKey } from 'vue'
import { createServer } from 'vite'

async function mountTiming(t, read, props = {}) {
  const server = await createServer({ optimizeDeps: { noDiscovery: true, include: [] }, server: { middlewareMode: true, watch: null, hmr: false, ws: false } })
  t.after(() => server.close())
  const { api } = await server.ssrLoadModule('/src/api.js')
  t.mock.method(api, 'threadRunTiming', read)
  const { default: Component } = await server.ssrLoadModule('/src/components/RunTimingDialog.vue')
  const renderer = createRenderer({ createComment: () => ({}), insert() {}, remove() {}, parentNode: () => null, nextSibling: () => null })
  const app = renderer.createApp({ ...Component, render: () => null }, { threadId: 'thread', runId: 'run', messages: [], ...props })
  app.provide(ssrContextKey, {})
  const vm = app.mount({})
  t.after(() => app.unmount())
  await new Promise(resolve => setImmediate(resolve)); await nextTick()
  return vm.$.setupState
}

test('waterfall keeps wall offsets, execution shares, point markers and unambiguous tool names', async t => {
  const owner = { user_id: 'alice' }
  const state = await mountTiming(t, async (threadId, runId, selectedOwner, signal) => {
    assert.equal(threadId, 'thread'); assert.equal(runId, 'run'); assert.deepEqual(selectedOwner, owner)
    assert.ok(signal instanceof AbortSignal)
    return { state: 'completed', timing: {
      total_ms: 8000, model_ms: 3000, tool_ms: 0, framework_ms: 5000, coverage: 'complete', waiting_ms: 97000,
      timeline: { wall_ms: 105000, truncated: false, entries: [
        { kind: 'model', start_ms: 100000, end_ms: 103000, purpose: 'agent' },
        { kind: 'waiting', start_ms: 2000, end_ms: 99000 },
        { kind: 'first_token', start_ms: 101000, end_ms: 101000 },
        { kind: 'tool', start_ms: 103000, end_ms: 104000, tool_call_id: 'call' },
        { kind: 'tool', start_ms: 104000, end_ms: 105000, tool_call_id: 'ambiguous' },
      ] },
    } }
  }, { owner, messages: [{ id: 'tools', role: 'assistant', toolCalls: [
    { id: 'call', function: { name: 'load_skill' } },
    { id: 'ambiguous', function: { name: 'first' } },
    { id: 'ambiguous', function: { name: 'second' } },
  ] }] })
  assert.equal(state.rows[0].label, '主模型 #1')
  assert.equal(state.rows[0].offset, 100000 / 105000 * 100)
  assert.equal(state.rows[0].width, 3000 / 105000 * 100)
  assert.equal(state.rows[2].point, true)
  assert.equal(state.rows[3].toolTitle, 'load_skill')
  assert.equal(state.rows[4].toolTitle, null)
  assert.equal(state.longestRow.kind, 'model')
  assert.equal(state.totals.label, '框架开销')
  assert.equal(state.totals.share, 63)
  assert.equal(state.duration(105000), '105.00 s')
  assert.equal(state.duration(null), '—')
  assert.equal(state.duration(3600000), '60.00 min')
})

test('truncated and incomplete timing never claims a longest phase or a complete breakdown', async t => {
  const state = await mountTiming(t, async () => ({ state: 'failed', timing: {
    total_ms: 1000, coverage: 'incomplete', timeline: { wall_ms: 1000, truncated: true,
      entries: Array.from({ length: 30 }, () => ({ kind: 'tool', start_ms: 0, end_ms: 1000 })),
    },
  } }))
  assert.equal(state.rows.length, 30)
  assert.equal(state.visibleCount, 24)
  assert.equal(state.totals, null)
  assert.equal(state.longestRow, null)
})

test('failed reads show an error and suspended runs retain their missing timing state', async t => {
  const failure = await mountTiming(t, async () => { throw Error('unavailable') })
  assert.equal(failure.request.loading, false)
  assert.equal(failure.request.error, true)
  const suspended = await mountTiming(t, async () => ({ state: 'suspended', timing: null }))
  assert.equal(suspended.request.data.state, 'suspended')
  assert.equal(suspended.timing, null)
  assert.deepEqual(suspended.rows, [])
})
