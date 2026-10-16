import assert from 'node:assert/strict'
import { test } from 'node:test'
import { createRenderer, nextTick, ssrContextKey } from 'vue'
import { createServer } from 'vite'

async function setup(t, name, directory = 'views') {
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
  const { default: Component } = await server.ssrLoadModule(`/src/${directory}/${name}.vue`)
  return { api, mount: async (props = {}) => {
    const renderer = createRenderer({ createComment: () => ({}), insert() {}, remove() {}, parentNode: () => null, nextSibling: () => null })
    const app = renderer.createApp({ ...Component, render: () => null }, props)
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
  t.mock.method(api, 'listPlugins', async () => ({ configurable: ['context.summarizer'] }))
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
  t.mock.method(api, 'listPlugins', async () => ({ configurable: ['context.summarizer'] }))
  for (const method of ['listAgents', 'listModels', 'listMcp', 'listA2aAgents', 'listSkills', 'listTools', 'listAgentSkills']) t.mock.method(api, method, async () => [])
  t.mock.method(api, 'createAgent', async body => ({ ...body, id: 'new-agent' }))
  t.mock.method(api, 'updateAgent', async (id, body) => ({ ...body, id }))
  t.mock.method(api, 'bindAgentSkills', async () => [])
  const state = await mount()
  state.startNew()
  state.form.name = 'New agent'
  state.form.tools = ['file_read']
  state.form.tool_approval.tools = { file_read: 'ask', 'mcp:drive:write': 'auto_approve' }
  state.selectedSkills = ['research']
  await state.save(false)
  assert.equal(state.drawerOpen, true)
  assert.equal(state.editing, 'new-agent')
  assert.deepEqual(api.bindAgentSkills.mock.calls[0].arguments, ['new-agent', ['research']])
  assert.deepEqual(Object.keys(api.createAgent.mock.calls[0].arguments[0]).sort(), ['budgets', 'description', 'execution_policy', 'instructions', 'model_id', 'name', 'plugins', 'sandbox', 'tool_approval', 'tools'])
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
  t.mock.method(api, 'listAgents', async () => [{ id: 'own-agent', name: 'My agent' }])
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

test('personal settings reads and saves only the current account policy even for admins', async t => {
  const { api, mount } = await setup(t, 'PersonalSettings')
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
  state.query = '抽取式摘要'
  assert.equal(state.groups.length, 1)
  state.query = 'unmatched'
  assert.equal(state.groups.length, 0)
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
  for (const group of state.groups) {
    const rows = state.parameterRows(group)
    if (group.id === 'context.summarizer') assert.equal(rows[0].value, '30')
    else {
      assert.deepEqual(rows, [])
      assert.equal(state.currentNames(group), 'Server 提供')
    }
  }
  state.server = null
  assert.doesNotThrow(() => state.parameterRows(state.groups[0]))
})
