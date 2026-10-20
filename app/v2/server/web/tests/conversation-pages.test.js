import assert from 'node:assert/strict'
import { test } from 'node:test'
import { createRenderer, createSSRApp, nextTick, ssrContextKey } from 'vue'
import { renderToString } from 'vue/server-renderer'
import { createMemoryHistory, createRouter } from 'vue-router'
import { createServer } from 'vite'

async function setup(t, name, target) {
  const server = await createServer({ optimizeDeps: { noDiscovery: true, include: [] }, server: { middlewareMode: true, watch: null, hmr: false, ws: false } })
  t.after(() => server.close())
  const values = new Map([['sage.server_v2.user', JSON.stringify({ user_id: 'me', role: 'admin' })]])
  const restorers = []
  for (const [key, value] of Object.entries({
    localStorage: { getItem: key => values.get(key) || '', setItem: (key, value) => values.set(key, value) },
    document: { addEventListener() {}, removeEventListener() {}, getElementById: () => null },
  })) {
    const previous = Object.getOwnPropertyDescriptor(globalThis, key)
    Object.defineProperty(globalThis, key, { configurable: true, value })
    restorers.push(() => previous ? Object.defineProperty(globalThis, key, previous) : delete globalThis[key])
  }
  const { api } = await server.ssrLoadModule('/src/api.js')
  const { default: Component } = await server.ssrLoadModule(`/src/views/${name}.vue`)
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/:pathMatch(.*)*', component: { render: () => null } }] })
  await router.push(target || '/?new=1')
  const mount = async () => {
    const renderer = createRenderer({ createComment: () => ({}), insert() {}, remove() {}, parentNode: () => null, nextSibling: () => null })
    const app = renderer.createApp({ ...Component, render: () => null }).use(router)
    app.provide(ssrContextKey, {})
    const vm = app.mount({})
    t.after(() => { app.unmount(); for (const restore of restorers) restore() })
    await new Promise(resolve => setImmediate(resolve)); await nextTick()
    return vm.$.setupState
  }
  return { api, mount, router, Component }
}

test('history loads cursor pages, filters on the server, retains rows on failure, and keeps failed deletion open', async t => {
  const { api, mount } = await setup(t, 'History', '/history')
  const own = { thread_id: 'own', title: '项目规划', agent_id: 'a' }
  const foreign = { thread_id: 'foreign', title: '研究资料', agent_id: 'a', _owner: { user_id: 'alice', username: 'Alice' } }
  t.mock.method(api, 'listThreads', async params => ({ items: params.cursor ? [foreign] : [own], next_cursor: params.cursor ? null : 'page-2' }))
  t.mock.method(api, 'agentSummaries', async () => [{ id: 'a', name: '写作助手' }, { id: 'b', name: '研究助手', _owner: foreign._owner }])
  t.mock.method(api, 'deleteThread', async () => { throw Error('删除失败') })
  const state = await mount()
  assert.deepEqual(state.visible.map(item => item.thread_id), ['own'])
  assert.equal(state.nextCursor, 'page-2')
  await state.load(true)
  assert.deepEqual(state.visible.map(item => item.thread_id), ['own', 'foreign'])
  assert.equal(api.listThreads.mock.calls[1].arguments[0].cursor, 'page-2')
  assert.equal(state.nextCursor, null)
  t.mock.method(api, 'listThreads', async params => {
    assert.equal(params.search, '研究助手'); assert.equal(params.agent_id, 'b'); assert.equal(params.cursor, undefined)
    return { items: [foreign], next_cursor: null }
  })
  state.search = '研究助手'; state.agentFilter = 'b'
  await nextTick(); await new Promise(resolve => setTimeout(resolve, 230)); await nextTick()
  assert.deepEqual(state.visible.map(item => item.thread_id), ['foreign'])
  state.requestDelete(foreign); assert.equal(state.deleteTarget, null)
  state.requestDelete(own); await state.remove()
  assert.equal(state.deleteTarget.thread_id, 'own'); assert.equal(state.deleteError, '删除失败')
  t.mock.method(api, 'listThreads', async () => { throw Error('读取失败') })
  await state.load()
  assert.equal(state.error, '读取失败'); assert.deepEqual(state.threads.map(item => item.thread_id), ['foreign'])
  t.mock.method(api, 'deleteThread', async () => {})
  await state.remove()
  assert.equal(state.deleteTarget, null)
})

test('chat opens an older direct link with its owner and pinned agent even outside the first thread page', async t => {
  const { api, mount } = await setup(t, 'Chat', '/?thread=older')
  t.mock.method(api, 'listThreads', async () => ({ items: [], next_cursor: 'more' }))
  t.mock.method(api, 'thread', async id => ({ thread_id: id, title: '旧会话', agent_id: 'b', _owner: { user_id: 'alice', username: 'Alice' } }))
  t.mock.method(api, 'listAgents', async () => [{ id: 'a' }])
  t.mock.method(api, 'listModels', async () => [{ id: 'm' }])
  t.mock.method(api, 'threadEvents', async (id, limit, owner) => {
    assert.equal(id, 'older'); assert.equal(owner.user_id, 'alice')
    return { events: [], total: 0, offset: 0, limit: 500 }
  })
  const state = await mount()
  assert.equal(state.selectedAgentId, 'b'); assert.equal(state.readOnly, true)
  assert.equal(state.threadTitle, '旧会话'); assert.equal(state.agentLocked, true)
})

test('new chat preserves drafts when configuration fails, disables sends without models, and sends through AG-UI', async t => {
  const { api, mount } = await setup(t, 'Chat')
  t.mock.method(api, 'listThreads', async () => ({ items: [], next_cursor: null }))
  t.mock.method(api, 'listAgents', async () => [{ id: 'a', name: '助手' }])
  t.mock.method(api, 'listModels', async () => [])
  t.mock.method(globalThis, 'fetch', async (url, init) => {
    assert.equal(url, '/api/agent')
    const { threadId, runId } = JSON.parse(init.body)
    return new Response([{ type: 'RUN_STARTED', threadId, runId }, { type: 'RUN_FINISHED', threadId, runId }].map(event => `data: ${JSON.stringify(event)}\n\n`).join(''), { headers: { 'Content-Type': 'text/event-stream' } })
  })
  const state = await mount()
  state.text = '保留这段草稿'
  assert.equal(state.isStart, true)
  assert.equal(state.canSend, false)
  await state.send()
  assert.equal(state.text, '保留这段草稿'); assert.equal(fetch.mock.calls.length, 0)
  t.mock.method(api, 'listModels', async () => { throw Error('配置读取失败') })
  await state.initialize()
  assert.equal(state.setupFailed, true); assert.equal(state.text, '保留这段草稿')
  t.mock.method(api, 'listModels', async () => [{ id: 'model' }])
  await state.initialize()
  assert.equal(state.canSend, true)
  let prevented = false
  state.inputKeydown({ key: 'Enter', isComposing: true, preventDefault() { prevented = true } })
  assert.equal(prevented, false); assert.equal(fetch.mock.calls.length, 0)
  state.selectedSkills = ['wishseen-project', 'review']
  await state.send()
  assert.equal(fetch.mock.calls.length, 1)
  assert.equal(state.isStart, false); assert.equal(state.agentLocked, true)
  assert.equal(state.text, '')
  assert.equal(JSON.parse(fetch.mock.calls[0].arguments[1].body).messages[0].content, '<skill>wishseen-project</skill> <skill>review</skill> 保留这段草稿')
  assert.deepEqual(state.selectedSkills, [])
  state.selectedSkills = ['wishseen-project']
  assert.equal(state.canSend, true)
  await state.send()
  assert.equal(JSON.parse(fetch.mock.calls[1].arguments[1].body).messages.at(-1).content, '<skill>wishseen-project</skill>')
  state.selectedSkills = ['review']
  state.startNew()
  assert.deepEqual(state.selectedSkills, [])
})

test('approval remains visible during submission, preserves a failed answer, and does not resurrect after a list refresh failure', async t => {
  const { api, mount } = await setup(t, 'Chat')
  t.mock.method(api, 'listThreads', async () => ({ items: [], next_cursor: null }))
  t.mock.method(api, 'listAgents', async () => [{ id: 'a' }])
  t.mock.method(api, 'listModels', async () => [{ id: 'm' }])
  let finish, fail = true
  t.mock.method(globalThis, 'fetch', async (url, init) => {
    assert.match(url, /\/resume$/)
    if (fail) { await new Promise(resolve => { finish = resolve }); throw Error('提交失败') }
    const { runId } = JSON.parse(init.body)
    return new Response([{ type: 'RUN_STARTED', threadId: 'thread-test', runId }, { type: 'RUN_FINISHED', threadId: 'thread-test', runId }].map(event => `data: ${JSON.stringify(event)}\n\n`).join(''), { headers: { 'Content-Type': 'text/event-stream' } })
  })
  const state = await mount()
  state.threadId = 'thread-test'
  state.interaction = { interaction_id: 'question', interaction_type: 'user_input', allowed_decisions: ['submit'], payload: {} }
  await nextTick(); state.interactionAnswer = '保留这个回答'
  state.messages = [{ id: 'before-submit', role: 'assistant', content: '保留已读的工具结果' }]
  const sending = state.decide({ decision: 'submit', payload: { text: state.interactionAnswer } })
  await new Promise(resolve => setImmediate(resolve))
  assert.equal(state.activeInteraction.interaction_id, 'question'); assert.equal(state.pending, true)
  assert.equal(state.messages[0].content, '保留已读的工具结果')
  await state.decide({ decision: 'submit', payload: { text: 'duplicate' } })
  assert.equal(fetch.mock.calls.length, 1)
  finish(); await sending; await nextTick()
  assert.equal(state.interactionAnswer, '保留这个回答')
  assert.equal(state.messages[0].content, '保留已读的工具结果')
  assert.equal(state.decisionError, '提交失败'); assert.equal(state.interaction.interaction_id, 'question')
  fail = false
  t.mock.method(api, 'listThreads', async () => { throw Error('列表刷新失败') })
  await state.decide({ decision: 'submit', payload: { text: state.interactionAnswer } })
  assert.equal(state.activeInteraction, null); assert.equal(state.decisionError, '')
  assert.equal(state.error, '列表刷新失败')
})

test('live chat accepts supplemental input once, preserves failures, and cancels the backend without reconnecting', async t => {
  const { api, mount } = await setup(t, 'Chat')
  t.mock.method(api, 'listThreads', async () => ({ items: [], next_cursor: null }))
  t.mock.method(api, 'listAgents', async () => [{ id: 'a' }])
  t.mock.method(api, 'listModels', async () => [{ id: 'm' }])
  let stream, request, failSteer = true, failStop = true
  const encoder = new TextEncoder()
  const emit = (...events) => stream.enqueue(encoder.encode(events.map(event => `data: ${JSON.stringify(event)}\n\n`).join('')))
  t.mock.method(globalThis, 'fetch', async (url, init) => {
    request = JSON.parse(init.body)
    return new Response(new ReadableStream({ start(controller) {
      stream = controller
      emit({ type: 'RUN_STARTED', threadId: request.threadId, runId: request.runId },
        { type: 'TEXT_MESSAGE_START', messageId: 'reply', role: 'assistant' },
        { type: 'TEXT_MESSAGE_CONTENT', messageId: 'reply', delta: '保留已有内容' })
    } }), { headers: { 'Content-Type': 'text/event-stream' } })
  })
  const supplements = []
  t.mock.method(api, 'steerThreadRun', async (id, body) => {
    supplements.push(body)
    assert.equal(id, request.threadId); assert.equal(body.runId, request.runId)
    if (failSteer) throw Error('网络失败')
    return { steer_id: 'steer-1', state: 'pending' }
  })
  t.mock.method(api, 'cancelThreadRun', async (id, runId) => {
    assert.equal(id, request.threadId); assert.equal(runId, request.runId)
    if (failStop) throw Error('取消失败')
    emit({ type: 'CUSTOM', name: 'sage.run.cancelled', value: { state: 'cancelled' } })
    stream.close()
    return { cancelled: true }
  })
  const state = await mount()
  state.text = '开始'
  const running = state.send()
  await new Promise(resolve => setImmediate(resolve))
  assert.equal(state.pending, true); assert.equal(state.streamStarted, true)
  state.text = '补充要求'
  state.selectedSkills = ['wishseen-project']
  assert.equal(state.canSend, true)
  await state.submit()
  assert.equal(state.text, '补充要求'); assert.match(state.error, /补充发送失败/)
  assert.deepEqual(state.selectedSkills, ['wishseen-project'])
  failSteer = false
  await state.submit()
  assert.equal(supplements[0].messageId, supplements[1].messageId)
  assert.equal(supplements[1].text, '<skill>wishseen-project</skill> 补充要求')
  assert.deepEqual(state.selectedSkills, [])
  assert.equal(state.text, ''); assert.equal(state.queuedSupplements.length, 1)
  assert.equal(fetch.mock.calls.length, 1)
  emit({ type: 'CUSTOM', name: 'sage.steer.applied', value: { steer_id: 'steer-1' } },
    { type: 'TEXT_MESSAGE_END', messageId: 'reply' },
    { type: 'TEXT_MESSAGE_START', messageId: 'canonical-extra', role: 'user' },
    { type: 'TEXT_MESSAGE_CONTENT', messageId: 'canonical-extra', delta: '补充要求' },
    { type: 'TEXT_MESSAGE_END', messageId: 'canonical-extra' })
  await new Promise(resolve => setImmediate(resolve))
  assert.equal(state.queuedSupplements.length, 0)
  assert.equal(state.displayMessages.filter(message => message.content === '补充要求').length, 1)
  await state.stop()
  assert.equal(state.pending, true); assert.equal(state.stopping, false)
  assert.match(state.error, /停止失败/)
  failStop = false
  await state.stop(); await running
  assert.equal(state.pending, false); assert.equal(state.stopping, false)
  assert.equal(state.error, ''); assert.equal(fetch.mock.calls.length, 1)
  assert.equal(state.messages.some(message => message.content === '保留已有内容'), true)
})

test('unreceived supplemental text returns to the draft when the run finishes', async t => {
  const { api, mount } = await setup(t, 'Chat')
  t.mock.method(api, 'listThreads', async () => ({ items: [], next_cursor: null }))
  t.mock.method(api, 'listAgents', async () => [{ id: 'a' }])
  t.mock.method(api, 'listModels', async () => [{ id: 'm' }])
  t.mock.method(api, 'steerThreadRun', async () => ({ steer_id: 'unclaimed', state: 'pending' }))
  let finish
  t.mock.method(globalThis, 'fetch', async (url, init) => {
    const { threadId, runId } = JSON.parse(init.body), encoder = new TextEncoder()
    return new Response(new ReadableStream({ start(controller) {
      controller.enqueue(encoder.encode(`data: ${JSON.stringify({ type: 'RUN_STARTED', threadId, runId })}\n\n`))
      finish = () => { controller.enqueue(encoder.encode(`data: ${JSON.stringify({ type: 'RUN_FINISHED', threadId, runId })}\n\n`)); controller.close() }
    } }), { headers: { 'Content-Type': 'text/event-stream' } })
  })
  const state = await mount()
  state.text = '开始'
  const running = state.send()
  await new Promise(resolve => setImmediate(resolve))
  state.text = '不能丢失的补充'
  await state.submit()
  state.text = '正在编辑的新草稿'
  finish(); await running
  assert.equal(state.text, '不能丢失的补充\n\n正在编辑的新草稿')
  assert.equal(state.queuedSupplements.length, 0)
  assert.match(state.error, /已放回输入框/)
})


test('new chat loads quietly without exposing a cached agent id or shifting the composer with loading notices', async t => {
  const { api, mount, router, Component } = await setup(t, 'Chat')
  const cachedId = 'agent_cached_internal_id'
  localStorage.setItem('sage.server_v2.agent', cachedId)
  let finishAgents, finishModels
  t.mock.method(api, 'listThreads', async () => ({ items: [], next_cursor: null }))
  t.mock.method(api, 'listAgents', () => new Promise(resolve => { finishAgents = resolve }))
  t.mock.method(api, 'listModels', () => new Promise(resolve => { finishModels = resolve }))
  const state = await mount()
  const html = () => renderToString(createSSRApp({ ...Component, setup: () => state }).use(router))
  state.text = '初始化期间输入的草稿'
  assert.equal(state.initializing, true)
  assert.equal(state.selectedAgentId, cachedId)
  assert.equal(state.selectedAgentName, '智能体')
  assert.equal(state.composerPlaceholder, '输入消息…')
  assert.equal(state.canSend, false)
  const initialHtml = await html()
  assert.doesNotMatch(initialHtml, /agent_cached_internal_id|正在准备会话|class="conversation-notices"|class="conversation-agent"/)
  assert.match(initialHtml, /aria-busy="true"/)

  finishAgents([{ id: cachedId, name: '游戏问数' }])
  await new Promise(resolve => setImmediate(resolve))
  assert.equal(state.initializing, true)
  assert.equal(state.composerPlaceholder, '输入消息…')
  assert.doesNotMatch(await html(), /class="conversation-agent"/)
  finishModels([{ id: 'model' }])
  await new Promise(resolve => setImmediate(resolve)); await nextTick()
  assert.equal(state.initializing, false)
  assert.equal(state.composerPlaceholder, '向游戏问数提问…')
  assert.equal(state.text, '初始化期间输入的草稿')
  assert.equal(state.canSend, true)
  assert.match(await html(), /class="conversation-agent"/)
})
