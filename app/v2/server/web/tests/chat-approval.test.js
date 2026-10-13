import assert from 'node:assert/strict'
import { test } from 'node:test'
import { createRenderer, nextTick, ssrContextKey } from 'vue'
import { createServer } from 'vite'

test('chat approval rewinds messages and reaches resume without cloning Vue proxies', async (t) => {
  const server = await createServer({
    server: { middlewareMode: true, watch: null, hmr: false, ws: false },
  })
  t.after(() => server.close())
  t.mock.method(globalThis, 'fetch', async (url, init) => {
    if (String(url).endsWith('/resume')) {
      const { runId } = JSON.parse(init.body)
      return new Response([
        { type: 'RUN_STARTED', threadId: 'thread-test', runId },
        { type: 'RUN_FINISHED', threadId: 'thread-test', runId },
      ].map((event) => `data: ${JSON.stringify(event)}\n\n`).join(''), {
        headers: { 'Content-Type': 'text/event-stream' },
      })
    }
    return Response.json({ data: [] })
  })
  const previousStorage = Object.getOwnPropertyDescriptor(globalThis, 'localStorage')
  Object.defineProperty(globalThis, 'localStorage', {
    configurable: true,
    value: { getItem: () => '', setItem() {} },
  })
  t.after(() => {
    if (previousStorage) Object.defineProperty(globalThis, 'localStorage', previousStorage)
    else delete globalThis.localStorage
  })

  const { default: Chat } = await server.ssrLoadModule('/src/views/Chat.vue')
  // Exercise the real component setup and handlers without a DOM or backend.
  const renderer = createRenderer({
    createComment: () => ({}), insert() {}, remove() {},
    parentNode: () => null, nextSibling: () => null,
  })
  const app = renderer.createApp({ ...Chat, render: () => null })
  app.provide(ssrContextKey, {})
  const vm = app.mount({})
  t.after(() => app.unmount())
  await new Promise((resolve) => setImmediate(resolve))
  await nextTick()
  const state = vm.$.setupState
  const history = [{ id: 'user-1', role: 'user', content: 'draw a robot' }]
  state.messages = history
  state.baseline = [...state.messages]
  state.threadId = 'thread-test'
  state.interaction = {
    allowed_decisions: ['approve_once'],
    payload: { tool_name: 'execute_shell_command', arguments: { command: 'echo ok' } },
  }

  await state.decide({ decision: 'approve_once', payload: {} })

  assert.equal(state.error, '')
  assert.equal(state.interaction, null)
  assert.equal(state.pending, false)
  assert.deepEqual(state.messages, history)
  const resumes = fetch.mock.calls.filter(({ arguments: [url] }) => String(url).endsWith('/resume'))
  assert.equal(resumes.length, 1)
  assert.equal(resumes[0].arguments[0], '/api/threads/thread-test/resume')
  assert.equal(JSON.parse(resumes[0].arguments[1].body).decision, 'approve_once')

  // Switching agents also hands the displayed messages back to the SDK.
  assert.doesNotThrow(() => state.selectAgent())
  assert.deepEqual(state.agent.messages, history)
})
