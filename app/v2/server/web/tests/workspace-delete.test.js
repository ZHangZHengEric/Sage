import assert from 'node:assert/strict'
import { test } from 'node:test'
import { createRenderer, createSSRApp, nextTick, ssrContextKey } from 'vue'
import { renderToString } from 'vue/server-renderer'
import { createServer } from 'vite'

async function setup(t) {
  const server = await createServer({ optimizeDeps: { noDiscovery: true, include: [] }, server: { middlewareMode: true, watch: null, hmr: false, ws: false } })
  t.after(() => server.close())
  const previous = Object.getOwnPropertyDescriptor(globalThis, 'localStorage')
  Object.defineProperty(globalThis, 'localStorage', { configurable: true, value: { getItem: key => key.endsWith('.user') ? JSON.stringify({ user_id: 'alice' }) : '' } })
  t.after(() => previous ? Object.defineProperty(globalThis, 'localStorage', previous) : delete globalThis.localStorage)
  const { api } = await server.ssrLoadModule('/src/api.js')
  const { default: Panel } = await server.ssrLoadModule('/src/components/WorkspacePanel.vue')
  const { default: Tree } = await server.ssrLoadModule('/src/components/WorkspaceFileTree.vue')
  return { api, Tree, mount: async (props = {}) => {
    const renderer = createRenderer({ createComment: () => ({}), insert() {}, remove() {}, parentNode: () => null, nextSibling: () => null })
    const app = renderer.createApp({ ...Panel, render: () => null }, props)
    app.provide(ssrContextKey, {})
    const vm = app.mount({})
    t.after(() => app.unmount())
    await new Promise(resolve => setImmediate(resolve)); await nextTick()
    return vm.$.setupState
  } }
}

test('workspace delete preserves a failed selection for retry, guards duplicate submits and refreshes after success', async t => {
  const { api, mount } = await setup(t)
  let files = [{ path: '项目/nested', name: 'nested', is_directory: true }]
  t.mock.method(api, 'workspaceFiles', async () => [...files])
  let finish
  t.mock.method(api, 'workspaceDelete', async () => { throw new Error('workspace busy') })
  const state = await mount({ threadId: 'session', agentId: 'agent' })
  state.requestDelete(files[0])
  await state.remove()
  assert.equal(state.deleteError, 'workspace busy')
  assert.equal(state.deleteTarget.path, '项目/nested')
  assert.equal(state.files.length, 1)
  api.workspaceDelete.mock.mockImplementation(() => new Promise(resolve => { finish = resolve }))
  const pending = state.remove()
  assert.equal(state.deleting, true)
  await state.remove()
  assert.equal(api.workspaceDelete.mock.callCount(), 2)
  assert.deepEqual(api.workspaceDelete.mock.calls[1].arguments, ['项目/nested', true, 'session', 'agent'])
  files = []
  finish({ deleted: true })
  await pending
  assert.equal(state.deleteTarget, null)
  assert.deepEqual(state.files, [])
  assert.equal(state.deleting, false)
})

test('foreign workspace stays readonly and row delete follows download', async t => {
  const { api, Tree, mount } = await setup(t)
  const item = { path: 'file.txt', name: 'file.txt', is_directory: false, size: 2 }
  t.mock.method(api, 'workspaceFiles', async () => [item])
  t.mock.method(api, 'workspaceDelete', async () => { throw new Error('must not delete') })
  const state = await mount({ owner: { user_id: 'bob' }, threadId: 'foreign' })
  state.requestDelete(item)
  await state.remove()
  assert.equal(state.deleteTarget, null)
  assert.equal(api.workspaceDelete.mock.callCount(), 0)
  const html = await renderToString(createSSRApp(Tree, { item, canDelete: true }))
  assert.ok(html.indexOf('aria-label="下载 file.txt"') < html.indexOf('aria-label="删除 file.txt"'))
  const readonly = await renderToString(createSSRApp(Tree, { item, canDelete: false }))
  assert.doesNotMatch(readonly, /aria-label="删除/)
})

test('workspace delete encodes a selected path and prefers Session identity over Agent identity', async t => {
  const { api } = await setup(t)
  t.mock.method(globalThis, 'fetch', async () => new Response(JSON.stringify({ data: { deleted: true } })))
  await api.workspaceDelete('项目/a & b.txt', false, 'thread & 1', 'ignored')
  const [url, options] = fetch.mock.calls[0].arguments
  const query = new URL(url, 'http://localhost').searchParams
  assert.equal(options.method, 'DELETE')
  assert.equal(query.get('path'), '项目/a & b.txt')
  assert.equal(query.get('thread_id'), 'thread & 1')
  assert.equal(query.has('agent_id'), false)
  assert.equal(query.get('recursive'), 'false')
  await api.workspaceDelete('folder', true, '', 'agent')
  assert.equal(new URL(fetch.mock.calls[1].arguments[0], 'http://localhost').searchParams.get('agent_id'), 'agent')
})
