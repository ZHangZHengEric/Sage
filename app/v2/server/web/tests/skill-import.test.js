import assert from 'node:assert/strict'
import { test } from 'node:test'
import { createRenderer, nextTick, ssrContextKey } from 'vue'
import { createServer } from 'vite'

async function setup(t) {
  const server = await createServer({ optimizeDeps: { noDiscovery: true, include: [] }, server: { middlewareMode: true, watch: null, hmr: false, ws: false } })
  t.after(() => server.close())
  const { api } = await server.ssrLoadModule('/src/api.js')
  t.mock.method(api, 'listSkills', async () => [])
  t.mock.method(api, 'agentSummaries', async () => [])
  const { default: Component } = await server.ssrLoadModule('/src/views/Skills.vue')
  const renderer = createRenderer({ createComment: () => ({}), insert() {}, remove() {}, parentNode: () => null, nextSibling: () => null })
  const app = renderer.createApp({ ...Component, render: () => null })
  app.provide(ssrContextKey, {})
  const vm = app.mount({})
  t.after(() => app.unmount())
  await new Promise(resolve => setImmediate(resolve))
  return { api, state: vm.$.setupState }
}

test('online ZIP previews then imports only selected skills and explicit overwrites', async t => {
  const { api, state } = await setup(t)
  t.mock.method(api, 'previewSkillImport', async source => {
    assert.equal(source.kind, 'zip_url')
    assert.equal(source.value, 'https://example.test/skills.zip')
    return { revision: 'a'.repeat(64), candidates: [
      { path: 'one', name: 'one', package_sha256: 'hash1', expected_version_id: '', status: 'new' },
      { path: 'two', name: 'two', package_sha256: 'hash2', expected_version_id: 'v1', status: 'conflict' },
    ] }
  })
  t.mock.method(api, 'importSkills', async body => {
    assert.deepEqual(body.items.map(item => [item.path, item.overwrite]), [['two', true]])
    assert.equal(body.revision, 'a'.repeat(64))
    return { success_count: 1, failed_count: 0, results: [{ filename: 'two', success: true, message: 'Imported' }] }
  })
  state.importMode = 'zip_url'
  state.remoteInputs.zip_url = 'https://example.test/skills.zip'
  await nextTick()
  await state.previewRemote()
  assert.deepEqual(state.selectedPaths, ['one'])
  state.selectedPaths = ['two']
  state.overwritePaths = ['two']
  await state.importRemote()
  assert.equal(state.results[0].success, true)
  assert.equal(state.pending, false)
})

test('changing a CLI command invalidates preview and ignores an obsolete response', async t => {
  const { api, state } = await setup(t)
  let finish
  t.mock.method(api, 'previewSkillImport', () => new Promise(resolve => { finish = resolve }))
  state.importMode = 'skills_cli'
  state.remoteInputs.skills_cli = 'npx skills add owner/repo'
  await nextTick()
  const request = state.previewRemote()
  state.remoteInputs.skills_cli = 'npx skills add owner/other'
  await nextTick()
  finish({ revision: 'a'.repeat(40), candidates: [{ path: 'old', status: 'new' }] })
  await request
  assert.equal(state.remotePreview, null)
  assert.deepEqual(state.selectedPaths, [])
  assert.equal(state.pending, false)
})

test('remote partial failure retains selection and input for retry', async t => {
  const { api, state } = await setup(t)
  t.mock.method(api, 'previewSkillImport', async () => ({ revision: 'a'.repeat(40), candidates: [
    { path: 'one', name: 'one', status: 'new' }, { path: 'two', name: 'two', status: 'new' },
  ] }))
  t.mock.method(api, 'importSkills', async () => ({ success_count: 1, failed_count: 1, results: [
    { filename: 'one', success: true }, { filename: 'two', success: false, message: 'Conflict' },
  ] }))
  state.importMode = 'skills_cli'
  state.remoteInputs.skills_cli = 'npx skills add owner/repo'
  await nextTick()
  await state.previewRemote()
  await state.importRemote()
  assert.deepEqual(state.selectedPaths, ['two'])
  assert.equal(state.remoteInputs.skills_cli, 'npx skills add owner/repo')
  assert.equal(state.results[1].message, 'Conflict')
  assert.equal(state.error, '1 个成功，1 个失败')
})
