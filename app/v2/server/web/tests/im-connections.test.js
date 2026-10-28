import assert from 'node:assert/strict'
import { test } from 'node:test'
import { effectScope } from 'vue'
import { useIMConnection } from '../src/use-im-connection.js'
import { api } from '../src/api.js'

const connection = { id: 'im_own', name: 'My bot', revision: 3, enabled: true, paired: false }
const status = { revision: 3, state: 'awaiting_pairing', paired: false }
function setup(t, overrides = {}) {
  const client = {
    imConnection: async () => ({ ...connection }), imConnectionStatus: async () => ({ ...status }),
    imDeliveries: async () => ({ items: [], next_cursor: null }), ...overrides,
  }
  const scope = effectScope()
  const state = scope.run(() => useIMConnection({ ...connection }, { client }))
  t.after(() => scope.stop())
  return { state, client, scope }
}

test('IM API keeps own scope and supplies CAS revisions and explicit duplicate consent', async t => {
  const previous = Object.getOwnPropertyDescriptor(globalThis, 'localStorage')
  Object.defineProperty(globalThis, 'localStorage', { configurable: true, value: { getItem: () => '' } })
  t.after(() => { if (previous) Object.defineProperty(globalThis, 'localStorage', previous); else delete globalThis.localStorage })
  const calls = []
  t.mock.method(globalThis, 'fetch', async (url, options) => { calls.push([url, options]); return Response.json({ data: {} }) })
  await api.imConnections()
  await api.imDeliveries('im/a', { after: 51, unresolved: true })
  await api.updateIMConnection('im/a', { revision: 7, enabled: false })
  await api.retryIMDelivery(8, 4, true)
  await api.discardIMDelivery(9, 5)
  await api.deleteIMConnection('im/a', 8)
  assert.equal(calls[0][0], '/api/im/connections')
  assert.match(calls[1][0], /im%2Fa\/deliveries\?after=51&limit=50&unresolved=true/)
  assert.deepEqual(JSON.parse(calls[2][1].body), { revision: 7, enabled: false })
  assert.deepEqual(JSON.parse(calls[3][1].body), { revision: 4, allow_duplicate: true })
  assert.match(calls[4][0], /\/9\?revision=5$/)
  assert.match(calls[5][0], /im%2Fa\?revision=8$/)
  assert.ok(calls.every(([, options]) => !options.headers['X-Sage-View-User']))
})

test('mismatched connection/status revisions never claim a current connection state', async t => {
  const { state } = setup(t, { imConnectionStatus: async () => ({ ...status, revision: 4 }) })
  await state.refresh()
  assert.equal(state.status.value, null)
  assert.equal(state.connection.value.revision, 3)
})

test('connection writes are single-flight and conflicts do not silently resubmit', async t => {
  let rejectWrite, writes = []
  const { state } = setup(t, { updateIMConnection: (id, body) => { writes.push([id, body]); return new Promise((_, reject) => { rejectWrite = reject }) } })
  const pending = state.toggle()
  assert.equal(await state.toggle(), false)
  rejectWrite(Error('版本冲突，请刷新'))
  assert.equal(await pending, false)
  assert.deepEqual(writes, [['im_own', { revision: 3, enabled: false }]])
  assert.equal(state.connection.value.enabled, true)
  assert.match(state.error.value, /版本冲突/)
})

test('late status reads cannot overwrite a successful enable/disable action', async t => {
  let resolveOld
  const { state, client } = setup(t, { imConnection: () => new Promise(resolve => { resolveOld = resolve }) })
  const old = state.refresh()
  const updated = { ...connection, revision: 4, enabled: false }
  client.imConnection = async () => updated
  client.imConnectionStatus = async () => ({ revision: 4, state: 'disabled', paired: false })
  client.updateIMConnection = async () => updated
  assert.equal(await state.toggle(), true)
  resolveOld({ ...connection })
  await old
  assert.equal(state.connection.value.revision, 4)
  assert.equal(state.status.value.state, 'disabled')
})

test('unknown retry requires consent and failed mutation preserves the loaded queue', async t => {
  let calls = 0
  const row = { id: 8, revision: 4, state: 'unknown' }
  const { state, client } = setup(t, { imDeliveries: async () => ({ items: [row], next_cursor: null }) })
  client.retryIMDelivery = async (id, revision, consent) => { calls++; assert.deepEqual([id, revision, consent], [8, 4, true]); throw Error('投递版本冲突') }
  await state.loadDeliveries()
  assert.equal(await state.retry(row), false)
  assert.equal(calls, 0)
  assert.equal(await state.retry(row, true), false)
  assert.equal(calls, 1)
  assert.deepEqual(state.deliveries.value, [row])
  assert.match(state.error.value, /版本冲突/)
})

test('delivery pagination retains the filter and older records on a later-page failure', async t => {
  const row = { id: 51, state: 'failed' }, args = []
  const { state } = setup(t, { imDeliveries: async (id, options) => {
    args.push(options)
    if (options.after) throw Error('加载失败')
    return { items: [row], next_cursor: 51 }
  } })
  await state.loadDeliveries()
  await state.loadDeliveries(false)
  assert.deepEqual(args, [{ after: 0, unresolved: true }, { after: 51, unresolved: true }])
  assert.deepEqual(state.deliveries.value, [row])
  assert.equal(state.cursor.value, 51)
  assert.equal(state.deliveryError.value, '加载失败')
})

test('pairing data is ephemeral and disposed connections reject late pairing results', async t => {
  let resolvePair
  const { state, scope } = setup(t, { pairIMConnection: () => new Promise(resolve => { resolvePair = resolve }) })
  const pending = state.pair()
  scope.stop()
  resolvePair({ command: '/pair transient', expires_in: 600 })
  assert.equal(await pending, false)
  assert.equal(state.pairing.value, null)
})

test('expired pairing commands are cleared instead of remaining copyable', async t => {
  t.mock.timers.enable({ apis: ['Date', 'setInterval'], now: 1000 })
  const { state } = setup(t, { pairIMConnection: async () => ({ command: '/pair short-lived', expires_in: 2 }) })
  state.start()
  assert.equal(await state.pair(), true)
  assert.equal(state.secondsLeft.value, 2)
  t.mock.timers.tick(3000)
  assert.equal(state.secondsLeft.value, 0)
  assert.equal(state.pairing.value, null)
})


test('credential recovery refreshes the unavailable state without enabling the connection', async t => {
  let recovered = false
  const { state } = setup(t, {
    imConnection: async () => ({ ...connection, enabled: false, credentials_error: recovered ? '' : '密钥不可用' }),
    imConnectionStatus: async () => ({ ...status, state: recovered ? 'disabled' : 'unavailable' }),
    testIMConnection: async () => { recovered = true; return { credentials_valid: true } },
  })
  await state.refresh()
  assert.equal(state.status.value.state, 'unavailable')
  assert.equal(await state.probe(), true)
  assert.equal(state.status.value.state, 'disabled')
  assert.equal(state.connection.value.enabled, false)
  assert.equal(state.connection.value.credentials_error, '')
})
