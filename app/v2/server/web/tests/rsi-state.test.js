import assert from 'node:assert/strict'
import { test } from 'node:test'
import { effectScope } from 'vue'
import { useRsi } from '../src/use-rsi.js'
import { api } from '../src/api.js'

const bundle = { manifest: { entrypoint: { agent: 'a' }, agents: { a: { instructions: { inline: 'before' } } } }, files: {} }
const finished = { id: 'run', status: 'completed', base_package_ref: 'base', candidate_ref: 'next', versions: [
  { version_id: 'v1', package_ref: 'next', iteration: 1 }, { version_id: 'v2', package_ref: 'other', iteration: 2 }],
  result: { iterations: [{ iteration: 0, package: bundle }] } }
function setup(t, overrides = {}) {
  const client = { getAgent: async () => ({ id: 'a', package_ref: 'base' }), listModels: async () => [], rsiRuns: async () => [],
    rsiRun: async () => finished, rsiVersion: async (a, r, v) => ({ ...finished.versions.find(row => row.version_id === v), package: bundle }), ...overrides }
  const scope = effectScope(), state = scope.run(() => useRsi({ client, delay: 60000 }))
  t.after(() => scope.stop())
  return { state, client, scope }
}

test('RSI API encodes identities and applies with the explicit original package reference', async t => {
  const descriptor = Object.getOwnPropertyDescriptor(globalThis, 'localStorage')
  Object.defineProperty(globalThis, 'localStorage', { configurable: true, value: { getItem: () => '' } })
  t.after(() => descriptor ? Object.defineProperty(globalThis, 'localStorage', descriptor) : delete globalThis.localStorage)
  const calls = []
  t.mock.method(globalThis, 'fetch', async (url, options) => { calls.push([url, options]); return Response.json({ data: {} }) })
  await api.startRsi('a/b', { goal: 'test', request_id: 'id' })
  await api.rsiRuns('a/b', 50)
  await api.rsiVersion('a/b', 'r/b', 'v/b')
  await api.applyRsiVersion('a/b', 'r/b', 'v/b', 'original')
  assert.match(calls[0][0], /a%2Fb\/rsi\/runs$/)
  assert.match(calls[1][0], /offset=50$/)
  assert.match(calls[2][0], /r%2Fb\/versions\/v%2Fb$/)
  assert.deepEqual(JSON.parse(calls[3][1].body), { expected_package_ref: 'original' })
  assert.ok(calls.every(([, options]) => !options.headers['X-Sage-View-User']))
})

test('an ambiguous start retry keeps its request ID and writes remain single-flight', async t => {
  const requests = []
  let reject
  const { state } = setup(t, { startRsi: (id, body) => { requests.push(body); return new Promise((_, no) => { reject = no }) } })
  await state.load('a')
  const first = state.start({ goal: 'improve' })
  assert.equal(await state.start({ goal: 'improve' }), false)
  reject(Error('network lost')); assert.equal(await first, false)
  const second = state.start({ goal: 'improve' })
  reject(Error('network lost')); await second
  assert.equal(requests[0].request_id, requests[1].request_id)
})

test('late version responses never replace the selected candidate and stale config cannot apply', async t => {
  let resolveFirst, writes = 0
  const { state, client } = setup(t, { rsiVersion: (a, r, v) => v === 'v1' ? new Promise(resolve => { resolveFirst = resolve }) :
    Promise.resolve({ ...finished.versions[1], package: bundle }), applyRsiVersion: async () => { writes++ } })
  await state.load('a')
  const read = state.selectRun('run')
  await new Promise(resolve => setImmediate(resolve))
  await state.selectVersion('v2')
  resolveFirst({ ...finished.versions[0], package: bundle }); await read
  assert.equal(state.version.value.version_id, 'v2')
  assert.ok(state.canApply.value)
  client.getAgent = async () => ({ id: 'a', package_ref: 'edited' })
  await state.refresh()
  assert.equal(await state.apply(), false)
  assert.equal(writes, 0)
})

test('application conflict is visible and never retried with a new package reference', async t => {
  const calls = []
  const { state } = setup(t, { applyRsiVersion: async (...args) => { calls.push(args); throw Object.assign(Error('conflict'), { status: 409 }) } })
  await state.load('a'); await state.selectRun('run')
  assert.equal(await state.apply(), false)
  assert.deepEqual(calls[0], ['a', 'run', 'v1', 'base'])
  assert.match(state.actionError.value, /最新配置新建实验/)
  assert.equal(calls.length, 1)
})

test('old poll cannot overwrite a successful stop and unmounted views ignore late reads', async t => {
  let resolvePoll
  const { state, client, scope } = setup(t, { rsiRun: async () => ({ id: 'run', status: 'running', versions: [] }),
    cancelRsi: async () => ({ id: 'run', status: 'interrupted', versions: [] }) })
  await state.load('a'); await state.selectRun('run')
  client.rsiRun = () => new Promise(resolve => { resolvePoll = resolve })
  const reading = state.refreshRun()
  await state.control('cancel')
  resolvePoll({ id: 'run', status: 'running' }); await reading
  assert.equal(state.run.value.status, 'interrupted')
  const late = state.refreshRun(); scope.stop()
  resolvePoll({ id: 'run', status: 'completed' }); await late
  assert.equal(state.run.value.status, 'interrupted')
})

test('late history pages cannot replace the most recently requested page', async t => {
  const { state, client } = setup(t)
  await state.load('a')
  let finishOld
  client.rsiRuns = (id, offset) => offset === 50 ? new Promise(resolve => { finishOld = resolve }) : Promise.resolve([{ id: 'newest' }])
  const old = state.refreshHistory(50)
  await state.refreshHistory(0)
  finishOld([{ id: 'older' }]); await old
  assert.equal(state.offset.value, 0)
  assert.equal(state.runs.value[0].id, 'newest')
})
