import assert from 'node:assert/strict'
import { test } from 'node:test'
import { createRenderer, createSSRApp, nextTick, ssrContextKey } from 'vue'
import { renderToString } from 'vue/server-renderer'
import { routerKey } from 'vue-router'
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
  assert.deepEqual(Object.keys(api.createAgent.mock.calls[0].arguments[0]).sort(), ['budgets', 'description', 'execution_policy', 'external_tools', 'fast_model_id', 'instructions', 'memory', 'model_id', 'name', 'plugins', 'sandbox', 'tool_approval', 'tools'])
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
  assert.equal(state.groups.length, 3)
  assert.ok(!state.groups.some(group => group.id === 'context.summarizer'))
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
  assert.match(html, /已保存：本地 BM25 记忆/)
  assert.match(html, /配置 Server/)
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


test('agent editor selects external tools independently and keeps unavailable selections removable', async t => {
  const { Component, mount } = await setup(t, 'AgentEditor', 'components')
  let form = { name: 'Scoped', tools: ['file_read'], external_tools: ['mcp_old'], execution_policy: { shell: 'ask' } }
  const state = await mount({ form, externalTools: ['mcp_read', 'a2a_peer_search'],
    'onUpdate:form': value => { form = value } })
  assert.deepEqual(state.availableExternalTools, ['mcp_read', 'a2a_peer_search', 'mcp_old'])
  state.toggleExternalTool('mcp_read')
  assert.deepEqual(form.external_tools, ['mcp_old', 'mcp_read'])
  assert.deepEqual(form.tools, ['file_read'])
  const html = await renderToString(createSSRApp(Component, { form, externalTools: ['mcp_read', 'a2a_peer_search'] }))
  assert.match(html, /仅允许所选工具/)
  assert.match(html, /mcp_read/)
})

test('agents retain external scope through opening and saving, excluding disabled connections', async t => {
  const { api, mount } = await setup(t, 'Agents')
  t.mock.method(api, 'listPlugins', async () => ({ configurable: [] }))
  const agent = { id: 'scoped', name: 'Scoped', tools: ['file_read'], external_tools: ['mcp_read'] }
  for (const method of ['listModels', 'listSkills', 'listTools', 'listAgentSkills']) t.mock.method(api, method, async () => [])
  t.mock.method(api, 'listAgents', async () => [agent])
  t.mock.method(api, 'getAgent', async () => agent)
  t.mock.method(api, 'listMcp', async () => [{ tools: ['mcp_read'] }, { disabled: true, tools: ['mcp_disabled'] }])
  t.mock.method(api, 'listA2aAgents', async () => [{ skills: ['a2a_search'] }])
  t.mock.method(api, 'updateAgent', async (id, body) => ({ ...body, id }))
  t.mock.method(api, 'bindAgentSkills', async () => [])
  const state = await mount()
  assert.deepEqual(state.externalTools, ['mcp_read', 'a2a_search'])
  await state.openAgent(agent, false)
  assert.deepEqual(state.form.external_tools, ['mcp_read'])
  state.form.external_tools = []
  await state.save(false)
  assert.deepEqual(api.updateAgent.mock.calls[0].arguments[1].external_tools, [])
  state.startNew()
  assert.deepEqual(state.form.external_tools, [])
})
