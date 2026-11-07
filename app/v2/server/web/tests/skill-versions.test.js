import assert from 'node:assert/strict'
import { test } from 'node:test'
import { createRenderer, ssrContextKey } from 'vue'
import { createServer } from 'vite'

async function setup(t, component = 'SkillVersions') {
  const server = await createServer({ optimizeDeps: { noDiscovery: true, include: [] }, server: { middlewareMode: true, watch: null, hmr: false, ws: false } })
  t.after(() => server.close())
  const { api } = await server.ssrLoadModule('/src/api.js')
  t.mock.method(api, 'skillVersions', async () => [{ version_id: 'v2', revision: 2 }, { version_id: 'v1', revision: 1 }])
  t.mock.method(api, 'getSkill', async () => ({ version_id: 'v2' }))
  t.mock.method(api, 'agentSummaries', async () => [{ id: 'agent', name: 'Demo' }])
  t.mock.method(api, 'skillVersion', async (_, version) => ({ content: version }))
  const { default: Component } = await server.ssrLoadModule(`/src/components/${component}.vue`)
  const renderer = createRenderer({ createComment: () => ({}), insert() {}, remove() {}, parentNode: () => null, nextSibling: () => null })
  const app = renderer.createApp({ ...Component, render: () => null }, { item: { skill_id: 'demo', version_id: 'v2' } })
  app.provide(ssrContextKey, {})
  const vm = app.mount({})
  t.after(() => app.unmount())
  await new Promise(resolve => setTimeout(resolve, 30))
  return { api, state: vm.$.setupState }
}

test('rollback uses the observed head and refreshes the history', async t => {
  const { api, state } = await setup(t)
  await state.select('v1')
  t.mock.method(api, 'rollbackSkill', async (id, body) => {
    assert.equal(id, 'demo')
    assert.deepEqual(body, { version_id: 'v1', expected_version_id: 'v2' })
    return { version_id: 'v3', revision: 3 }
  })
  t.mock.method(api, 'getSkill', async () => ({ version_id: 'v3' }))
  await state.rollback()
  assert.equal(state.head, 'v3')
  assert.match(state.message, /3/)
})

test('version selection ignores stale content and pin changes are explicit', async t => {
  const { api, state } = await setup(t)
  let finish
  t.mock.method(api, 'skillVersion', (_, version) => version === 'v1'
    ? new Promise(resolve => { finish = resolve }) : Promise.resolve({ content: 'new' }))
  const old = state.select('v1')
  await state.select('v2')
  finish({ content: 'old' })
  await old
  assert.equal(state.content, 'new')
  t.mock.method(api, 'listAgentSkills', async () => [{ skill_id: 'demo', version_id: 'v2', version_policy: 'latest' }])
  state.agentId = 'agent'
  await state.loadBinding()
  state.pin = 'v1'
  t.mock.method(api, 'bindSkillVersion', async (agent, id, version) => {
    assert.deepEqual([agent, id, version], ['agent', 'demo', 'v1'])
    return { skill_id: 'demo', version_id: 'v1', version_policy: 'pinned' }
  })
  await state.saveBinding()
  assert.equal(state.binding.version_policy, 'pinned')
})

test('returning to the file browser after rollback reloads the current files', async t => {
  const { api, state } = await setup(t, 'SkillBrowser')
  state.selected = 'SKILL.md'
  state.content = '# Old'
  t.mock.method(api, 'skillFiles', async () => [{ path: 'SKILL.md', size: 9 }])
  t.mock.method(api, 'skillFile', async () => ({ blob: new Blob(['# Current']) }))
  state.versionChanged()
  await state.setTab('overview')
  assert.equal(state.content, '# Current')
})
