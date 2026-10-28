import assert from 'node:assert/strict'
import { test } from 'node:test'
import { createRenderer, createSSRApp, nextTick, ssrContextKey } from 'vue'
import { renderToString } from 'vue/server-renderer'
import { routerKey } from 'vue-router'
import { createServer } from 'vite'

const editorResources = (overrides = {}) => ({ models: [], skills: [], tools: [], external_tools: [], plugins: { configurable: [] }, ...overrides })

test('agent skill sync uses saved bindings and prevents duplicate requests', async t => {
  const { api, mount } = await setup(t, 'Agents')
  const agent = { id: 'writer', name: 'Writer', instructions: 'Saved prompt', skills: ['guide'] }
  t.mock.method(api, 'agentSummaries', async () => [agent])
  t.mock.method(api, 'agentEditorResources', async () => editorResources())
  t.mock.method(api, 'getAgent', async () => agent)
  let finish
  t.mock.method(api, 'syncAgentSkills', () => new Promise(resolve => { finish = resolve }))
  const state = await mount()
  await state.openAgent(agent, false)
  await new Promise(done => setImmediate(done))
  state.form.instructions = 'Unsaved prompt'
  await state.syncSkills()
  assert.equal(api.syncAgentSkills.mock.callCount(), 0)
  state.form.instructions = 'Saved prompt'
  const pending = state.syncSkills()
  await state.syncSkills()
  assert.equal(api.syncAgentSkills.mock.callCount(), 1)
  assert.deepEqual(api.syncAgentSkills.mock.calls[0].arguments, ['writer'])
  assert.equal(state.syncingSkills, true)
  finish({ success_count: 1, failed_count: 0, results: [{ name: 'guide', success: true, workspaces: 1 }] })
  await pending
  assert.equal(state.syncingSkills, false)
  assert.match(state.savedMessage, /同步完成/)
  assert.equal(state.form.instructions, 'Saved prompt')
  assert.deepEqual(state.selectedSkills, ['guide'])
})

test('agent skill sync button reflects saved, dirty, loading and readonly states', async t => {
  const { Component } = await setup(t, 'AgentEditor', 'components')
  const props = { form: { name: 'Writer' }, savedForm: { name: 'Writer' }, agentId: 'writer', selectedSkills: ['guide'], savedSkills: ['guide'] }
  const render = overrides => renderToString(createSSRApp(Component, { ...props, ...overrides }))
  assert.match(await render({}), /<button[^>]*>Agent 技能同步<\/button>/)
  assert.match(await render({ form: { name: 'Changed' } }), /<button[^>]*disabled[^>]*>Agent 技能同步<\/button>/)
  assert.match(await render({ syncingSkills: true }), /同步中…/)
  assert.doesNotMatch(await render({ readonly: true }), /Agent 技能同步/)
})

test('ordinary agent settings roundtrip mode and members and scope choices to the owner', async t => {
  const { api, mount } = await setup(t, 'Agents')
  const agent = { id: 'director', name: 'Director', agent_mode: 'team', available_sub_agent_ids: ['writer'] }
  t.mock.method(api, 'agentSummaries', async () => [agent, { id: 'writer', name: 'Writer' }, { id: 'foreign', name: 'Foreign', _owner: { user_id: 'alice' } }])
  t.mock.method(api, 'agentEditorResources', async () => editorResources())
  t.mock.method(api, 'getAgent', async () => agent)
  t.mock.method(api, 'updateAgent', async (id, body) => ({ ...body, id }))
  t.mock.method(api, 'bindAgentSkills', async () => [])
  const state = await mount()
  await state.openAgent(agent, false)
  await new Promise(done => setImmediate(done))
  assert.equal(state.form.agent_mode, 'team')
  assert.deepEqual(state.form.available_sub_agent_ids, ['writer'])
  assert.deepEqual(state.memberAgents.map(item => item.id), ['writer'])
  state.form.agent_mode = 'fibre'
  await state.save(false)
  assert.equal(api.updateAgent.mock.calls[0].arguments[1].agent_mode, 'fibre')
  assert.deepEqual(api.updateAgent.mock.calls[0].arguments[1].available_sub_agent_ids, ['writer'])
  await state.startNew()
  assert.equal(state.form.agent_mode, 'simple')
  assert.deepEqual(state.form.available_sub_agent_ids, [])
})

test('agent mode controls render members for team and fibre and respect readonly settings', async t => {
  const { Component } = await setup(t, 'AgentEditor', 'components')
  for (const agent_mode of ['simple', 'fibre', 'team']) {
    const html = await renderToString(createSSRApp(Component, {
      form: { name: 'Director', agent_mode, available_sub_agent_ids: ['writer'] },
      memberAgents: [{ id: 'writer', name: 'Writer' }], agentId: 'director', readonly: true,
    }))
    assert.match(html, /aria-label="运行模式"/)
    assert.match(html, /Simple/); assert.match(html, /Fibre/); assert.match(html, /Team/)
    assert.equal(html.includes('可用成员'), agent_mode !== 'simple')
    if (agent_mode !== 'simple') assert.match(html, /Writer/)
    assert.doesNotMatch(html, /选择成员<\/button>/)
  }
})

async function setup(t, name, directory = 'views') {
  const server = await createServer({ optimizeDeps: { noDiscovery: true, include: [] }, server: { middlewareMode: true, watch: null, hmr: false, ws: false } })
  t.after(() => server.close())
  const previous = Object.getOwnPropertyDescriptor(globalThis, 'localStorage')
  Object.defineProperty(globalThis, 'localStorage', { configurable: true, value: {
    getItem: key => key.endsWith('.user') ? JSON.stringify({ user_id: 'admin', role: 'admin' }) : '', setItem() {},
  } })
  t.after(() => {
    if (previous) Object.defineProperty(globalThis, 'localStorage', previous)
    else delete globalThis.localStorage
  })
  const navigation = { push: t.mock.fn(async () => {}), replace: t.mock.fn(async () => {}) }
  const { api } = await server.ssrLoadModule('/src/api.js')
  const { default: Component } = await server.ssrLoadModule(`/src/${directory}/${name}.vue`)
  return { api, navigation, Component, mount: async (props = {}) => {
    const renderer = createRenderer({ createComment: () => ({}), insert() {}, remove() {}, parentNode: () => null, nextSibling: () => null })
    const app = renderer.createApp({ ...Component, render: () => null }, props)
    app.provide(ssrContextKey, {})
    app.provide(routerKey, navigation)
    const vm = app.mount({})
    t.after(() => app.unmount())
    await new Promise(resolve => setImmediate(resolve)); await nextTick()
    return vm.$.setupState
  } }
}

test('IM self-service creation loads only own Agents and never submits an owner or env reference', async t => {
  const { api, mount } = await setup(t, 'FeishuConnectionForm', 'components')
  t.mock.method(api, 'agentSummaries', async all => { assert.equal(all, false); return [{ id: 'own', name: 'Own' }] })
  t.mock.method(api, 'adminUsers', async () => { throw Error('admin request forbidden') })
  t.mock.method(api, 'createIMConnection', async body => ({ id: 'created', ...body }))
  const state = await mount({ modelValue: true })
  assert.equal(state.form.agent_id, 'own')
  state.form.name = 'Mine'
  state.form.config = { app_id: 'cli_own', tenant_key: 'tenant', app_secret: 'test-secret', verification_token: 'test-token', encrypt_key: 'test-key' }
  await state.save()
  const body = api.createIMConnection.mock.calls[0].arguments[0]
  assert.equal(Object.hasOwn(body, 'owner_user_id'), false)
  assert.equal(Object.hasOwn(body.config, 'app_secret_env'), false)
  assert.equal(body.agent_id, 'own')
  assert.equal(api.adminUsers.mock.calls.length, 0)
})

for (const operation of ['created', 'removed', 'changed']) {
  test(`IM list refresh cannot overwrite a connection that was ${operation} while loading`, async t => {
    const { api, mount } = await setup(t, 'FeishuConnections', 'components')
    const old = { id: 'old', owner_user_id: 'admin', revision: 1, paired: false, enabled: true }
    t.mock.method(api, 'imConnections', async () => ({ items: [old] }))
    const state = await mount()
    let finish
    api.imConnections.mock.mockImplementation(() => new Promise(resolve => { finish = resolve }))
    const pending = state.load()
    const added = { ...old, id: 'new' }, updated = { ...old, revision: 2, enabled: false }
    state[operation](operation === 'created' ? added : operation === 'removed' ? old.id : updated)
    finish({ items: [old] })
    await pending
    assert.deepEqual(state.connections, operation === 'created' ? [old, added] : operation === 'removed' ? [] : [updated])
    assert.equal(state.loading, false)
    if (operation !== 'changed') assert.equal(state.selected, operation === 'created' ? 'new' : '')
  })
}

test('probe report distinguishes strict Schema support from JSON output and real errors', async t => {
  const { Component } = await setup(t, 'CapabilityReport', 'components')
  const profile = { effective_max_output_tokens: 128, verified_at: '2026-10-19T00:00:00Z', outcomes: [
    { name: 'structured_output', status: 'unsupported', error: 'This response_format type is unavailable now' },
    { name: 'json_object', status: 'supported' },
  ] }
  const html = await renderToString(createSSRApp(Component, { profile }))
  assert.match(html, /严格 Schema 输出/)
  assert.match(html, /JSON 输出/)
  assert.match(html, /不支持/)
  assert.doesNotMatch(html, /探测失败|class="[^"]*error/)
  assert.match(html, /This response_format type is unavailable now/)
  const errorHtml = await renderToString(createSSRApp(Component, { profile: { ...profile, outcomes: [
    { name: 'structured_output', status: 'error', error: 'Authentication failed' },
  ] } }))
  assert.match(errorHtml, /探测失败/)
  assert.match(errorHtml, /class="[^"]*error/)
})

test('model cards show verified output capabilities separately while retaining the combined switch', async t => {
  const { api, mount } = await setup(t, 'Models')
  const model = { id: 'json-only', capabilities: { structured_output: true }, capability_profile: { outcomes: [
    { name: 'structured_output', status: 'unsupported' }, { name: 'json_object', status: 'supported' },
  ] } }
  t.mock.method(api, 'listModels', async () => [model])
  const state = await mount()
  assert.deepEqual(state.visibleModels[0].labels, ['JSON 输出'])
  assert.equal(state.visibleModels[0].probe.state, 'checked')
  state.models[0].capability_profile.outcomes[0].status = 'supported'
  assert.deepEqual(state.visibleModels[0].labels, ['严格 Schema 输出', 'JSON 输出'])
  state.models[0].capability_profile = null
  assert.deepEqual(state.visibleModels[0].labels, ['JSON / Schema 输出'])
})

test('admin opens foreign chat pages read-only and new conversations use own agent', async t => {
  const { api, mount } = await setup(t, 'Chat')
  const owner = { user_id: 'alice', username: 'alice' }
  t.mock.method(api, 'listThreads', async () => ({ items: [{ thread_id: 'foreign', agent_id: 'alice-agent', _owner: owner }], next_cursor: null }))
  t.mock.method(api, 'listAgents', async all => { assert.equal(all, false); return [{ id: 'own-agent' }] })
  t.mock.method(api, 'listModels', async () => [])
  t.mock.method(api, 'threadEvents', async (id, limit, actualOwner, offset) => {
    assert.equal(id, 'foreign'); assert.equal(actualOwner.user_id, 'alice')
    return { events: [], offset, limit, total: 1001 }
  })
  const state = await mount()
  assert.equal(state.readOnly, true)
  assert.equal(state.workspaceThreadId, 'foreign')
  assert.equal(state.historyOffset, 500)
  await state.loadHistory(); await state.loadHistory()
  assert.equal(state.historyOffset, 1500)
  assert.deepEqual(api.threadEvents.mock.calls.map(call => call.arguments[3]), [0, 500, 1000])
  state.text = 'must not send as Alice'
  await state.send()
  assert.equal(state.text, 'must not send as Alice')
  state.startNew()
  assert.equal(state.workspaceThreadId, '')
  assert.equal(state.readOnly, false)
  assert.equal(state.selectedAgentId, 'own-agent')
  assert.equal(state.historyTotal, 0)
})

test('model detail keeps another owner read-only across all mutation actions', async t => {
  const { api, mount } = await setup(t, 'Models')
  const owner = { user_id: 'alice', username: 'Alice' }
  const model = { id: 'foreign', model: 'Alice model', protocol: 'openai-responses', base_url: 'https://example.test/v1', _owner: owner }
  t.mock.method(api, 'listModels', async () => [model])
  t.mock.method(api, 'getModel', async (id, actualOwner) => {
    assert.equal(id, model.id); assert.equal(actualOwner.user_id, owner.user_id)
    return { ...model, api_key: 'test-key' }
  })
  for (const name of ['saveModel', 'deleteModel', 'probeModel']) t.mock.method(api, name, async () => { throw new Error('foreign mutation') })
  const state = await mount()
  await state.openModel(model, false)
  assert.equal(state.viewOnly, true)
  await state.save(); await state.probe(); await state.makeCurrent(model); await state.remove(model)
  for (const name of ['saveModel', 'deleteModel', 'probeModel']) assert.equal(api[name].mock.calls.length, 0)
})

test('model default selection preserves configured request, limits and capability profile', async t => {
  const { api, mount } = await setup(t, 'Models')
  const model = { id: 'own', model: 'Model', protocol: 'openai-responses', base_url: 'https://example.test/v1',
    request: { temperature: 0.4, max_output_tokens: 1024, extra: { custom: true } }, limits: { context_window: 32000 },
    capabilities: { tool_calling: true }, capability_profile: { outcomes: [] } }
  t.mock.method(api, 'listModels', async () => [model])
  t.mock.method(api, 'saveModel', async () => ({}))
  const state = await mount()
  await state.makeCurrent(model)
  const saved = api.saveModel.mock.calls[0].arguments[0]
  for (const field of ['request', 'limits', 'capabilities', 'capability_profile']) assert.deepEqual(saved[field], model[field])
  assert.equal(saved.is_default, true)
  assert.equal(saved.api_key, '')
  assert.equal(state.pending, false)
  api.saveModel.mock.mockImplementation(async () => { throw new Error('Connection lost') })
  await state.makeCurrent(model)
  assert.equal(state.error, 'Connection lost')
  assert.equal(state.pending, false)
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

test('agent list defers one aggregated editor catalog request and reuses it', async t => {
  const { api, mount } = await setup(t, 'Agents')
  t.mock.method(globalThis, 'fetch', async url => Response.json({ data:
    url.startsWith('/api/agents/editor-resources') ? { models: [], skills: [], tools: [], external_tools: [], plugins: { configurable: [] } } : [],
  }))
  const state = await mount()
  assert.deepEqual(fetch.mock.calls.map(call => call.arguments[0]), ['/api/admin/agents'])
  await state.startNew()
  assert.equal(state.drawerOpen, true)
  assert.equal(fetch.mock.calls.length, 2)
  assert.match(fetch.mock.calls[1].arguments[0], /^\/api\/agents\/editor-resources/)
  await state.startNew()
  assert.equal(fetch.mock.calls.length, 2)
})

test('agent editor catalog failures leave the list usable and can be retried', async t => {
  const { api, mount } = await setup(t, 'Agents')
  t.mock.method(api, 'agentSummaries', async () => [{ id: 'own' }])
  t.mock.method(api, 'agentEditorResources', async () => { throw new Error('Catalog unavailable') })
  const state = await mount()
  assert.equal(state.loading, false)
  assert.equal(state.error, '')
  await state.startNew()
  assert.equal(state.drawerOpen, false)
  assert.equal(state.pending, false)
  assert.equal(state.error, 'Catalog unavailable')
  assert.equal(state.agents.length, 1)
  api.agentEditorResources.mock.mockImplementation(async () => editorResources())
  await state.startNew()
  assert.equal(state.drawerOpen, true)
  assert.equal(state.error, '')
})

test('PluginConfig reuses a supplied catalog instead of requesting it again', async t => {
  const { api, mount } = await setup(t, 'PluginConfig', 'components')
  t.mock.method(api, 'listPlugins', async () => { throw new Error('duplicate catalog request') })
  const catalogData = { configurable: [], plugins: [], defaults: {} }
  const state = await mount({ catalogData })
  assert.equal(state.error, '')
  assert.deepEqual(state.catalog, catalogData)
  assert.equal(api.listPlugins.mock.calls.length, 0)
})

test('agent detail reads the selected owner and keeps foreign configurations read-only', async t => {
  const { api, mount } = await setup(t, 'Agents')
  t.mock.method(api, 'agentEditorResources', async actualOwner => { assert.equal(actualOwner.user_id, 'alice'); return editorResources({ skills: [{ name: 'research' }] }) })
  const owner = { user_id: 'alice', username: 'alice' }
  const agent = { id: 'agent-1', name: 'Alice agent', description: '', instructions: 'Instructions', tools: ['file_read'], model_id: 'alice-model', skills: ['research'], _owner: owner }
  t.mock.method(api, 'agentSummaries', async () => [agent])
  t.mock.method(api, 'getAgent', async (id, actualOwner) => { assert.equal(actualOwner.user_id, 'alice'); return agent })
  t.mock.method(api, 'listAgentSkills', async () => { throw new Error('redundant bindings request') })
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

test('agent detail opens before slow resources and ignores closed editor results', async t => {
  const { api, mount } = await setup(t, 'Agents')
  t.mock.method(api, 'agentSummaries', async () => [])
  const agent = { id: 'slow', name: 'Readable immediately', skills: ['bound'], tools: [] }
  t.mock.method(api, 'getAgent', async () => agent)
  let resolve
  t.mock.method(api, 'agentEditorResources', () => new Promise(done => { resolve = done }))
  t.mock.method(api, 'listAgentSkills', async () => { throw new Error('redundant request') })
  t.mock.method(api, 'updateAgent', async () => { throw new Error('save before resources') })
  const state = await mount()
  await state.openAgent(agent, false)
  assert.equal(state.drawerOpen, true)
  assert.equal(state.resourcesLoading, true)
  assert.equal(state.form.name, 'Readable immediately')
  assert.deepEqual(state.selectedSkills, ['bound'])
  await state.save(false)
  assert.equal(api.updateAgent.mock.calls.length, 0)
  state.closeEditor()
  resolve(editorResources({ models: [{ id: 'stale' }] }))
  await new Promise(done => setImmediate(done))
  assert.deepEqual(state.models, [])
  assert.equal(state.drawerOpen, false)
})

test('failed editor resources retain detail and basic edits through retry', async t => {
  const { api, mount } = await setup(t, 'Agents')
  t.mock.method(api, 'agentSummaries', async () => [])
  t.mock.method(api, 'getAgent', async () => ({ id: 'own', name: 'Original', tools: [] }))
  t.mock.method(api, 'agentEditorResources', async () => { throw new Error('Resources unavailable') })
  const state = await mount()
  await state.openAgent({ id: 'own' }, false)
  await new Promise(done => setImmediate(done))
  assert.equal(state.drawerOpen, true)
  assert.equal(state.resourcesError, 'Resources unavailable')
  state.form.name = 'Edited while loading'
  api.agentEditorResources.mock.mockImplementation(async () => editorResources())
  await state.retryResources()
  assert.equal(state.resourcesError, '')
  assert.equal(state.form.name, 'Edited while loading')
  assert.equal(state.savedForm.name, 'Original')
})

test('switching owners isolates resources and loads real approval metadata only on demand', async t => {
  const { api, mount } = await setup(t, 'Agents')
  t.mock.method(api, 'agentSummaries', async () => [])
  t.mock.method(api, 'getAgent', async id => ({ id, name: id, tools: [] }))
  let resolveAlice
  t.mock.method(api, 'agentEditorResources', owner => owner.user_id === 'alice'
    ? new Promise(done => { resolveAlice = done })
    : Promise.resolve(editorResources({ models: [{ id: 'bob-model' }] })))
  t.mock.method(api, 'agentApprovalTools', async owner => {
    assert.equal(owner.user_id, 'bob')
    return [{ name: 'mcp_notes_read', approval_key: 'mcp:notes:read.remote' }]
  })
  const state = await mount()
  await state.openAgent({ id: 'alice-agent', _owner: { user_id: 'alice' } })
  state.closeEditor()
  await state.openAgent({ id: 'bob-agent', _owner: { user_id: 'bob' } })
  await new Promise(done => setImmediate(done))
  assert.deepEqual(state.models.map(item => item.id), ['bob-model'])
  resolveAlice(editorResources({ models: [{ id: 'alice-model' }] }))
  await new Promise(done => setImmediate(done))
  assert.deepEqual(state.models.map(item => item.id), ['bob-model'])
  assert.equal(api.agentApprovalTools.mock.calls.length, 0)
  await state.loadApprovalTools()
  await state.loadApprovalTools()
  assert.equal(api.agentApprovalTools.mock.calls.length, 1)
  assert.equal(state.officialTools[0].approval_key, 'mcp:notes:read.remote')
})

test('agent editor saves V2 fields and selected skills before staying open or exiting', async t => {
  const { api, mount } = await setup(t, 'Agents')
  t.mock.method(api, 'agentEditorResources', async () => editorResources({ plugins: { configurable: ['context.summarizer'] } }))
  t.mock.method(api, 'agentSummaries', async () => [])
  t.mock.method(api, 'createAgent', async body => ({ ...body, id: 'new-agent' }))
  t.mock.method(api, 'updateAgent', async (id, body) => ({ ...body, id }))
  t.mock.method(api, 'bindAgentSkills', async () => [])
  const state = await mount()
  await state.startNew()
  state.form.name = 'New agent'
  state.form.tools = ['file_read']
  state.form.tool_approval.tools = { file_read: 'ask', 'mcp:drive:write': 'auto_approve' }
  state.selectedSkills = ['research']
  await state.save(false)
  assert.equal(state.drawerOpen, true)
  assert.equal(state.editing, 'new-agent')
  assert.deepEqual(api.bindAgentSkills.mock.calls[0].arguments, ['new-agent', ['research']])
  assert.deepEqual(Object.keys(api.createAgent.mock.calls[0].arguments[0]).sort(), ['agent_mode', 'available_sub_agent_ids', 'budgets', 'description', 'execution_policy', 'external_tools', 'fast_model_id', 'instructions', 'memory', 'model_id', 'name', 'plugins', 'sandbox', 'tool_approval', 'tools'])
  assert.deepEqual(api.createAgent.mock.calls[0].arguments[0].tool_approval, { default: 'auto_approve', tools: { file_read: 'ask', 'mcp:drive:write': 'auto_approve' } })
  await state.save(true)
  assert.equal(state.drawerOpen, false)
  assert.equal(api.createAgent.mock.calls.length, 1)
  assert.equal(api.updateAgent.mock.calls.length, 1)
})

test('skills are searchable and can be filtered by agent without changing bindings', async t => {
  const { api, mount } = await setup(t, 'Skills')
  const own = { skill_id: 'own', name: 'demo', description: 'Own skill', _owner: { user_id: 'admin' } }
  const foreign = { skill_id: 'foreign', name: 'demo', description: 'Foreign skill', _owner: { user_id: 'alice' } }
  t.mock.method(api, 'listSkills', async () => [own, foreign])
  t.mock.method(api, 'agentSummaries', async all => { assert.equal(all, false); return [{ id: 'own-agent', name: 'My agent' }] })
  t.mock.method(api, 'listAgentSkills', async () => [own])
  t.mock.method(api, 'bindAgentSkills', async () => { throw new Error('must not change bindings') })
  const state = await mount()
  assert.equal(state.visibleSkills.length, 2)
  state.search = 'own skill'
  assert.deepEqual(state.visibleSkills.map(skill => skill.skill_id), ['own'])
  state.search = ''
  state.filterAgentId = 'own-agent'
  await state.changeAgent()
  assert.deepEqual(state.visibleSkills.map(skill => skill.skill_id), ['own'])
  assert.equal(api.bindAgentSkills.mock.calls.length, 0)
  state.filterAgentId = ''
  await state.changeAgent()
  assert.equal(state.visibleSkills.length, 2)
})

test('skill browser opens every nested file and reads text and binary content', async t => {
  const { api, mount } = await setup(t, 'SkillBrowser', 'components')
  t.mock.method(api, 'skillFiles', async () => [
    { path: 'SKILL.md', size: 8 },
    { path: 'references/guide.txt', size: 5 },
    { path: 'assets/raw.bin', size: 3 },
  ])
  t.mock.method(api, 'skillFile', async (id, path) => ({
    blob: new Blob([path === 'SKILL.md' ? '# Skill\n' : path.endsWith('.txt') ? 'guide' : new Uint8Array([0, 1, 255])]),
  }))
  const state = await mount({ item: { skill_id: 'writer', name: 'writer' } })
  await state.inspect()
  assert.equal(state.selected, 'SKILL.md')
  assert.deepEqual(state.tree.filter(entry => entry.folder).map(entry => entry.path), ['assets', 'references'])
  await state.selectFile('references/guide.txt')
  assert.equal(state.content, 'guide')
  await state.selectFile('assets/raw.bin')
  assert.equal(state.kind, 'binary')
  assert.match(state.hexRows[0], /00 01 ff/)
})

test('skill overview returns to SKILL.md and closing ignores outstanding file reads', async t => {
  const { api, mount } = await setup(t, 'SkillBrowser', 'components')
  t.mock.method(api, 'skillFiles', async () => [{ path: 'SKILL.md', size: 10 }, { path: 'scripts/example.py', size: 12 }])
  t.mock.method(api, 'skillFile', async (id, path) => ({ blob: new Blob([path === 'SKILL.md' ? '# Overview' : 'print(1)']) }))
  const state = await mount({ item: { skill_id: 'writer', name: 'writer' } })
  await state.inspect()
  await state.setTab('files'); await state.selectFile('scripts/example.py')
  await state.setTab('overview')
  assert.equal(state.selected, 'SKILL.md')
  assert.equal(state.content, '# Overview')
  let finish
  api.skillFile.mock.mockImplementation(() => new Promise(resolve => { finish = resolve }))
  const reading = state.selectFile('scripts/example.py')
  state.close(); finish({ blob: new Blob(['late result']) }); await reading
  assert.equal(state.open, false)
  assert.equal(state.content, '')
})

test('skill import preserves failed files for retry', async t => {
  const { api, mount } = await setup(t, 'Skills')
  t.mock.method(api, 'listSkills', async () => [])
  t.mock.method(api, 'agentSummaries', async () => [])
  t.mock.method(api, 'uploadSkills', async () => ({ success_count: 1, failed_count: 1, results: [
    { filename: 'good.zip', success: true, message: 'Imported' }, { filename: 'bad.zip', success: false, message: 'Missing SKILL.md' },
  ] }))
  const state = await mount()
  state.addFiles([{ name: 'good.zip', size: 12 }, { name: 'bad.zip', size: 15 }])
  await state.upload()
  assert.deepEqual(state.files.map(file => file.name), ['bad.zip'])
  assert.equal(state.results.length, 2)
  assert.equal(state.pending, false)
})

test('skill browser blocks deletion of another owner even for an admin viewer', async t => {
  const { api, mount } = await setup(t, 'SkillBrowser', 'components')
  t.mock.method(api, 'deleteSkill', async () => { throw new Error('foreign delete') })
  const state = await mount({ item: { skill_id: 'other', name: 'Other skill', _owner: { user_id: 'alice' } } })
  await state.remove()
  assert.equal(api.deleteSkill.mock.calls.length, 0)
})

test('MCP connection editing retains existing timeout settings and never echoes a stored key', async t => {
  const { api, mount } = await setup(t, 'Mcp')
  const item = { name: 'notes', protocol: 'streamable_http', url: 'https://example.test/mcp', timeout_seconds: 12.5, call_timeout_seconds: 180, has_api_key: true }
  t.mock.method(api, 'listMcp', async () => [item])
  t.mock.method(api, 'listTools', async () => [])
  t.mock.method(api, 'updateMcp', async () => ({}))
  const state = await mount()
  state.edit(item)
  assert.equal(state.form.api_key, '')
  await state.save()
  assert.equal(api.updateMcp.mock.calls[0].arguments[1].timeout_seconds, 12.5)
  assert.equal(api.updateMcp.mock.calls[0].arguments[1].call_timeout_seconds, 180)
  state.drawerOpen = false
  state.edit({ ...item, _owner: { user_id: 'alice' } })
  assert.equal(state.drawerOpen, false)
})

test('execution settings reads and saves only the current account policy even for admins', async t => {
  const { api, mount } = await setup(t, 'ExecutionSettings')
  t.mock.method(api, 'adminUsers', async () => { throw new Error('must not fetch other users') })
  t.mock.method(api, 'executionPolicy', async () => ({ shell: 'ask', on_approval_required: 'suspend', approval_timeout_seconds: 3600 }))
  t.mock.method(api, 'saveExecutionPolicy', async body => body)
  const state = await mount()
  assert.equal(state.form.timeout, 60)
  state.form.shell = 'deny'
  state.form.timeout = 30
  await state.save()
  assert.deepEqual(api.saveExecutionPolicy.mock.calls[0].arguments, [{ shell: 'deny', on_approval_required: 'suspend', approval_timeout_seconds: 1800 }])
  assert.equal(api.adminUsers.mock.calls.length, 0)
})

test('personal API keys stay in the current account scope and preserve creation permissions', async t => {
  const { api, mount } = await setup(t, 'ApiKeys')
  t.mock.method(api, 'listKeys', async all => { assert.equal(all, false); return [] })
  t.mock.method(api, 'listAgents', async all => { assert.equal(all, false); return [{ id: 'own', name: 'Own' }] })
  t.mock.method(api, 'createKey', async () => ({ api_key: 'one-time-fixture' }))
  const state = await mount()
  assert.equal(state.ready, true)
  state.startNew()
  state.form.name = 'Integration'
  state.form.approve = true
  await state.create()
  assert.deepEqual(api.createKey.mock.calls[0].arguments, [{ name: 'Integration', agent_id: 'own', scopes: ['a2a:invoke', 'a2a:read', 'a2a:approve'] }])
  assert.equal(state.issued, 'one-time-fixture')
  assert.equal(api.listKeys.mock.calls.length, 2)
})

test('user execution policy viewer switches to the selected row without changing policies', async t => {
  const { api, mount } = await setup(t, 'Users')
  const alice = { user_id: 'alice', username: 'Alice', execution_policy: { shell: 'ask', on_approval_required: 'suspend', approval_timeout_seconds: 3600 } }
  const bob = { user_id: 'bob', username: 'Bob', execution_policy: { shell: 'deny', on_approval_required: 'deny', approval_timeout_seconds: 1800 } }
  t.mock.method(api, 'adminUsers', async () => [alice, bob])
  t.mock.method(api, 'saveExecutionPolicy', async () => { throw new Error('read-only viewer') })
  const state = await mount()
  state.showExecutionPolicy(state.users[0])
  assert.equal(state.policyOpen, true)
  assert.equal(state.selectedUser.execution_policy.shell, 'ask')
  state.policyOpen = false
  state.showExecutionPolicy(state.users[1])
  assert.equal(state.selectedUser.username, 'Bob')
  assert.equal(state.selectedUser.execution_policy.shell, 'deny')
  assert.equal(api.saveExecutionPolicy.mock.calls.length, 0)
})

test('user search and role filters retain original policies and clear without refetching', async t => {
  const { api, mount } = await setup(t, 'Users')
  const users = [
    { user_id: 'admin-id', username: 'Admin', role: 'admin', execution_policy: { shell: 'ask', on_approval_required: 'suspend', approval_timeout_seconds: 3600 } },
    { user_id: 'member-id', username: 'Member', role: 'user', execution_policy: { shell: 'deny', on_approval_required: 'deny', approval_timeout_seconds: 1800 } },
  ]
  t.mock.method(api, 'adminUsers', async () => users)
  const state = await mount()
  state.search = 'MEMBER-ID'
  assert.deepEqual(state.visibleUsers.map(user => user.username), ['Member'])
  state.role = 'admin'
  assert.equal(state.visibleUsers.length, 0)
  state.clearFilters()
  assert.equal(state.visibleUsers.length, 2)
  state.showExecutionPolicy(state.visibleUsers[1])
  assert.deepEqual(state.selectedUser.execution_policy, users[1].execution_policy)
  assert.equal(api.adminUsers.mock.calls.length, 1)
})

test('system plugin reload discards only the current draft and retains another category draft', async t => {
  const { api, mount } = await setup(t, 'Plugins')
  const memory = 'memory.provider', summary = 'context.summarizer'
  const bm25 = 'sage.memory.filesystem-bm25', extractive = 'sage.context.summarizer.extractive'
  t.mock.method(api, 'listPlugins', async () => ({ plugins: [
    { id: bm25, capabilities: [memory], schema: { properties: { root: { type: 'string' } } } },
    { id: extractive, capabilities: [summary], schema: { properties: { limit: { type: 'integer' } } } },
  ] }))
  t.mock.method(api, 'serverPlugins', async () => ({ configurable: [memory, summary], providers: [], defaults: {}, saved: {
    [memory]: { plugin: bm25, config: { root: '/saved' } }, [summary]: { plugin: extractive, config: { limit: 20 } },
  }, pending: [], revision: 'current' }))
  const state = await mount()
  state.selectNode(summary); state.draft.config.limit = 7
  state.selectNode(memory); state.draft.config.root = '/draft'
  assert.ok(state.draftChanges.some(change => change.before === '/saved' && change.after === '/draft'))
  await state.reloadServer()
  assert.equal(state.draft.config.root, '/saved')
  state.selectNode(summary)
  assert.equal(state.draft.config.limit, 7)
})

test('model edits preserve request options and probe facts through save and default selection', async t => {
  const { api, mount } = await setup(t, 'Models')
  const model = { id: 'model-1', protocol: 'openai-chat-completions', base_url: 'https://example.invalid/v1', model: 'demo', is_default: false,
    request: { temperature: 0, max_output_tokens: 8192, extra: { seed: 7 } }, limits: { context_window: 128000 }, capabilities: { tool_calling: true } }
  t.mock.method(api, 'listModels', async () => [model])
  t.mock.method(api, 'getModel', async () => ({ ...model, api_key: 'key' }))
  t.mock.method(api, 'saveModel', async body => body)
  t.mock.method(api, 'probeModel', async () => ({ route_fingerprint: 'fingerprint', outcomes: [{ name: 'tool_calling', status: 'supported' }, { name: 'multimodal', status: 'unsupported' }] }))
  const state = await mount()
  await state.openModel(model, false)
  assert.equal(state.form.request.temperature, 0)
  await state.probe()
  assert.equal(state.form.capability_profile.route_fingerprint, 'fingerprint')
  assert.equal(state.form.capabilities.multimodal, false)
  await state.save()
  assert.equal(api.saveModel.mock.calls[0].arguments[0].request.extra.seed, 7)
  await state.makeCurrent(model)
  assert.deepEqual(api.saveModel.mock.calls[1].arguments[0].request, model.request)
  state.startNew()
  assert.equal(state.form.capability_profile, undefined)
  state.form.protocol = 'gemini-generate-content'
  state.onProtocolChange()
  assert.equal(state.form.base_url, 'https://generativelanguage.googleapis.com/v1beta')
})

test('package form edits retain unrelated agents, files and runtime selections', async t => {
  const { mount } = await setup(t, 'PackageEditor', 'components')
  const bundle = { manifest: { metadata: { id: 'demo', version: '1' }, agents: { main: { name: 'Main' }, child: { name: 'Child' } }, runtime: { capabilities: { 'memory.provider': { plugin: 'memory' } } } }, files: { 'prompts/main.md': 'Keep me' } }
  let changed
  const state = await mount({ modelValue: JSON.stringify(bundle), schema: { bundle_schema: { properties: { manifest: { type: 'object' } } } }, 'onUpdate:modelValue': value => { changed = JSON.parse(value) } })
  state.update({ id: 'demo', version: '2' })
  assert.equal(changed.manifest.metadata.version, '2')
  assert.deepEqual(changed.manifest.agents, bundle.manifest.agents)
  assert.deepEqual(changed.files, bundle.files)
  assert.deepEqual(changed.manifest.runtime, bundle.manifest.runtime)
})

test('inconclusive probe failures retain declared abilities instead of disabling them', async t => {
  const { api, mount } = await setup(t, 'Models')
  t.mock.method(api, 'listModels', async () => [])
  t.mock.method(api, 'probeModel', async () => ({ outcomes: [
    { name: 'tool_calling', status: 'error', error: 'timeout' },
    { name: 'multimodal', status: 'error', error: 'HTTP 429' },
    { name: 'structured_output', status: 'unsupported' },
    { name: 'json_object', status: 'error' },
  ] }))
  const state = await mount()
  state.startNew()
  state.form.capabilities = { tool_calling: true, multimodal: true, structured_output: true }
  await state.probe()
  assert.deepEqual(state.form.capabilities, { tool_calling: true, multimodal: true, structured_output: true })
  assert.equal(state.probing, false)
})


test('plugin settings group implementations under Desktop component names and keep actual values', async t => {
  const { api, mount } = await setup(t, 'Plugins')
  const model = 'sage.context.summarizer.model', extractive = 'sage.context.summarizer.extractive'
  t.mock.method(api, 'listPlugins', async () => ({ defaults: { 'context.summarizer': model }, plugins: [
    { id: model, name: 'Model summary', capabilities: ['context.summarizer'], schema: { properties: { timeout_seconds: { default: 300 } } } },
    { id: extractive, name: 'Extractive', capabilities: ['context.summarizer'], schema: {} },
  ] }))
  t.mock.method(api, 'serverPlugins', async () => ({ providers: [{ capability: 'context.summarizer', plugin_id: model }], selections: { 'context.summarizer': { plugin: model, config: { timeout_seconds: 45 } } } }))
  const state = await mount()
  assert.equal(state.groups.length, 1)
  const group = state.groups[0]
  assert.equal(group.name, '上下文摘要器')
  assert.equal(group.plugins.length, 2)
  assert.equal(state.currentNames(group), '模型摘要')
  assert.equal(state.parameterRows(group)[0].value, '45')
  state.preview[group.id] = extractive
  assert.equal(state.inspecting(group).id, extractive)
  assert.equal(state.currentNames(group), '模型摘要')
  assert.equal(api.serverPlugins.mock.calls.length, 1)
})

test('plugin settings handle Server injected components without descriptors or selections', async t => {
  const { api, mount } = await setup(t, 'Plugins')
  t.mock.method(api, 'listPlugins', async () => ({ defaults: {}, plugins: [
    { id: 'sage.context.summarizer.model', capabilities: ['context.summarizer'], schema: { properties: { timeout_seconds: { default: 30 } } } },
  ] }))
  t.mock.method(api, 'serverPlugins', async () => ({ providers: [
    { capability: 'derived-state.store', plugin_id: null, scope: 'process' },
    { capability: 'session.access', plugin_id: null, scope: 'process' },
    { capability: 'agent.approval-memory', plugin_id: null, scope: 'process' },
  ], selections: {} }))
  const state = await mount()
  assert.equal(state.error, '')
  assert.equal(state.groups.length, 4)
  assert.ok(state.groups.some(group => group.id === 'context.summarizer'))
  for (const group of state.groups) {
    const rows = state.parameterRows(group)
    if (group.id === 'context.summarizer') assert.equal(rows[0].value, '30')
    else {
      assert.deepEqual(rows, [])
      assert.equal(state.currentNames(group), '未指定')
    }
  }
  state.server = null
  assert.doesNotThrow(() => state.parameterRows({ id: 'derived-state.store', plugins: [] }))
})

test('Server plugin editor saves a real selection, preserves failed drafts, and resets defaults', async t => {
  const { api, Component, mount } = await setup(t, 'Plugins')
  const id = 'sage.memory.filesystem-bm25'
  t.mock.method(api, 'listPlugins', async () => ({ defaults: { 'memory.provider': 'sage.memory.noop' }, plugins: [
    { id: 'sage.memory.noop', capabilities: ['memory.provider'], schema: {} },
    { id, capabilities: ['memory.provider'], schema: { properties: { root: { type: 'string' } } } },
  ] }))
  const initial = { providers: [], selections: {}, saved: { 'memory.provider': { plugin: id, config: { root: '/data/original' } } }, defaults: {}, configurable: ['memory.provider'], pending: ['memory.provider'], revision: 'first', storage_root: '/data/plugins' }
  t.mock.method(api, 'serverPlugins', async () => initial)
  t.mock.method(api, 'saveServerPlugins', async body => {
    if (body.revision === 'stale') throw new Error('配置已被其他管理员修改')
    return { ...initial, revision: 'next', saved: body.changes['memory.provider'] ? body.changes : {}, pending: body.changes['memory.provider'] ? ['memory.provider'] : [] }
  })
  const state = await mount()
  const group = state.groups[0]
  state.startEdit(group)
  state.draft.config.root = '/data/changed'
  assert.equal(state.server.saved['memory.provider'].config.root, '/data/original')
  state.server.revision = 'stale'
  await state.saveServer()
  assert.match(state.saveError, /其他管理员/)
  assert.equal(state.editing, 'memory.provider')
  assert.equal(state.draft.config.root, '/data/changed')
  state.server.revision = 'first'
  state.choosePlugin(id)
  assert.equal(state.draft.config.root, '/data/plugins/memory.provider')
  await state.saveServer()
  assert.equal(state.editing, '')
  assert.match(state.message, /重启/)
  assert.equal(state.currentNames(group), '关闭长期记忆')
  const html = await renderToString(createSSRApp({ ...Component, setup: () => state }))
  assert.match(html, /<article/)
  assert.match(html, /已保存默认/)
  assert.match(html, /本地 BM25 记忆/)
  assert.match(html, /配置系统默认/)
  state.startEdit(group)
  state.choosePlugin('')
  await state.saveServer()
  assert.equal(api.saveServerPlugins.mock.calls.at(-1).arguments[0].changes['memory.provider'], null)
  assert.equal(state.server.pending.length, 0)
})


test('Studio starts new Package runs through the ordinary chat page', async t => {
  const { api, navigation, mount } = await setup(t, 'Studio')
  const bundle = { manifest: { entrypoint: { agent: 'assistant' }, agents: { assistant: {} } } }
  for (const method of ['packages', 'packageRuns', 'listAgents']) t.mock.method(api, method, async () => [])
  t.mock.method(api, 'packageSchema', async () => ({}))
  t.mock.method(api, 'packageTemplate', async () => bundle)
  t.mock.method(api, 'runPackage', async () => { throw new Error('must not use the legacy run path') })
  const previous = Object.getOwnPropertyDescriptor(globalThis, 'sessionStorage')
  const drafts = new Map()
  Object.defineProperty(globalThis, 'sessionStorage', { configurable: true, value: { setItem: (key, value) => drafts.set(key, value) } })
  t.after(() => previous ? Object.defineProperty(globalThis, 'sessionStorage', previous) : delete globalThis.sessionStorage)
  const state = await mount()
  state.savedRef = 'package@1.0.0'; state.content = 'Run this package'
  await state.run()
  assert.equal(state.error, '')
  assert.equal(api.runPackage.mock.calls.length, 0)
  const target = navigation.push.mock.calls[0].arguments[0]
  assert.equal(target.path, '/')
  assert.equal(target.query.package, 'package@1.0.0')
  assert.deepEqual(JSON.parse(drafts.get(target.query.draft)), { content: 'Run this package' })
})

test('package model slots select App model IDs without embedding model routes', async t => {
  const { mount } = await setup(t, 'PackageEditor', 'components')
  const bundle = { manifest: { agents: { main: { models: { primary: 'existing-id' } } } }, files: {} }
  const schema = { bundle_schema: { $defs: { AgentDefinition: { properties: {
    mode: {}, models: { patternProperties: { '^.*$': { type: 'string' } } }, delegation_model_bindings: {},
    tools: {}, skills: {}, subagents: {},
  } } }, properties: { manifest: { type: 'object' } } } }
  const state = await mount({ modelValue: JSON.stringify(bundle), schema, resources: { models: [{ id: 'app-model', model: 'Model label' }] } })
  const bindings = state.root.$defs.AgentDefinition.properties
  assert.deepEqual(bindings.models.additionalProperties.enum, ['default', 'app-model', 'existing-id'])
  assert.equal(bindings.models.additionalProperties['x-option-labels']['app-model'], 'Model label')
  assert.deepEqual(bindings.delegation_model_bindings.additionalProperties.enum, ['default', 'app-model'])
  assert.equal(state.sections.includes('models'), false)
  assert.equal(state.sections.includes('credentials'), false)
  assert.equal(state.bundle.manifest.models, undefined)
})


test('agent editor combines selected tools while preserving independent scopes and missing grants', async t => {
  const { Component, mount } = await setup(t, 'AgentEditor', 'components')
  let form = { name: 'Scoped', tools: ['file_read'], external_tools: ['mcp_old'], execution_policy: { shell: 'ask' } }
  const state = await mount({ form, externalTools: ['mcp_read', 'a2a_peer_search'],
    'onUpdate:form': value => { form = value } })
  state.setSelectedTools(['tools:file_read', 'external_tools:mcp_old', 'external_tools:mcp_read'])
  assert.deepEqual(form.external_tools, ['mcp_old', 'mcp_read'])
  assert.deepEqual(form.tools, ['file_read'])
  const html = await renderToString(createSSRApp(Component, { form, externalTools: ['mcp_read', 'a2a_peer_search'] }))
  assert.match(html, /3 已选/)
  assert.match(html, /mcp_read/)
  assert.doesNotMatch(html, /未选择时使用服务端默认工具/)
})

test('agents retain external scope through opening and saving, excluding disabled connections', async t => {
  const { api, mount } = await setup(t, 'Agents')
  t.mock.method(api, 'agentEditorResources', async () => editorResources({ external_tools: ['mcp_read', 'a2a_search'] }))
  const agent = { id: 'scoped', name: 'Scoped', tools: ['file_read'], external_tools: ['mcp_read'] }
  t.mock.method(api, 'agentSummaries', async () => [agent])
  t.mock.method(api, 'getAgent', async () => agent)
  t.mock.method(api, 'updateAgent', async (id, body) => ({ ...body, id }))
  t.mock.method(api, 'bindAgentSkills', async () => [])
  const state = await mount()
  assert.deepEqual(state.externalTools, [])
  await state.openAgent(agent, false)
  await new Promise(done => setImmediate(done))
  assert.deepEqual(state.externalTools, ['mcp_read', 'a2a_search'])
  assert.deepEqual(state.form.external_tools, ['mcp_read'])
  state.form.external_tools = []
  await state.save(false)
  assert.deepEqual(api.updateAgent.mock.calls[0].arguments[1].external_tools, [])
  await state.startNew()
  assert.deepEqual(state.form.external_tools, [])
})

test('capability canvas selection preserves unrelated bindings and blocks unavailable or read-only changes', async t => {
  const { api, mount } = await setup(t, 'PluginConfig', 'components')
  const capability = 'tool.selection-policy', plugin = 'sage.tool-selection.lexical'
  t.mock.method(api, 'listPlugins', async () => ({ configurable: [capability], defaults: { [capability]: 'sage.tool-selection.llm' }, plugins: [
    { id: plugin, capabilities: [capability], schema: { properties: { max_visible_tools: { default: 24 } } } },
    { id: 'unavailable', capabilities: [capability], available: false },
  ] }))
  const original = { [capability]: { plugin: 'sage.tool-selection.llm', scope: 'run', config: { old: true } }, 'flow.node': { plugin: 'custom.node', config: { retained: true } } }
  const updates = []
  const props = { modelValue: original, savedValue: original, 'onUpdate:modelValue': value => updates.push(value) }
  const state = await mount(props)
  assert.equal(state.active, capability)
  state.update(capability, plugin)
  assert.deepEqual(updates[0][capability], { plugin, scope: 'run', config: {} })
  assert.deepEqual(updates[0]['flow.node'], original['flow.node'])
  assert.equal(original[capability].config.old, true)
  state.update(capability, 'unavailable'); state.update('flow.node', 'custom.node')
  assert.equal(updates.length, 1)
  state.update(capability, '')
  assert.deepEqual(updates[1], { 'flow.node': original['flow.node'] })
  const readonly = await mount({ ...props, disabled: true })
  readonly.update(capability, plugin); readonly.configure(capability, { max_visible_tools: 4 })
  assert.equal(updates.length, 2)
})

test('capability parameters and change preview reflect draft configuration instead of claiming runtime results', async t => {
  const { api, Component, mount } = await setup(t, 'PluginConfig', 'components')
  const capability = 'tool.selection-policy', plugin = 'sage.tool-selection.lexical'
  t.mock.method(api, 'listPlugins', async () => ({ configurable: [capability], defaults: { [capability]: 'sage.tool-selection.llm' }, plugins: [
    { id: plugin, capabilities: [capability], schema: { properties: { max_visible_tools: { type: 'integer', default: 24 } } } },
    { id: 'sage.tool-selection.llm', capabilities: [capability], schema: { properties: { max_visible_tools: { default: 24 } } } },
  ] }))
  let updated
  const state = await mount({ modelValue: { [capability]: { plugin, config: { max_visible_tools: 7 } } }, savedValue: {},
    modelLabel: 'App model', 'onUpdate:modelValue': value => { updated = value } })
  assert.equal(state.active, capability)
  assert.equal(state.current.config.max_visible_tools, 7)
  assert.ok(state.explanation.effects.some(value => value.includes('7')))
  assert.ok(state.changes.some(change => change.after === 'BM25 相关性选择'))
  state.configure(capability, { max_visible_tools: 9 })
  assert.equal(updated[capability].config.max_visible_tools, 9)
  const html = await renderToString(createSSRApp({ ...Component, setup: () => state }))
  assert.match(html, /能力节点画布/)
  assert.match(html, /配置推演/)
  assert.match(html, /本次变更/)
})

test('agent configuration starts at the first tab and continuous scrolling includes the canvas', async t => {
  const { mount, Component } = await setup(t, 'AgentEditor', 'components')
  const props = { agentId: 'existing', form: { name: 'Agent', tools: [], execution_policy: { shell: 'ask' } } }
  const state = await mount(props)
  assert.equal(state.activeSection, 'basic')
  const html = await renderToString(createSSRApp(Component, props))
  assert.match(html, /id="agent-plugins"/)
  assert.match(html, /id="agent-basic"/)
  const scroll = t.mock.fn()
  state.content = { scrollTop: 900, scrollTo: scroll, getBoundingClientRect: () => ({ top: 0 }), querySelector: selector => ({
    getBoundingClientRect: () => ({ top: ({ '#agent-basic': -800, '#agent-model': -200, '#agent-plugins': 20 })[selector] ?? 1200 }),
    scrollIntoView() {},
  }) }
  state.trackSection()
  assert.equal(state.activeSection, 'plugins')
  await state.jump('basic')
  assert.equal(state.activeSection, 'basic')
  assert.equal(scroll.mock.calls[0].arguments[0].top, 76)
})

test('package visual configuration resolves the recursive bundle schema root used by Server', async t => {
  const { mount, Component } = await setup(t, 'PackageEditor', 'components')
  const schema = { bundle_schema: { $ref: '#/$defs/AgentPackageBundle', $defs: {
    AgentPackageBundle: { type: 'object', properties: { manifest: { $ref: '#/$defs/Manifest' } } },
    Manifest: { type: 'object', properties: { metadata: { type: 'object', properties: { id: { type: 'string' } } } } },
  } } }
  const state = await mount({ schema, modelValue: JSON.stringify({ manifest: { metadata: { id: 'demo' } } }) })
  assert.ok(state.root.properties.manifest)
  const html = await renderToString(createSSRApp({ ...Component, setup: () => state }))
  assert.match(html, /Package 配置分区/)
  assert.match(html, /能力编排/)
})

test('system plugin form retains single implementations and unsaved drafts across category changes', async t => {
  const { api, mount } = await setup(t, 'Plugins')
  const memory = 'memory.provider', summary = 'context.summarizer', bm25 = 'sage.memory.filesystem-bm25', noop = 'sage.memory.noop'
  t.mock.method(api, 'listPlugins', async () => ({ configurable: [summary], defaults: { [memory]: noop, [summary]: 'sage.context.summarizer.extractive' }, plugins: [
    { id: noop, capabilities: [memory], schema: {} }, { id: bm25, capabilities: [memory], schema: { properties: { root: { type: 'string' } } } },
    { id: 'sage.context.summarizer.extractive', capabilities: [summary], schema: {} },
  ] }))
  t.mock.method(api, 'serverPlugins', async () => ({ configurable: [memory, summary, 'missing.capability'], providers: [], selections: {}, saved: {}, defaults: { [memory]: { plugin: noop }, [summary]: { plugin: 'sage.context.summarizer.extractive' } }, pending: [], revision: 'one', storage_root: '/data/plugins' }))
  const state = await mount()
  assert.equal(state.groups.length, 3)
  state.selectNode(memory); state.choosePlugin(bm25); state.draft.config.root = '/data/draft'
  state.selectNode(summary)
  assert.equal(state.navigationItems.find(node => node.id === memory).sourceText, '未保存')
  state.selectNode(memory)
  assert.equal(state.draft.config.root, '/data/draft')
  state.cancelEdit(); state.selectNode(memory)
  assert.equal(state.draft, null)
})

test('ordinary users inspect system implementations without changing defaults or querying admin configuration', async t => {
  const { api, mount } = await setup(t, 'Plugins')
  t.mock.method(localStorage, 'getItem', key => key.endsWith('.user') ? JSON.stringify({ user_id: 'user', role: 'user' }) : '')
  t.mock.method(api, 'listPlugins', async () => ({ configurable: ['context.summarizer'], defaults: { 'context.summarizer': 'sage.context.summarizer.extractive' }, plugins: [
    { id: 'sage.context.summarizer.extractive', capabilities: ['context.summarizer'], schema: {} },
  ] }))
  t.mock.method(api, 'serverPlugins', async () => { throw Error('admin read') })
  t.mock.method(api, 'saveServerPlugins', async () => { throw Error('admin write') })
  const state = await mount()
  state.startEdit(state.groups[0]); state.selectImplementation(state.groups[0].plugins[0]); await state.saveServer()
  assert.equal(state.editing, '')
  assert.equal(state.inspecting(state.groups[0]).id, 'sage.context.summarizer.extractive')
  assert.equal(api.serverPlugins.mock.calls.length, 0)
  assert.equal(api.saveServerPlugins.mock.calls.length, 0)
})

test('system plugins with fixed bindings or no editable configuration are visibly read-only and cannot save', async t => {
  const { api, Component, mount } = await setup(t, 'Plugins')
  const fixed = 'session.store', empty = 'context.reducer', injected = 'package.registry', unavailable = 'unavailable', editable = 'skill.loading'
  const plugins = [
    { id: 'sage.session.mysql', capabilities: [fixed], schema: { properties: { dsn: { type: 'string' } } } },
    { id: 'sage.context.reducer.window', capabilities: [empty], schema: { properties: {} } },
    { id: 'sage.package-registry.ephemeral', capabilities: [injected], schema: { properties: { resolver: {} } } },
    { id: 'missing', capabilities: [unavailable], available: false, schema: { properties: { root: { type: 'string' } } } },
    { id: 'sage.skill.loading.lazy', capabilities: [editable], schema: { properties: { max_active_characters: { type: 'integer' } } } },
  ]
  t.mock.method(api, 'listPlugins', async () => ({ defaults: {}, plugins }))
  t.mock.method(api, 'serverPlugins', async () => ({ configurable: [empty, injected, unavailable, editable], providers: [], selections: {}, saved: {}, defaults: {}, pending: [] }))
  t.mock.method(api, 'saveServerPlugins', async () => { throw Error('read-only write') })
  const state = await mount()
  for (const id of [fixed, empty, injected, unavailable]) {
    state.selectNode(id)
    assert.equal(state.canConfigure(id), false)
    assert.equal(state.navigationItems.find(item => item.id === id).sourceText, '不可修改')
    state.startEdit(state.currentGroup)
    state.selectImplementation(state.currentGroup.plugins[0])
    assert.equal(state.editing, '')
    await state.saveServer()
    const html = await renderToString(createSSRApp({ ...Component, setup: () => state }))
    assert.match(html, /不可修改/)
    assert.match(html, /class="[^"]*\bimplementation\b[^"]*"[^>]*disabled/)
    assert.doesNotMatch(html, /部署管理|保存系统默认|配置系统默认|保存后需重启生效/)
    assert.doesNotMatch(html, /<input[^>]*type="(?:number|text)"/)
  }
  assert.equal(api.saveServerPlugins.mock.calls.length, 0)
  state.selectNode(editable)
  assert.equal(state.canConfigure(editable), true)
  assert.equal(state.editing, editable)
})

test('agent picker searches purpose, isolates modal drafts, and preserves selection across pages', async t => {
  const { mount } = await setup(t, 'AgentResourceSelection', 'components')
  const { agentToolChoices } = await import('../src/agent-resource-selection.js')
  const items = agentToolChoices([{ name: 'file_read', source: 'official', category: 'files' }],
    Array.from({ length: 240 }, (_, index) => `mcp_research_${index}`), [], [], ['lost'])
  const updates = []
  const state = await mount({ kind: 'tools', items, selected: ['external_tools:lost'],
    'onUpdate:selected': value => updates.push(value) })
  await state.show()
  state.query = 'research'; await nextTick()
  assert.equal(state.results.length, 240)
  state.bulk(true)
  assert.equal(state.draft.size, 241)
  state.turnPage(5)
  assert.equal(state.visibleItems.length, 20)
  assert.equal(state.visibleItems.every(item => state.draft.has(item.id)), true)
  assert.equal(updates.length, 0)
  state.open = false
  await state.show()
  assert.deepEqual([...state.draft], ['external_tools:lost'])
  state.query = '读取文件'; await nextTick()
  assert.equal(state.results.length, 1)
  state.bulk(true); state.confirm()
  assert.deepEqual(updates, [['external_tools:lost', 'tools:file_read']])
  const readonly = await mount({ kind: 'tools', items, selected: ['external_tools:lost'], readonly: true,
    'onUpdate:selected': () => { throw new Error('readonly mutation') } })
  await readonly.show(); readonly.bulk(true); readonly.toggle(items[0], true); readonly.remove(items[0]); readonly.confirm()
  assert.deepEqual([...readonly.draft], ['external_tools:lost'])
})

test('agent resource confirmation preserves order and blocks writes while busy', async t => {
  const { mount } = await setup(t, 'AgentEditor', 'components')
  const form = { name: 'Agent', tools: ['later', 'first'], external_tools: ['lost'], execution_policy: { shell: 'ask' } }
  let updated
  const state = await mount({ form, tools: [{ name: 'first' }, { name: 'later' }],
    'onUpdate:form': value => { updated = value } })
  state.setSelectedTools(state.selectedToolIds)
  assert.deepEqual(updated, form)
  state.setSelectedTools([...state.selectedToolIds, 'external_tools:missing:undo'])
  assert.deepEqual(updated.external_tools, ['lost', 'missing:undo'])
  const busy = await mount({ form, busy: true, 'onUpdate:form': () => { throw new Error('busy mutation') },
    'onUpdate:selectedSkills': () => { throw new Error('busy mutation') } })
  busy.setSelectedTools([]); busy.setSelectedSkills([]); busy.updateBudget('max_steps', 10)
})

test('agent A editor protects unsaved edits and returns to basic when scrolled above other sections', async t => {
  const { mount } = await setup(t, 'AgentEditor', 'components')
  const saved = { name: 'Saved', tools: [], memory: { recall: false }, execution_policy: { shell: 'ask' } }
  let closed = 0
  const state = await mount({ agentId: 'id', form: { ...saved, name: 'Changed' }, savedForm: saved, selectedSkills: ['research'], savedSkills: [], onClose: () => { closed++ } })
  assert.equal(state.dirty, true)
  assert.equal(state.changedSections.basic, true)
  assert.equal(state.changedSections.skills, true)
  state.requestClose()
  assert.equal(state.leaveOpen, true)
  assert.equal(closed, 0)
  state.discardAndClose()
  assert.equal(closed, 1)
  state.activeSection = 'tools'
  state.content = { getBoundingClientRect: () => ({ top: 0 }), querySelector: () => ({ getBoundingClientRect: () => ({ top: 300 }) }) }
  state.trackSection()
  assert.equal(state.activeSection, 'basic')
})

test('agent A saved baseline advances after both configuration and skills persist and retries the same created agent', async t => {
  const { api, mount } = await setup(t, 'Agents')
  t.mock.method(api, 'agentSummaries', async () => [])
  t.mock.method(api, 'agentEditorResources', async () => editorResources())
  t.mock.method(api, 'createAgent', async body => ({ ...body, id: 'created' }))
  t.mock.method(api, 'updateAgent', async (id, body) => ({ ...body, id }))
  t.mock.method(api, 'bindAgentSkills', async () => { throw new Error('Skills unavailable') })
  const state = await mount()
  await state.startNew()
  state.form.name = 'Draft'
  state.form.plugins = { 'context.summarizer': { plugin: 'summary' } }
  state.selectedSkills = ['research']
  await state.save(false)
  assert.equal(state.editing, 'created')
  assert.equal(state.drawerOpen, true)
  assert.deepEqual(state.savedPlugins, {})
  assert.notEqual(state.savedForm?.name, 'Draft')
  api.bindAgentSkills.mock.mockImplementation(async () => [])
  await state.save(false)
  assert.equal(api.createAgent.mock.calls.length, 1)
  assert.equal(api.updateAgent.mock.calls.length, 1)
  assert.equal(state.savedForm.name, 'Draft')
  assert.deepEqual(state.savedSkills, ['research'])
  assert.deepEqual(state.savedPlugins, state.form.plugins)
})

test('agent A keeps foreign and busy mutations blocked and retains failed deletion for retry', async t => {
  const { api, mount } = await setup(t, 'Agents')
  const foreign = { id: 'shared', name: 'Shared', _owner: { user_id: 'alice' } }, own = { id: 'own', name: 'Own' }
  t.mock.method(api, 'agentSummaries', async () => [own, foreign])
  t.mock.method(api, 'agentEditorResources', async () => editorResources())
  t.mock.method(api, 'getAgent', async () => foreign)
  t.mock.method(api, 'updateAgent', async () => { throw new Error('unexpected update') })
  t.mock.method(api, 'deleteAgent', async () => { throw new Error('Deletion failed') })
  const state = await mount()
  await state.openAgent(foreign, false)
  await new Promise(resolve => setImmediate(resolve))
  assert.equal(state.viewOnly, true)
  state.requestDelete(foreign); await state.remove(foreign); await state.save(false)
  assert.equal(state.deleteOpen, false)
  assert.equal(api.updateAgent.mock.calls.length, 0)
  assert.equal(api.deleteAgent.mock.calls.length, 0)
  state.pending = true
  state.requestDelete(own); await state.remove(own)
  assert.equal(state.deleteOpen, false)
  assert.equal(api.deleteAgent.mock.calls.length, 0)
  state.pending = false
  state.requestDelete(own); await state.remove(own)
  assert.equal(state.deleteOpen, true)
  assert.equal(state.deleteTarget.id, 'own')
  assert.equal(state.deleteError, 'Deletion failed')
  assert.equal(state.pending, false)
})

test('tool directory separates built-ins from MCP and agent management in both cards and categories', async t => {
  const { api, mount } = await setup(t, 'Tools')
  t.mock.method(api, 'listTools', async () => [
    { name: 'file_read', source: 'official', category: 'files' },
    { name: 'file_read', source: 'mcp', category: 'MCP' },
    { name: 'create_agent', source: 'host', category: 'agent-management' },
  ])
  const state = await mount()
  assert.deepEqual(state.categories, ['files'])
  assert.deepEqual(state.visible.map(view => [view.item.source, view.item.name]), [['official', 'file_read']])
  state.search = 'create_agent'
  assert.equal(state.visible.length, 0)
})

test('MCP page defaults to a full tool inventory with independent owner failures and searchable service filters', async t => {
  const { api, mount } = await setup(t, 'Mcp')
  const alice = { user_id: 'alice', username: 'Alice' }
  const own = { name: 'notes', tools: ['mcp_notes_read'] }, foreign = { name: 'notes', tools: ['foreign_read'], _owner: alice }, stopped = { name: 'stopped', disabled: true, tools: ['cached_tool'] }
  t.mock.method(api, 'listMcp', async () => [own, foreign, stopped])
  t.mock.method(api, 'listTools', async owner => {
    if (owner?.user_id === 'alice') throw new Error('Offline')
    return [{ name: 'mcp_notes_read', source: 'mcp', approval_key: 'mcp:notes:read', description: 'Search all notes', input_schema: { type: 'object' } }, { name: 'file_read', source: 'official' }]
  })
  const state = await mount()
  assert.equal(state.mode, 'tools')
  assert.equal(state.inventory.length, 3)
  assert.equal(state.inventory.find(row => row.tool.name === 'cached_tool').state, 'disabled')
  assert.equal(state.inventory.find(row => row.tool.name === 'foreign_read').hasDefinition, false)
  assert.match(state.toolErrors[0], /Alice.*Offline/)
  assert.deepEqual(api.listTools.mock.calls.map(call => call.arguments[0]?.user_id), [undefined, 'alice'])
  state.search = 'all notes'
  assert.deepEqual(state.visibleTools.map(row => row.tool.name), ['mcp_notes_read'])
  state.showTools(foreign)
  assert.deepEqual(state.visibleTools.map(row => row.tool.name), ['foreign_read'])
  state.mode = 'connections'; await nextTick()
  assert.equal(state.visibleServers.length, 3)
})

test('MCP page ignores stale tool definitions after a connection list refresh', async t => {
  const { api, mount } = await setup(t, 'Mcp')
  let finish
  t.mock.method(api, 'listMcp', async () => [{ name: 'old', tools: ['mcp_old'] }])
  t.mock.method(api, 'listTools', () => new Promise(resolve => { finish = resolve }))
  const state = await mount()
  assert.equal(state.toolsLoading, true)
  state.mode = 'connections'; await nextTick()
  api.listMcp.mock.mockImplementation(async () => [])
  await state.refresh()
  finish([{ name: 'mcp_old', source: 'mcp', approval_key: 'mcp:old:read' }])
  await new Promise(resolve => setImmediate(resolve)); await nextTick()
  assert.deepEqual(state.inventory, [])
  assert.deepEqual(state.catalogs, [])
})

test('tool approval modal keeps paginated rule changes local until confirmation and uses real approval keys', async t => {
  const { mount } = await setup(t, 'AgentToolApproval', 'components')
  const tools = Array.from({ length: 235 }, (_, index) => ({ name: `mcp_notes_read_${index}`,
    source: 'mcp', approval_key: `mcp:notes:read.remote.${index}`, description: 'Read research notes' }))
  const original = { 'mcp:old:write': 'ask', untouched: 'auto_approve' }, updates = []
  let loads = 0
  const state = await mount({ tools, modelValue: original, defaultMode: 'ask', onLoad: () => loads++,
    'onUpdate:modelValue': value => updates.push(value) })
  await state.show()
  assert.equal(loads, 1)
  assert.equal(state.rules.length, 237)
  state.setRule('mcp:notes:read.remote.0', 'auto_approve')
  state.turnPage(4)
  assert.equal(state.visibleRules.length, 20)
  state.query = 'research'; await nextTick()
  assert.equal(state.results.length, 235)
  assert.equal(state.page, 1)
  assert.equal(state.draft['mcp:notes:read.remote.0'], 'auto_approve')
  assert.equal(updates.length, 0)
  state.open = false
  await state.show()
  assert.equal(state.draft['mcp:notes:read.remote.0'], undefined)
  state.confirm()
  assert.equal(updates.length, 0)
  await state.show()
  state.setRule('mcp:old:write', 'inherit')
  state.setRule('mcp:notes:read.remote.0', 'ask')
  state.customOnly = true; await nextTick()
  assert.equal(state.results.length, 2)
  state.confirm()
  assert.deepEqual(updates, [{ untouched: 'auto_approve', 'mcp:notes:read.remote.0': 'ask' }])
  assert.deepEqual(original, { 'mcp:old:write': 'ask', untouched: 'auto_approve' })
})

test('approval changes remain blocked for read-only, busy, failed and loading catalogs', async t => {
  const { mount } = await setup(t, 'AgentToolApproval', 'components')
  for (const guard of [{ readonly: true }, { disabled: true }, { loading: true }, { error: 'Discovery failed' }]) {
    const state = await mount({ ...guard, modelValue: { write: 'ask' },
      'onUpdate:modelValue': () => { throw new Error('blocked approval mutation') } })
    await state.show(); state.setRule('write', 'auto_approve'); state.confirm()
    assert.equal(state.draft.write, guard.disabled ? undefined : 'ask')
  }
})

test('agent approval discovery starts in the subpage and confirming rules preserves defaults and tool grants', async t => {
  const { mount } = await setup(t, 'AgentEditor', 'components')
  const form = { name: 'Agent', tools: ['file_read'], external_tools: ['mcp_notes_read'],
    tool_approval: { default: 'ask', tools: { file_read: 'auto_approve' } } }
  let updated, loads = 0
  const state = await mount({ form, 'onLoad-approval-tools': () => loads++, 'onUpdate:form': value => { updated = value } })
  state.activeSection = 'approval'; await nextTick()
  assert.equal(loads, 0)
  state.setApprovalRules({ file_read: 'auto_approve', 'mcp:notes:read.remote': 'ask' })
  assert.equal(updated.tool_approval.default, 'ask')
  assert.deepEqual(updated.tools, form.tools)
  assert.deepEqual(updated.external_tools, form.external_tools)
  assert.deepEqual(form.tool_approval.tools, { file_read: 'auto_approve' })
  const readonly = await mount({ form, readonly: true, 'onUpdate:form': () => { throw new Error('readonly mutation') } })
  readonly.setApprovalRules({})
  const legacy = await mount({ form: { name: 'Legacy', tool_approval: null }, 'onUpdate:form': () => { throw new Error('legacy policy changed') } })
  legacy.setApprovalRules({ file_read: 'ask' })
})

test('protocol adapters show concurrent runtime bindings without a single-choice editor or writes', async t => {
  const { api, Component, mount } = await setup(t, 'Plugins')
  const capability = 'interface.protocol-adapter'
  const plugins = ['a2a', 'ag-ui', 'native', 'acp', 'mcp'].map(name => ({ id: `sage.protocol.${name}`, capabilities: [capability], schema: {} }))
  t.mock.method(api, 'listPlugins', async () => ({ defaults: { [capability]: 'sage.protocol.mcp' }, plugins }))
  t.mock.method(api, 'serverPlugins', async () => ({ configurable: [capability], providers: [
    { capability, plugin_id: 'sage.protocol.ag-ui' }, { capability, plugin_id: 'sage.protocol.native' },
  ], saved: {}, defaults: {}, pending: [] }))
  t.mock.method(api, 'saveServerPlugins', async () => { throw Error('protocol write') })
  const state = await mount()
  assert.equal(state.currentGroup.name, '协议适配器')
  assert.equal(state.canConfigure(capability), false)
  assert.equal(state.currentNames(state.currentGroup), 'AG-UI、Native')
  assert.equal(state.protocolStatus(plugins[1]), '已启用')
  assert.equal(state.protocolStatus(plugins[2]), '已启用')
  assert.equal(state.protocolStatus(plugins[4]), '未启用')
  state.startEdit(state.currentGroup); state.selectImplementation(plugins[4]); await state.saveServer()
  assert.equal(state.editing, '')
  assert.equal(api.saveServerPlugins.mock.calls.length, 0)
  const html = await renderToString(createSSRApp({ ...Component, setup: () => state }))
  assert.match(html, /协议列表/)
  assert.match(html, /传输流式回复、工具状态和审批交互/)
  assert.match(html, /适配器本身不启动 MCP 服务/)
  assert.doesNotMatch(html, /option-indicator|aria-pressed|实现选择|已保存默认|保存系统默认/)
  state.server.providers = []
  assert.equal(state.protocolStatus(plugins[4]), '未启用')
  assert.equal(state.currentNames(state.currentGroup), '暂无已启用协议')
  delete state.server.providers
  assert.equal(state.protocolStatus(plugins[4]), '状态未知')
  assert.equal(state.currentNames(state.currentGroup), '状态未知')
})

test('agent success feedback expires, restarts for a new save and clears on returning to the list', async t => {
  const { api, mount } = await setup(t, 'Agents')
  const own = { id: 'own', name: 'Assistant', tools: [], skills: [] }
  t.mock.method(api, 'agentSummaries', async () => [own])
  t.mock.method(api, 'agentEditorResources', async () => editorResources())
  t.mock.method(api, 'getAgent', async () => own)
  t.mock.method(api, 'updateAgent', async (id, body) => ({ ...body, id }))
  t.mock.method(api, 'bindAgentSkills', async () => [])
  const state = await mount()
  await state.openAgent(own, false)
  await new Promise(resolve => setImmediate(resolve))
  t.mock.timers.enable({ apis: ['setTimeout'] })
  await state.save(false)
  assert.equal(state.savedMessage, '已保存')
  t.mock.timers.tick(2999)
  assert.equal(state.savedMessage, '已保存')
  t.mock.timers.tick(1)
  assert.equal(state.savedMessage, '')

  await state.save(false)
  t.mock.timers.tick(2000)
  await state.save(false)
  t.mock.timers.tick(1000)
  assert.equal(state.savedMessage, '已保存')
  t.mock.timers.tick(2000)
  assert.equal(state.savedMessage, '')

  await state.save(false)
  state.closeEditor()
  assert.equal(state.drawerOpen, false)
  assert.equal(state.savedMessage, '')
  await state.openAgent(own, false)
  await state.save(true)
  assert.equal(state.drawerOpen, false)
  assert.equal(state.savedMessage, '已保存')
  t.mock.timers.tick(3000)
  assert.equal(state.savedMessage, '')

  await state.openAgent(own, false)
  api.updateAgent.mock.mockImplementation(async () => { throw Error('保存失败') })
  await state.save(false)
  t.mock.timers.tick(5000)
  assert.equal(state.savedMessage, '')
  assert.equal(state.error, '保存失败')
})


test('IM detail displays unavailable credentials and allows a recovery check', async t => {
  const { api, Component, mount } = await setup(t, 'FeishuConnectionDetail', 'components')
  const connection = { id: 'im_broken', name: 'Broken', enabled: false, paired: true, revision: 4, agent_id: 'own', config: {}, credentials_error: '请恢复密钥备份', credentials_configured: true }
  t.mock.method(api, 'imConnection', async () => connection)
  t.mock.method(api, 'imConnectionStatus', async () => ({ state: 'unavailable', revision: 4, paired: true }))
  t.mock.method(api, 'imDeliveries', async () => ({ items: [], next_cursor: null }))
  const state = await mount({ connection })
  assert.equal(state.stateLabel, '不可用')
  assert.equal(state.locked, false)
  const html = await renderToString(createSSRApp(Component, { connection }))
  assert.match(html, /role="alert">请恢复密钥备份/)
  assert.match(html, /测试凭据/)
})

test('chat IM notification selector uses only personal ready connections and clears revoked targets', async t => {
  const { api, mount } = await setup(t, 'IMNotificationSelect', 'components')
  let connections = [
    { id: 'own', name: 'My IM', enabled: true, paired: true, credentials_error: '' },
    { id: 'unpaired', name: 'Unpaired', enabled: true, paired: false },
    { id: 'disabled', name: 'Disabled', enabled: false, paired: true },
    { id: 'broken', name: 'Broken', enabled: true, paired: true, credentials_error: 'bad key' },
    { id: 'foreign', name: 'Foreign', enabled: true, paired: true, _owner: { user_id: 'other' } },
  ]
  t.mock.method(api, 'imConnections', async () => ({ items: connections }))
  const selected = []
  const state = await mount({ modelValue: 'own', 'onUpdate:modelValue': value => selected.push(value) })
  assert.deepEqual(state.connections.map(row => row.id), ['own'])
  connections = []
  await state.load()
  assert.deepEqual(selected, [''])
  assert.equal(api.imConnections.mock.calls[0].arguments.length, 0)
})
