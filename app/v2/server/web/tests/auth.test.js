import assert from 'node:assert/strict'
import { test } from 'node:test'
import { clearSession, getUser, setSession } from '../src/auth.js'
import { api } from '../src/api.js'

test('browser sessions use cookies and remove persisted legacy credentials', async t => {
  const storage = new Map([['sage.server_v2.token', 'old-jwt'], ['sage.server_v2.user', '{}']])
  Object.defineProperty(globalThis, 'localStorage', { configurable: true, value: { getItem: key => storage.get(key), removeItem: key => storage.delete(key) } })
  Object.defineProperty(globalThis, 'document', { configurable: true, value: { cookie: 'sage_server_v2_csrf=csrf-value' } })
  t.after(() => { delete globalThis.localStorage; delete globalThis.document })
  setSession({ user_id: 'user', role: 'user' })
  assert.equal(storage.has('sage.server_v2.token'), false)
  assert.equal(storage.has('sage.server_v2.user'), false)
  assert.equal(getUser().user_id, 'user')
  t.mock.method(globalThis, 'fetch', async (url, init) => {
    assert.equal(init.credentials, 'same-origin')
    assert.equal(init.headers.Authorization, undefined)
    assert.equal(init.headers['X-CSRF-Token'], 'csrf-value')
    return Response.json({ data: null })
  })
  await api.logout()
  clearSession()
  assert.equal(getUser(), null)
})
