import assert from 'node:assert/strict'
import { test } from 'node:test'
import { api, isForeign } from '../src/api.js'

function session(t, role = 'admin') {
  const previous = Object.getOwnPropertyDescriptor(globalThis, 'localStorage')
  Object.defineProperty(globalThis, 'localStorage', { configurable: true, value: {
    getItem: key => key.endsWith('.user') ? JSON.stringify({ user_id: 'admin', role }) : 'token',
  } })
  t.after(() => {
    if (previous) Object.defineProperty(globalThis, 'localStorage', previous)
    else delete globalThis.localStorage
  })
}
const users = [{ user_id: 'admin', username: 'admin', role: 'admin' }, { user_id: 'alice', username: 'alice', role: 'user' }]

test('admin business lists include every owner and retain colliding names', async t => {
  session(t)
  t.mock.method(globalThis, 'fetch', async (url, init) => {
    assert.equal(init.headers.Authorization, 'Bearer token')
    return Response.json({ data: url === '/api/admin/users' ? users : [{ name: 'same-name' }] })
  })
  for (const method of ['listAgents', 'listModels', 'listMcp', 'listA2aAgents', 'listKeys', 'packages', 'packageRuns']) {
    const rows = await api[method]()
    assert.equal(rows.length, 2, method)
    assert.deepEqual(rows.map(row => row._owner.user_id), ['admin', 'alice'])
    assert.equal(isForeign(rows[0]), false)
    assert.equal(isForeign(rows[1]), true)
  }
  assert.ok(fetch.mock.calls.some(call => call.arguments[1].headers['X-Sage-View-User'] === 'alice'))
  assert.ok(fetch.mock.calls.every(call => !call.arguments[1].method || call.arguments[1].method === 'GET'))
})

test('ordinary user lists stay in their own scope', async t => {
  session(t, 'user')
  t.mock.method(globalThis, 'fetch', async () => Response.json({ data: [{ id: 'own' }] }))
  assert.deepEqual(await api.listAgents(), [{ id: 'own' }])
  assert.equal(fetch.mock.calls.length, 1)
  assert.equal(fetch.mock.calls[0].arguments[1].headers['X-Sage-View-User'], undefined)
})

test('admin own-only selectors and writes do not inherit a foreign read scope', async t => {
  session(t)
  t.mock.method(globalThis, 'fetch', async () => Response.json({ data: [] }))
  await api.listAgents(false)
  await api.listModels(false)
  await api.getAgent('foreign', users[1])
  await api.listAgentSkills('foreign', users[1])
  await api.package('same-ref', users[1])
  await api.packageRun('same-operation', users[1])
  await api.packageEvents('same-operation', 200, users[1])
  await api.threadEvents('thread', 500, users[1], 500)
  await api.createAgent({ name: 'own' })
  assert.equal(fetch.mock.calls[0].arguments[0], '/api/agents')
  assert.equal(fetch.mock.calls[0].arguments[1].headers['X-Sage-View-User'], undefined)
  for (const call of fetch.mock.calls.slice(2, 8)) assert.equal(call.arguments[1].headers['X-Sage-View-User'], 'alice')
  assert.match(fetch.mock.calls[7].arguments[0], /offset=500/)
  assert.equal(fetch.mock.calls[8].arguments[1].headers['X-Sage-View-User'], undefined)
})

test('skills are attributed once and approval pagination advances across empty owners', async t => {
  session(t)
  const own = { skill_id: 'own', owner_user_id: 'admin' }
  const foreign = { skill_id: 'foreign', owner_user_id: 'alice' }
  t.mock.method(globalThis, 'fetch', async (url, init) => {
    const owner = init.headers['X-Sage-View-User']
    let data
    if (url === '/api/admin/users') data = users
    else if (url === '/api/skills') data = owner === 'admin' ? [own, foreign] : [foreign]
    else data = owner === 'admin' ? { items: [], next_offset: null } : { items: [], next_offset: 100 }
    return Response.json({ data })
  })
  const skills = await api.listSkills()
  assert.deepEqual(skills.map(row => [row.skill_id, row._owner.user_id]), [['own', 'admin'], ['foreign', 'alice']])
  assert.deepEqual(await api.approvals(50), { items: [], next_offset: 100 })
})
