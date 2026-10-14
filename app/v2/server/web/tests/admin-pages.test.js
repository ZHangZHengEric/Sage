import assert from 'node:assert/strict'
import { test } from 'node:test'
import { createRenderer, nextTick, ssrContextKey } from 'vue'
import { createServer } from 'vite'

async function setup(t, name) {
  const server = await createServer({ server: { middlewareMode: true, watch: null, hmr: false, ws: false } })
  t.after(() => server.close())
  const previous = Object.getOwnPropertyDescriptor(globalThis, 'localStorage')
  Object.defineProperty(globalThis, 'localStorage', { configurable: true, value: {
    getItem: key => key.endsWith('.user') ? JSON.stringify({ user_id: 'admin', role: 'admin' }) : '', setItem() {},
  } })
  t.after(() => {
    if (previous) Object.defineProperty(globalThis, 'localStorage', previous)
    else delete globalThis.localStorage
  })
  const { api } = await server.ssrLoadModule('/src/api.js')
  const { default: Component } = await server.ssrLoadModule(`/src/views/${name}.vue`)
  return { api, mount: async () => {
    const renderer = createRenderer({ createComment: () => ({}), insert() {}, remove() {}, parentNode: () => null, nextSibling: () => null })
    const app = renderer.createApp({ ...Component, render: () => null })
    app.provide(ssrContextKey, {})
    const vm = app.mount({})
    t.after(() => app.unmount())
    await new Promise(resolve => setImmediate(resolve)); await nextTick()
    return vm.$.setupState
  } }
}

test('admin opens foreign chat pages read-only and new conversations use own agent', async t => {
  const { api, mount } = await setup(t, 'Chat')
  const owner = { user_id: 'alice', username: 'alice' }
  t.mock.method(api, 'listThreads', async () => [{ thread_id: 'foreign', agent_id: 'alice-agent', _owner: owner }])
  t.mock.method(api, 'listAgents', async all => { assert.equal(all, false); return [{ id: 'own-agent' }] })
  t.mock.method(api, 'listModels', async () => [])
  t.mock.method(api, 'threadEvents', async (id, limit, actualOwner, offset) => {
    assert.equal(id, 'foreign'); assert.equal(actualOwner.user_id, 'alice')
    return { events: [], offset, limit, total: 1001 }
  })
  const state = await mount()
  assert.equal(state.readOnly, true)
  assert.equal(state.historyOffset, 500)
  await state.loadHistory(); await state.loadHistory()
  assert.equal(state.historyOffset, 1500)
  assert.deepEqual(api.threadEvents.mock.calls.map(call => call.arguments[3]), [0, 500, 1000])
  state.text = 'must not send as Alice'
  await state.send()
  assert.equal(state.text, 'must not send as Alice')
  state.startNew()
  assert.equal(state.readOnly, false)
  assert.equal(state.selectedAgentId, 'own-agent')
  assert.equal(state.historyTotal, 0)
})

test('Studio reads identical operation names using the selected owner and resets event history', async t => {
  const { api, mount } = await setup(t, 'Studio')
  const bundle = { manifest: { entrypoint: { agent: 'assistant' }, agents: { assistant: {} } } }
  for (const method of ['packages', 'packageRuns', 'listAgents']) t.mock.method(api, method, async () => [])
  t.mock.method(api, 'packageSchema', async () => ({}))
  t.mock.method(api, 'packageTemplate', async () => bundle)
  t.mock.method(api, 'package', async () => bundle)
  t.mock.method(api, 'packageRun', async (op, owner) => ({ terminal: true, owner: owner.user_id }))
  t.mock.method(api, 'packageEvents', async (op, cursor, owner) => ({ events: [{ event_id: owner.user_id }], cursor: cursor + 1 }))
  const state = await mount()
  await state.inspect('same', { user_id: 'alice' })
  await state.inspect('same', { user_id: 'bob' })
  assert.equal(state.foreignRun, true)
  assert.equal(state.status.owner, 'bob')
  assert.deepEqual(state.events.map(event => event.event_id), ['bob'])
  assert.deepEqual(api.packageEvents.mock.calls.map(call => call.arguments[1]), [0, 0])
  await state.load({ ref: 'shared-ref', _owner: { user_id: 'alice' } })
  assert.equal(state.foreignBundle, true)
  assert.equal(api.package.mock.calls[0].arguments[1].user_id, 'alice')
})

test('agent detail reads the selected owner and keeps foreign configurations read-only', async t => {
  const { api, mount } = await setup(t, 'Agents')
  const owner = { user_id: 'alice', username: 'alice' }
  const agent = { id: 'agent-1', name: 'Alice agent', description: '', instructions: 'Instructions', tools: ['file_read'], model_id: 'alice-model', _owner: owner }
  for (const method of ['listModels', 'listMcp', 'listA2aAgents', 'listSkills', 'listTools']) t.mock.method(api, method, async () => [])
  t.mock.method(api, 'listAgents', async () => [agent])
  t.mock.method(api, 'getAgent', async (id, actualOwner) => { assert.equal(actualOwner.user_id, 'alice'); return agent })
  t.mock.method(api, 'listAgentSkills', async (id, actualOwner) => { assert.equal(actualOwner.user_id, 'alice'); return [{ name: 'research' }] })
  t.mock.method(api, 'updateAgent', async () => { throw new Error('foreign write') })
  const state = await mount()
  await state.openAgent(agent)
  assert.equal(state.drawerOpen, true)
  assert.equal(state.viewOnly, true)
  assert.equal(state.form.instructions, 'Instructions')
  assert.deepEqual(state.selectedSkills, ['research'])
  state.enableEdit()
  await state.save(false)
  assert.equal(state.viewOnly, true)
  assert.equal(api.updateAgent.mock.calls.length, 0)
})

test('agent editor saves V2 fields and selected skills before staying open or exiting', async t => {
  const { api, mount } = await setup(t, 'Agents')
  for (const method of ['listAgents', 'listModels', 'listMcp', 'listA2aAgents', 'listSkills', 'listTools', 'listAgentSkills']) t.mock.method(api, method, async () => [])
  t.mock.method(api, 'createAgent', async body => ({ ...body, id: 'new-agent' }))
  t.mock.method(api, 'updateAgent', async (id, body) => ({ ...body, id }))
  t.mock.method(api, 'bindAgentSkills', async () => [])
  const state = await mount()
  state.startNew()
  state.form.name = 'New agent'
  state.form.tools = ['file_read']
  state.selectedSkills = ['research']
  await state.save(false)
  assert.equal(state.drawerOpen, true)
  assert.equal(state.editing, 'new-agent')
  assert.deepEqual(api.bindAgentSkills.mock.calls[0].arguments, ['new-agent', ['research']])
  assert.deepEqual(Object.keys(api.createAgent.mock.calls[0].arguments[0]).sort(), ['description', 'execution_policy', 'instructions', 'model_id', 'name', 'tools'])
  await state.save(true)
  assert.equal(state.drawerOpen, false)
  assert.equal(api.createAgent.mock.calls.length, 1)
  assert.equal(api.updateAgent.mock.calls.length, 1)
})

test('skills without a source category are searchable and foreign names cannot be bound', async t => {
  const { api, mount } = await setup(t, 'Skills')
  const own = { skill_id: 'own', name: 'demo', description: 'Own skill', _owner: { user_id: 'admin' } }
  const foreign = { skill_id: 'foreign', name: 'demo', description: 'Foreign skill', _owner: { user_id: 'alice' } }
  t.mock.method(api, 'listSkills', async () => [own, foreign])
  t.mock.method(api, 'listAgents', async () => [{ id: 'own-agent', name: 'My agent' }])
  t.mock.method(api, 'listAgentSkills', async () => [])
  t.mock.method(api, 'bindAgentSkills', async () => [])
  const state = await mount()
  assert.equal(state.visibleSkills.length, 2)
  state.search = 'own skill'
  assert.deepEqual(state.visibleSkills.map(skill => skill.skill_id), ['own'])
  await state.toggleBind(foreign)
  assert.equal(api.bindAgentSkills.mock.calls.length, 0)
  await state.toggleBind(own)
  assert.deepEqual(api.bindAgentSkills.mock.calls[0].arguments, ['own-agent', ['demo']])
})
