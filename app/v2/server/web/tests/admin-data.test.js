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

test('admin agent summaries use one aggregate request and retain ownership', async t => {
  session(t)
  t.mock.method(globalThis, 'fetch', async url => {
    assert.equal(url, '/api/admin/agents')
    return Response.json({ data: [{ id: 'alice-agent', user_id: 'alice', username: 'alice' }] })
  })
  const rows = await api.agentSummaries()
  assert.equal(fetch.mock.calls.length, 1)
  assert.equal(isForeign(rows[0]), true)
  assert.deepEqual(rows[0]._owner, { user_id: 'alice', username: 'alice' })
})

test('ordinary user agent summaries make one own-scope request', async t => {
  session(t, 'user')
  t.mock.method(globalThis, 'fetch', async url => {
    assert.equal(url, '/api/agents/summary')
    return Response.json({ data: [{ id: 'own' }] })
  })
  assert.deepEqual(await api.agentSummaries(), [{ id: 'own' }])
  assert.equal(fetch.mock.calls.length, 1)
})

test('admin business lists include every owner and retain colliding names', async t => {
  session(t)
  t.mock.method(globalThis, 'fetch', async (url, init) => {
    assert.equal(init.headers.Authorization, 'Bearer token')
    return Response.json({ data: url === '/api/admin/users' ? users : [{ name: 'same-name' }] })
  })
  for (const method of ['listAgents', 'listKeys', 'packages', 'packageRuns']) {
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
  for (const method of ['listAgents', 'listModels', 'listMcp', 'listA2aAgents', 'listSkills']) {
    assert.deepEqual(await api[method](), [{ id: 'own' }])
  }
  assert.equal(fetch.mock.calls.length, 5)
  for (const call of fetch.mock.calls) {
    assert.equal(call.arguments[0].includes('/admin/'), false)
    assert.equal(call.arguments[1].headers['X-Sage-View-User'], undefined)
  }
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

test('workspace catalogs use one aggregate request and retain each owner', async t => {
  session(t)
  const paths = { listModels: '/api/admin/models', listMcp: '/api/admin/mcp', listA2aAgents: '/api/admin/a2a-agents', listSkills: '/api/admin/skills' }
  let expectedPath
  t.mock.method(globalThis, 'fetch', async (url, init) => {
    assert.equal(url, expectedPath)
    assert.equal(init.headers['X-Sage-View-User'], undefined)
    return Response.json({ data: users.map(owner => ({ name: 'same', user_id: owner.user_id, username: owner.username })) })
  })
  for (const [method, path] of Object.entries(paths)) {
    expectedPath = path
    const rows = await api[method]()
    assert.deepEqual(rows.map(row => row._owner.user_id), ['admin', 'alice'])
    assert.equal(isForeign(rows[1]), true)
  }
  assert.equal(fetch.mock.calls.length, 4)
})

test('own agent summaries skip admin aggregation for selectors', async t => {
  session(t)
  t.mock.method(globalThis, 'fetch', async url => {
    assert.equal(url, '/api/agents/summary')
    return Response.json({ data: [{ id: 'own' }] })
  })
  assert.deepEqual(await api.agentSummaries(false), [{ id: 'own' }])
  assert.equal(fetch.mock.calls.length, 1)
})

test('workspace reads bind to the Session even without owner metadata', async t => {
  session(t)
  t.mock.method(globalThis, 'fetch', async (url, init) => {
    assert.equal(new URL(url, 'http://localhost').searchParams.get('thread_id'), 'external/session')
    assert.equal(init.headers['X-Sage-View-User'], undefined)
    return url.includes('/download') ? new Response('file') : Response.json({ data: [] })
  })
  await api.workspaceFiles('', undefined, 'external/session')
  await api.workspaceFiles('nested', users[0], 'external/session')
  await api.workspaceDownload('nested/file.txt', users[0], 'external/session')
  assert.equal(fetch.mock.calls.length, 3)
})


test('new conversation workspace reads use the selected Agent', async t => {
  session(t)
  t.mock.method(globalThis, 'fetch', async url => {
    const params = new URL(url, 'http://localhost').searchParams
    assert.equal(params.get('agent_id'), 'agent_123')
    assert.equal(params.has('thread_id'), false)
    return url.includes('/download') ? new Response('file') : Response.json({ data: [] })
  })
  await api.workspaceFiles('', undefined, '', 'agent_123')
  await api.workspaceDownload('file', undefined, '', 'agent_123')
})
