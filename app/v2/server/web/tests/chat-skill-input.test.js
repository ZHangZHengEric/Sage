import assert from 'node:assert/strict'
import { test } from 'node:test'
import { createRenderer, nextTick, reactive, ssrContextKey } from 'vue'
import { createServer } from 'vite'

async function setup(t) {
  const server = await createServer({ optimizeDeps: { noDiscovery: true, include: [] }, server: { middlewareMode: true, watch: null, hmr: false, ws: false } })
  t.after(() => server.close())
  const { api } = await server.ssrLoadModule('/src/api.js')
  const { default: Component } = await server.ssrLoadModule('/src/components/ChatSkillInput.vue')
  const props = reactive({ modelValue: '', skills: [], agentId: 'a', agentPackage: null })
  const renderer = createRenderer({ createComment: () => ({}), insert() {}, remove() {}, parentNode: () => null, nextSibling: () => null })
  const app = renderer.createApp({ ...Component, render: () => null }, {
    ...props,
    'onUpdate:modelValue': value => { props.modelValue = value },
    'onUpdate:skills': value => { props.skills = value },
  })
  app.provide(ssrContextKey, {})
  const vm = app.mount({})
  t.after(() => app.unmount())
  // Update the real component's reactive props in this DOM-free renderer.
  const update = async values => { Object.assign(vm.$.props, values); Object.assign(props, values); await nextTick() }
  const state = vm.$.setupState
  state.textarea = { selectionStart: 0, selectionEnd: 0, focus() {}, setSelectionRange() {}, style: {}, scrollHeight: 54 }
  const query = async (value, caret = value.length) => {
    await update({ modelValue: value })
    state.textarea.selectionStart = state.textarea.selectionEnd = caret
    state.updateQuery()
    await new Promise(resolve => setImmediate(resolve)); await nextTick()
  }
  return { api, props, state, query, update }
}

test('slash filters bound skills at the caret, excludes URLs, and selection preserves surrounding text', async t => {
  const { api, props, state, query, update } = await setup(t)
  t.mock.method(api, 'listAgentSkills', async () => [{ name: 'wishseen-project' }, { name: 'review' }])
  await query('https://example.com/wish')
  assert.equal(state.query, null)
  assert.equal(api.listAgentSkills.mock.calls.length, 0)
  await query('请用 /WI 后续', 6)
  assert.deepEqual(state.options.map(item => item.name), ['wishseen-project'])
  assert.deepEqual(api.listAgentSkills.mock.calls[0].arguments, ['a'])
  await state.selectSkill(state.options[0]); await nextTick()
  assert.equal(props.modelValue, '请用  后续')
  assert.deepEqual(props.skills, ['wishseen-project'])
  await update({ skills: props.skills })
  await query('/')
  assert.deepEqual(state.options.map(item => item.name), ['review'])
  state.removeSkill('wishseen-project')
  assert.deepEqual(props.skills, [])
})

test('keyboard selection consumes Enter, Escape closes the list, and IME does not select', async t => {
  const { api, props, state, query } = await setup(t)
  t.mock.method(api, 'listAgentSkills', async () => [{ name: 'first' }, { name: 'second' }])
  await query('/')
  const pressed = key => ({ key, preventDefault() { this.prevented = true } })
  const composing = { ...pressed('Enter'), isComposing: true }
  state.keydown(composing)
  assert.deepEqual(props.skills, [])
  state.keydown(pressed('ArrowDown'))
  assert.equal(state.activeIndex, 1)
  const enter = pressed('Enter')
  state.keydown(enter); await nextTick()
  assert.equal(enter.prevented, true)
  assert.deepEqual(props.skills, ['second'])
  await query('/')
  state.keydown(pressed('Escape'))
  assert.equal(state.query, null)
})

test('agent changes discard stale results and selections; packages use their own declared skills', async t => {
  const { api, props, state, query, update } = await setup(t)
  let finish
  t.mock.method(api, 'listAgentSkills', () => new Promise(resolve => { finish = resolve }))
  await query('/')
  assert.equal(state.loading, true)
  await update({ skills: ['old'], agentId: 'b', agentPackage: { manifest: { agents: { b: { skills: ['package-only'] } } } } })
  assert.deepEqual(props.skills, [])
  finish([{ name: 'stale' }]); await nextTick()
  await query('/')
  assert.deepEqual(state.options.map(item => item.name), ['package-only'])
  assert.equal(api.listAgentSkills.mock.calls.length, 1)
  await update({ agentPackage: { manifest: { agents: { b: { skills: [] } } } } })
  await query('/')
  assert.deepEqual(state.options, [])
})

test('failed skill requests can be retried and never fall back to a global catalog', async t => {
  const { api, state, query } = await setup(t)
  t.mock.method(api, 'listAgentSkills', async () => { throw Error('加载失败') })
  await query('/')
  assert.equal(state.loadError, '加载失败')
  assert.deepEqual(state.options, [])
  t.mock.method(api, 'listAgentSkills', async () => [{ name: 'available' }])
  await state.loadSkills()
  assert.equal(state.loadError, '')
  assert.deepEqual(state.options.map(item => item.name), ['available'])
})
