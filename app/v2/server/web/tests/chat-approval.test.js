import assert from 'node:assert/strict'
import { test } from 'node:test'
import { createRenderer, nextTick, ssrContextKey } from 'vue'
import { createServer } from 'vite'

for (const mode of ['approval', 'questionnaire', 'ordinary-message', 'questionnaire-retry']) {
  test(`chat ${mode} uses the expected Run endpoint`, async (t) => {
    const server = await createServer({
      server: { middlewareMode: true, watch: null, hmr: false, ws: false },
    })
    t.after(() => server.close())
    let startedRequests = 0
    t.mock.method(globalThis, 'fetch', async (url, init) => {
      if (String(url).endsWith('/resume') || String(url) === '/api/agent') {
        if (mode === 'questionnaire-retry' && ++startedRequests === 1) {
          throw new Error('connection lost before acceptance')
        }
        const { runId } = JSON.parse(init.body)
        return new Response([
          { type: 'RUN_STARTED', threadId: 'thread-test', runId },
          { type: 'RUN_FINISHED', threadId: 'thread-test', runId },
        ].map((event) => `data: ${JSON.stringify(event)}\n\n`).join(''), {
          headers: { 'Content-Type': 'text/event-stream' },
        })
      }
      return Response.json({ data: String(url).startsWith('/api/threads?') ? { items: [], next_cursor: null } : [] })
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
    state.agent.setMessages(history)
    state.threadId = 'thread-test'
    state.configurationLoaded = true
    state.agents = [{ id: 'agent-test' }]
    state.selectedAgentId = 'agent-test'
    state.hasModel = true
    state.interaction = mode === 'approval' ? {
      allowed_decisions: ['approve_once'],
      payload: { tool_name: 'execute_shell_command', arguments: { command: 'echo ok' } },
    } : {
      interaction_type: 'questionnaire',
      allowed_decisions: ['submit'],
      payload: { title: 'Deployment target' },
      reply_as_new_run: true,
    }

    if (mode === 'ordinary-message') {
      state.text = 'Continue without answering'
      assert.equal(state.canSend, true)
      await state.submit()
    } else {
      await state.decide(mode === 'approval'
        ? { decision: 'approve_once', payload: {} }
        : { decision: 'submit', payload: { text: 'staging' } })
    }

    if (mode === 'questionnaire-retry') {
      assert.equal(state.error, 'connection lost before acceptance')
      assert.equal(state.interaction.reply_as_new_run, true)
      assert.equal(state.text, 'staging')
      assert.equal(state.pending, false)
      await state.decide({ decision: 'submit', payload: { text: 'staging' } })
    }

    assert.equal(state.error, '')
    assert.equal(state.interaction, null)
    assert.equal(state.pending, false)
    const resumes = fetch.mock.calls.filter(({ arguments: [url] }) => String(url).endsWith('/resume'))
    const starts = fetch.mock.calls.filter(({ arguments: [url] }) => String(url) === '/api/agent')
    assert.equal(resumes.length, mode === 'approval' ? 1 : 0)
    assert.equal(starts.length, mode === 'approval' ? 0 : mode === 'questionnaire-retry' ? 2 : 1)
    if (mode === 'questionnaire-retry') assert.deepEqual(JSON.parse(starts[0].arguments[1].body), JSON.parse(starts[1].arguments[1].body))
    if (mode === 'approval') {
      assert.deepEqual(state.messages, history)
      assert.equal(JSON.parse(resumes[0].arguments[1].body).decision, 'approve_once')
    } else {
      const body = JSON.parse(starts[0].arguments[1].body)
      assert.equal(body.session_id, 'thread-test')
      assert.equal(body.messages.at(-1).content, mode.startsWith('questionnaire') ? 'staging' : 'Continue without answering')
    }

    // Switching agents also hands the displayed messages back to the SDK.
    assert.doesNotThrow(() => state.selectAgent())
    assert.deepEqual(state.agent.messages, state.messages)
  })

}
